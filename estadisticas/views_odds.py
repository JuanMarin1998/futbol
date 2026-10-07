import os

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .ecuabet_client import EcuabetAPIError, EcuabetClient
from .models import Cuota1X2Snapshot, Partido


def _event_id(partido, client):
    if partido.ecuabet_event_id:
        return partido.ecuabet_event_id
    found = client.buscar_evento(partido.equipo_local.nombre, partido.equipo_visitante.nombre)
    partido.ecuabet_event_id = found["event_id"]
    partido.save(update_fields=["ecuabet_event_id"])
    return found["event_id"]


def _save_snapshot(partido, quotes):
    selections = quotes["selections"]
    values = {"local": None, "empate": None, "visitante": None}
    odd_ids = {"local": None, "empate": None, "visitante": None}
    for s in selections:
        kind = {1: "local", 2: "empate", 3: "visitante"}.get(s.get("type_id"))
        if kind:
            values[kind] = s.get("price")
            odd_ids[kind] = s.get("odd_id")
        if str(s.get("name", "")).strip().lower() == "empate":
            values["empate"] = s.get("price")
            odd_ids["empate"] = s.get("odd_id")

    score = next((s.get("score") for s in selections if s.get("score") is not None), None) or []
    return Cuota1X2Snapshot.objects.create(
        partido=partido,
        ecuabet_event_id=quotes["event_id"],
        odd_id_local=odd_ids["local"],
        odd_id_empate=odd_ids["empate"],
        odd_id_visitante=odd_ids["visitante"],
        cuota_local=values["local"],
        cuota_empate=values["empate"],
        cuota_visitante=values["visitante"],
        es_live=any(s.get("is_live") for s in selections),
        minuto=next((s.get("live_time") for s in selections if s.get("live_time")), "") or "",
        periodo=next((s.get("period") for s in selections if s.get("period")), "") or "",
        marcador_local=score[0] if len(score) > 0 else None,
        marcador_visitante=score[1] if len(score) > 1 else None,
    )


def _data(partido):
    client = EcuabetClient()
    event_id = _event_id(partido, client)
    snapshot = _save_snapshot(partido, client.obtener_cuotas_1x2(event_id))
    return {
        "ok": True,
        "event_id": event_id,
        "live": snapshot.es_live,
        "minuto": snapshot.minuto,
        "periodo": snapshot.periodo,
        "marcador": [snapshot.marcador_local, snapshot.marcador_visitante],
        "cuotas": {
            "local": float(snapshot.cuota_local) if snapshot.cuota_local is not None else None,
            "empate": float(snapshot.cuota_empate) if snapshot.cuota_empate is not None else None,
            "visitante": float(snapshot.cuota_visitante) if snapshot.cuota_visitante is not None else None,
        },
        "observado_en": snapshot.observado_en.isoformat(),
        "poll_seconds": int(os.getenv("ECUABET_POLL_SECONDS", "5")),
    }


def cuotas_partido(request, partido_id):
    partido = get_object_or_404(
        Partido.objects.select_related("liga", "equipo_local", "equipo_visitante"), pk=partido_id
    )
    return render(request, "estadisticas/cuotas_partido.html", {
        "partido": partido,
        "poll_seconds": int(os.getenv("ECUABET_POLL_SECONDS", "5")),
    })


def api_cuotas_partido(request, partido_id):
    partido = get_object_or_404(
        Partido.objects.select_related("equipo_local", "equipo_visitante"), pk=partido_id
    )
    try:
        return JsonResponse(_data(partido))
    except (EcuabetAPIError, ValueError, TypeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
