import os

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from .ecuabet_client import EcuabetAPIError, EcuabetClient
from .models import Cuota1X2Snapshot, Partido


def _event_info(partido, client):
    # No dependemos de un champId fijo ni de que el evento ya tenga
    # ecuabet_event_id guardado. Ecuabet puede cambiar/usar IDs distintos
    # según la competición, por lo que resolvemos el partido por equipos.
    found = client.buscar_evento(
        partido.equipo_local.nombre,
        partido.equipo_visitante.nombre,
        league_name=getattr(partido.liga, "nombre", ""),
    )

    if partido.ecuabet_event_id != found["event_id"]:
        partido.ecuabet_event_id = found["event_id"]
        partido.save(update_fields=["ecuabet_event_id"])

    return found


def _save_snapshot(partido, quotes):
    selections = quotes["selections"]
    values = {"local": None, "empate": None, "visitante": None}
    odd_ids = {"local": None, "empate": None, "visitante": None}

    for selection in selections:
        kind = {
            1: "local",
            2: "empate",
            3: "visitante",
        }.get(selection.get("type_id"))

        if kind:
            values[kind] = selection.get("price")
            odd_ids[kind] = selection.get("odd_id")

        if str(selection.get("name", "")).strip().lower() == "empate":
            values["empate"] = selection.get("price")
            odd_ids["empate"] = selection.get("odd_id")

    score = next(
        (selection.get("score") for selection in selections if selection.get("score") is not None),
        None,
    ) or []

    return Cuota1X2Snapshot.objects.create(
        partido=partido,
        ecuabet_event_id=quotes["event_id"],
        odd_id_local=odd_ids["local"],
        odd_id_empate=odd_ids["empate"],
        odd_id_visitante=odd_ids["visitante"],
        cuota_local=values["local"],
        cuota_empate=values["empate"],
        cuota_visitante=values["visitante"],
        es_live=any(selection.get("is_live") for selection in selections),
        minuto=next(
            (selection.get("live_time") for selection in selections if selection.get("live_time")),
            "",
        ) or "",
        periodo=next(
            (selection.get("period") for selection in selections if selection.get("period")),
            "",
        ) or "",
        marcador_local=score[0] if len(score) > 0 else None,
        marcador_visitante=score[1] if len(score) > 1 else None,
    )


def _serialize_snapshot(snapshot):
    return {
        "live": snapshot.es_live,
        "minuto": snapshot.minuto,
        "periodo": snapshot.periodo,
        "marcador": [snapshot.marcador_local, snapshot.marcador_visitante],
        "cuotas": {
            "local": float(snapshot.cuota_local) if snapshot.cuota_local is not None else None,
            "empate": float(snapshot.cuota_empate) if snapshot.cuota_empate is not None else None,
            "visitante": (
                float(snapshot.cuota_visitante)
                if snapshot.cuota_visitante is not None
                else None
            ),
        },
        "observado_en": snapshot.observado_en.isoformat(),
    }


def _data(partido):
    client = EcuabetClient()
    event = _event_info(partido, client)
    event_id = event["event_id"]
    detalle = client.obtener_mercados_evento(
        event_id,
        sport_id=event.get("sport_id") or 0,
        champ_id=event.get("champ_id") or 0,
    )

    mercado_1x2 = next(
        (m for m in detalle.get("markets", []) if int(m.get("market_type_id") or 0) == 1),
        None,
    )
    if not mercado_1x2 or not mercado_1x2.get("selections"):
        raise EcuabetAPIError(f"No se encontró mercado 1X2 para {event_id}")

    quotes = {
        "event_id": event_id,
        "market_id": mercado_1x2["market_id"],
        "selections": [
            {
                **selection,
                "is_live": False,
                "live_time": None,
                "period": None,
                "score": None,
                "last_update": None,
            }
            for selection in mercado_1x2["selections"]
        ],
    }
    snapshot = _save_snapshot(partido, quotes)

    mercados = []
    for market in detalle.get("markets", []):
        selections = []
        for selection in market.get("selections", []):
            selections.append({
                "odd_id": selection.get("odd_id"),
                "type_id": selection.get("type_id"),
                "name": selection.get("name") or "Selección",
                "price": selection.get("price"),
                "competitor_id": selection.get("competitor_id"),
            })

        if selections:
            mercados.append({
                "market_id": market.get("market_id"),
                "market_type_id": market.get("market_type_id"),
                "name": market.get("name") or "Mercado",
                "line": market.get("line"),
                "selections": selections,
            })

    previous = (
        Cuota1X2Snapshot.objects
        .filter(partido=partido)
        .exclude(pk=snapshot.pk)
        .first()
    )

    current_data = _serialize_snapshot(snapshot)
    previous_data = _serialize_snapshot(previous) if previous else None

    changes = {}
    if previous:
        for key in ("local", "empate", "visitante"):
            current_value = current_data["cuotas"][key]
            previous_value = previous_data["cuotas"][key]
            changes[key] = (
                round(current_value - previous_value, 4)
                if current_value is not None and previous_value is not None
                else None
            )
    else:
        changes = {"local": None, "empate": None, "visitante": None}

    return {
        "ok": True,
        "event_id": event_id,
        "snapshot_id": snapshot.pk,
        "snapshot_count": Cuota1X2Snapshot.objects.filter(partido=partido).count(),
        "current": {
            **current_data,
            "mercados": mercados,
        },
        "previous": previous_data,
        "changes": changes,
        "poll_seconds": int(os.getenv("ECUABET_POLL_SECONDS", "5")),
    }


def cuotas_partido(request, partido_id):
    partido = get_object_or_404(
        Partido.objects.select_related("liga", "equipo_local", "equipo_visitante"),
        pk=partido_id,
    )
    return render(
        request,
        "estadisticas/cuotas_partido.html",
        {
            "partido": partido,
            "poll_seconds": int(os.getenv("ECUABET_POLL_SECONDS", "5")),
        },
    )


def api_cuotas_partido(request, partido_id):
    partido = get_object_or_404(
        Partido.objects.select_related("liga", "equipo_local", "equipo_visitante"),
        pk=partido_id,
    )
    try:
        return JsonResponse(_data(partido))
    except (EcuabetAPIError, ValueError, TypeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
