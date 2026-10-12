from django.http import JsonResponse
from django.shortcuts import render
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.db import transaction
from django.db.models import Count, Sum
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Thread

from .api_football_live import APIFootballLiveClient
from .ecuabet_client import EcuabetClient
from .live_engine.collector import LiveMatchCollector
from .live_engine.match_mapper import MatchMappingError
from .live_engine.experiment import LiveExperimentManager
from .live_engine.opportunity_levels import enrich
from .models import LiveExperiment, LiveExperimentEntry, LiveExperimentDailyArchive, MatchBehaviorSnapshot, TeamBehaviorProfile, EcuabetPreMatchContext

logger = logging.getLogger(__name__)



def _contexto_guardado_json(context):
    """Serializa la ficha original sin recalcular ni sobrescribir sus cuotas."""
    return {
        "id": context.ecuabet_event_id,
        "name": context.match_name,
        "home": context.home_team or "Local no identificado",
        "away": context.away_team or "Visitante no identificado",
        "time": timezone.localtime(context.kickoff).strftime("%H:%M") if context.kickoff else "",
        "championship": context.championship,
        "home_odds": context.home_odds,
        "draw_odds": context.draw_odds,
        "away_odds": context.away_odds,
        "favorite": context.favorite,
        "status": context.status,
        "explanation": context.explanation,
        "source": context.source,
        "captured_at": timezone.localtime(context.captured_at).strftime("%H:%M:%S"),
        "persisted": True,
    }


def calendario_ecuabet(request):
    """Página de programación de Ecuabet limitada al día actual."""
    return render(
        request,
        "estadisticas/calendario_ecuabet.html",
        {"seccion": "calendario_ecuabet", "fecha_hoy": timezone.localdate()},
    )


def api_calendario_ecuabet(request):
    """Obtiene los eventos de fútbol de Ecuabet y devuelve solo los de hoy."""
    hoy = timezone.localdate()
    cache_key = f"ecuabet_calendar_today_v1_{hoy.isoformat()}"
    try:
        payload = cache.get(cache_key)
        if payload is None:
            payload = EcuabetClient()._request(
                "GET",
                "GetEvents",
                {"eventCount": 0, "sportId": 66, "champIds": 0},
            )
            cache.set(cache_key, payload, 60)

        raw_events = payload.get("events", []) if isinstance(payload, dict) else []
        champs = payload.get("champs", []) or payload.get("availableChamps", []) or []
        champs_by_id = {}
        for champ in champs:
            if isinstance(champ, dict):
                champ_id = champ.get("id") or champ.get("champId") or champ.get("LI") or champ.get("I")
                if champ_id is not None:
                    champs_by_id[str(champ_id)] = champ.get("name") or champ.get("champName") or champ.get("L") or champ.get("LE") or ""

        def fecha_evento(event):
            value = event.get("startDate") or event.get("start_date") or event.get("date")
            if value is None:
                return None, None
            parsed = None
            if isinstance(value, (int, float)):
                try:
                    # Ecuabet puede entregar marcas de tiempo en segundos o milisegundos.
                    stamp = value / 1000 if value > 10**11 else value
                    parsed = datetime.fromtimestamp(stamp, tz=timezone.get_current_timezone())
                except (OverflowError, OSError, ValueError):
                    parsed = None
            elif isinstance(value, str):
                parsed = parse_datetime(value)
                if parsed is None:
                    try:
                        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    except (TypeError, ValueError):
                        parsed = None
            if parsed is not None:
                if timezone.is_naive(parsed):
                    parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
                local_dt = timezone.localtime(parsed)
                return local_dt.date(), local_dt
            if isinstance(value, str) and len(value) >= 10:
                try:
                    from datetime import date as date_type
                    return date_type.fromisoformat(value[:10]), None
                except ValueError:
                    pass
            return None, None

        from datetime import datetime
        events_today = []
        without_date = 0
        for event in raw_events:
            if not isinstance(event, dict):
                continue
            event_date, event_dt = fecha_evento(event)
            if event_date is None:
                without_date += 1
                continue
            if event_date != hoy:
                continue
            champ_id = event.get("champId") or event.get("champ_id")
            champ_name = (
                event.get("champName")
                or event.get("champ")
                or champs_by_id.get(str(champ_id), "")
            )
            events_today.append({
                "id": event.get("id") or event.get("eventId"),
                "name": event.get("name") or event.get("eventName") or "Partido sin nombre",
                "start_date": event.get("startDate") or event.get("start_date") or event.get("date"),
                "time": timezone.localtime(event_dt).strftime("%H:%M") if event_dt else "",
                "championship": champ_name.get("name", "") if isinstance(champ_name, dict) else str(champ_name or ""),
                "status": event.get("status") or event.get("eventStatus") or "",
            })

        events_today.sort(key=lambda item: (item["time"] == "", item["time"], item["name"].lower()))
        context_ids = [int(item["id"]) for item in events_today if str(item.get("id", "")).isdigit()]
        saved_contexts = {
            str(item.ecuabet_event_id): item
            for item in EcuabetPreMatchContext.objects.filter(ecuabet_event_id__in=context_ids)
        }
        for item in events_today:
            saved = saved_contexts.get(str(item.get("id")))
            item["context"] = _contexto_guardado_json(saved) if saved else None
            item["context_available"] = saved is not None
        return JsonResponse({
            "ok": True,
            "date": hoy.isoformat(),
            "date_label": hoy.strftime("%d/%m/%Y"),
            "count": len(events_today),
            "events": events_today,
            "events_returned_by_ecuabet": len(raw_events),
            "events_without_recognized_date": without_date,
            "source": "Ecuabet GetEvents",
            "updated_at": timezone.localtime().strftime("%H:%M:%S"),
            "note": "" if events_today else "Ecuabet no devolvió eventos identificables para la fecha de hoy en esta consulta. Puede que GetEvents requiera consultar campeonatos por separado.",
        })
    except Exception as exc:
        logger.exception("Error cargando calendario diario de Ecuabet")
        return JsonResponse({
            "ok": False,
            "date": hoy.isoformat(),
            "date_label": hoy.strftime("%d/%m/%Y"),
            "count": 0,
            "events": [],
            "error": str(exc),
            "source": "Ecuabet GetEvents",
        }, status=502)



def contexto_ecuabet(request):
    """Página para generar y revisar el contexto previo de los partidos de hoy."""
    return render(
        request,
        "estadisticas/contexto_ecuabet.html",
        {"seccion": "contexto_ecuabet", "fecha_hoy": timezone.localdate()},
    )


def api_generar_contexto_ecuabet(request):
    """Genera contexto previo usando localía y cuotas 1X2 de Ecuabet."""
    hoy = timezone.localdate()
    cache_key = f"ecuabet_pre_match_context_v1_{hoy.isoformat()}"
    try:
        # Reutilizar fichas persistentes; solo consultar Ecuabet si no existe la ficha solicitada.
        if request.GET.get("force") != "1":
            saved = list(EcuabetPreMatchContext.objects.filter(match_date=hoy))
            requested_event_id = request.GET.get("event_id", "").strip()
            requested_exists = any(str(item.ecuabet_event_id) == requested_event_id for item in saved)
            if saved and (not requested_event_id or requested_exists):
                contexts_saved = [_contexto_guardado_json(item) for item in saved]
                return JsonResponse({
                    "ok": True, "date": hoy.isoformat(),
                    "date_label": hoy.strftime("%d/%m/%Y"),
                    "count": len(contexts_saved), "contexts": contexts_saved,
                    "generated_at": timezone.localtime().strftime("%H:%M:%S"),
                    "source": "Base de datos · fichas previas guardadas",
                    "note": "Contexto previo persistente. Las cuotas originales se conservan y no se sobrescriben al sincronizar el calendario.",
                })

        # Migrar al almacenamiento persistente el contexto que ya estaba en caché,
        # conservando las cuotas originales en lugar de recalcularlas al primer acceso.
        cached_result = cache.get(cache_key)
        if cached_result and cached_result.get("contexts"):
            from datetime import datetime, time as time_type
            migrated = []
            for item in cached_result.get("contexts", []):
                event_id = item.get("id")
                if not str(event_id or "").isdigit():
                    continue
                kickoff_value = None
                time_value = item.get("time")
                if time_value:
                    try:
                        kickoff_value = timezone.make_aware(
                            datetime.combine(hoy, time_type.fromisoformat(time_value)),
                            timezone.get_current_timezone(),
                        )
                    except (TypeError, ValueError):
                        kickoff_value = None
                captured_value = timezone.now()
                try:
                    if item.get("captured_at"):
                        captured_value = timezone.make_aware(
                            datetime.combine(hoy, time_type.fromisoformat(item["captured_at"])),
                            timezone.get_current_timezone(),
                        )
                except (TypeError, ValueError):
                    pass
                saved, created = EcuabetPreMatchContext.objects.get_or_create(
                    ecuabet_event_id=int(event_id),
                    defaults={
                        "match_name": item.get("name") or "Partido sin nombre",
                        "home_team": item.get("home") or "",
                        "away_team": item.get("away") or "",
                        "championship": item.get("championship") or "",
                        "match_date": hoy, "kickoff": kickoff_value,
                        "home_odds": item.get("home_odds"), "draw_odds": item.get("draw_odds"),
                        "away_odds": item.get("away_odds"), "favorite": item.get("favorite") or "",
                        "status": item.get("status") or "", "explanation": item.get("explanation") or "",
                        "source": item.get("source") or "Ecuabet · mercado 1X2",
                        "captured_at": captured_value, "raw_context": item,
                    },
                )
                migrated.append(_contexto_guardado_json(saved))
            if migrated:
                cached_result = dict(cached_result)
                cached_result["contexts"] = migrated
                cached_result["count"] = len(migrated)
                cached_result["source"] = "Contexto anterior recuperado y guardado"
                cached_result["note"] = "Se recuperó la ficha previa existente y se guardó sin recalcular ni sobrescribir las cuotas iniciales."
                return JsonResponse(cached_result)

        client = EcuabetClient()
        payload = client._request(
            "GET", "GetEvents",
            {"eventCount": 0, "sportId": 66, "champIds": 0},
        )
        raw_events = payload.get("events", []) if isinstance(payload, dict) else []
        champs = payload.get("champs", []) or payload.get("availableChamps", []) or []
        champs_by_id = {
            str(item.get("id") or item.get("champId") or item.get("LI") or item.get("I")):
                (item.get("name") or item.get("champName") or item.get("L") or item.get("LE") or "")
            for item in champs if isinstance(item, dict)
        }
        competitors = payload.get("competitors", []) or []
        competitors_by_id = {
            str(item.get("id")): item.get("name", "")
            for item in competitors if isinstance(item, dict) and item.get("id") is not None
        }

        def parse_event_datetime(event):
            value = event.get("startDate") or event.get("start_date") or event.get("date")
            if value is None:
                return None
            if isinstance(value, (int, float)):
                try:
                    stamp = value / 1000 if value > 10**11 else value
                    return timezone.localtime(datetime.fromtimestamp(stamp, tz=timezone.get_current_timezone()))
                except (OverflowError, OSError, ValueError):
                    return None
            if isinstance(value, str):
                parsed = parse_datetime(value)
                if parsed is None:
                    try:
                        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    except (TypeError, ValueError):
                        return None
                if timezone.is_naive(parsed):
                    parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
                return timezone.localtime(parsed)
            return None

        def numeric_price(value):
            try:
                price = float(value)
                return price if price > 1 else None
            except (TypeError, ValueError):
                return None

        from datetime import datetime
        contexts = []
        for event in raw_events:
            if not isinstance(event, dict):
                continue
            kickoff = parse_event_datetime(event)
            if kickoff is None or kickoff.date() != hoy:
                continue

            event_name = event.get("name") or event.get("eventName") or "Partido sin nombre"
            competitor_ids = event.get("competitorIds") or []
            home = competitors_by_id.get(str(competitor_ids[0]), "") if competitor_ids else ""
            away = competitors_by_id.get(str(competitor_ids[1]), "") if len(competitor_ids) > 1 else ""
            if not home or not away:
                for separator in (" - ", " vs ", " VS ", " v "):
                    if separator in event_name:
                        pieces = event_name.split(separator, 1)
                        home = home or pieces[0].strip()
                        away = away or pieces[1].strip()
                        break

            normalized = client.normalizar_mercados_evento(event, payload)
            market = next(
                (item for item in normalized.get("markets", [])
                 if str(item.get("market_type_id") or item.get("type_id") or "") == "1"),
                None,
            )
            home_price = away_price = draw_price = None
            if market:
                for selection in market.get("selections", []):
                    price = numeric_price(selection.get("price"))
                    if price is None:
                        continue
                    selection_name = str(selection.get("name") or "").strip().lower()
                    competitor_id = selection.get("competitor_id")
                    if competitor_id is not None and competitor_ids:
                        if str(competitor_id) == str(competitor_ids[0]):
                            home_price = price
                            continue
                        if len(competitor_ids) > 1 and str(competitor_id) == str(competitor_ids[1]):
                            away_price = price
                            continue
                    if selection_name in {"x", "draw", "empate", "tie"}:
                        draw_price = price
                    elif selection_name and home and selection_name == home.lower():
                        home_price = price
                    elif selection_name and away and selection_name == away.lower():
                        away_price = price

            favorite = ""
            status = "Cuotas 1X2 no identificadas"
            explanation = "No se pudo identificar con seguridad la cuota de victoria de ambos equipos; no se asigna favorito."
            if home_price is not None and away_price is not None:
                eligible = []
                if 1.05 <= home_price <= 2.00:
                    eligible.append((home_price, home, "local"))
                if 1.05 <= away_price <= 2.00:
                    eligible.append((away_price, away, "visitante"))
                if len(eligible) == 1:
                    _, favorite, side = eligible[0]
                    status = "Favorito según la regla"
                    explanation = f"{favorite} es el favorito según la regla de cuotas (1.05–2.00), jugando como {side}."
                elif len(eligible) == 2:
                    _, favorite, side = min(eligible, key=lambda item: item[0])
                    status = "Favorito según la regla · cuotas parejas"
                    explanation = f"Ambos equipos están en el rango definido; {favorite} tiene la cuota menor y queda como favorito relativo."
                else:
                    status = "Sin favorito según la regla"
                    explanation = "Ninguna cuota de victoria está entre 1.05 y 2.00; no se asigna favorito."
            champ_id = event.get("champId") or event.get("champ_id")
            champ = event.get("champName") or event.get("champ") or champs_by_id.get(str(champ_id), "")
            contexts.append({
                "id": event.get("id") or event.get("eventId"),
                "name": event_name,
                "home": home or "Local no identificado",
                "away": away or "Visitante no identificado",
                "time": kickoff.strftime("%H:%M"),
                "championship": champ.get("name", "") if isinstance(champ, dict) else str(champ or ""),
                "home_odds": home_price,
                "draw_odds": draw_price,
                "away_odds": away_price,
                "favorite": favorite,
                "status": status,
                "explanation": explanation,
                "source": "Ecuabet · mercado 1X2",
                "captured_at": timezone.localtime().strftime("%H:%M:%S"),
            })

        # Guardar la primera ficha por ID; get_or_create protege las cuotas originales.
        persisted_contexts = []
        events_by_id = {
            str(ev.get("id") or ev.get("eventId")): ev
            for ev in raw_events if isinstance(ev, dict)
        }
        for item in contexts:
            event_id = item.get("id")
            if not str(event_id or "").isdigit():
                persisted_contexts.append(item)
                continue
            source_event = events_by_id.get(str(event_id), {})
            kickoff_value = parse_event_datetime(source_event) if source_event else None
            saved, created = EcuabetPreMatchContext.objects.get_or_create(
                ecuabet_event_id=int(event_id),
                defaults={
                    "match_name": item["name"], "home_team": item["home"], "away_team": item["away"],
                    "championship": item["championship"], "match_date": hoy, "kickoff": kickoff_value,
                    "home_odds": item["home_odds"], "draw_odds": item["draw_odds"], "away_odds": item["away_odds"],
                    "favorite": item["favorite"], "status": item["status"], "explanation": item["explanation"],
                    "source": item["source"], "raw_context": item,
                },
            )
            persisted_contexts.append(_contexto_guardado_json(saved))
        contexts = persisted_contexts
        contexts.sort(key=lambda item: (item["time"], item["name"].lower()))
        result = {
            "ok": True,
            "date": hoy.isoformat(),
            "date_label": hoy.strftime("%d/%m/%Y"),
            "count": len(contexts),
            "contexts": contexts,
            "generated_at": timezone.localtime().strftime("%H:%M:%S"),
            "source": "Ecuabet GetEvents",
            "note": "Contexto previo basado únicamente en localía y cuotas 1X2. Es una clasificación según la regla definida, no una predicción segura del resultado.",
        }
        cache.set(cache_key, result, 60 * 60 * 12)
        return JsonResponse(result)
    except Exception as exc:
        logger.exception("Error generando contexto previo de Ecuabet")
        return JsonResponse({"ok": False, "error": str(exc), "contexts": []}, status=502)

def partidos_en_vivo(request):
    poll_seconds = getattr(settings, "LIVE_POLL_SECONDS", 60)
    return render(request, "estadisticas/live.html", {"live_poll_ms": poll_seconds * 1000})


def api_partidos_en_vivo(request):
    try:
        cache_key = "api_football_live_matches_v3"
        payload = cache.get(cache_key)

        if payload is None:
            payload = APIFootballLiveClient().obtener_en_vivo()
            cache.set(cache_key, payload, getattr(settings, "LIVE_CACHE_SECONDS", 50))

        matches = []
        for item in payload.get("response", []):
            fixture = item.get("fixture", {})
            league = item.get("league", {})
            teams = item.get("teams", {})
            goals = item.get("goals", {})
            status = fixture.get("status", {})

            matches.append({
                "id": fixture.get("id"),
                "league": league.get("name", ""),
                "country": league.get("country", ""),
                "home": teams.get("home", {}).get("name", ""),
                "away": teams.get("away", {}).get("name", ""),
                "home_logo": teams.get("home", {}).get("logo", ""),
                "away_logo": teams.get("away", {}).get("logo", ""),
                "home_goals": goals.get("home", 0),
                "away_goals": goals.get("away", 0),
                "elapsed": status.get("elapsed"),
                "extra": status.get("extra"),
                "status": status.get("short", ""),
                "status_long": status.get("long", ""),
            })

        return JsonResponse({
            "count": len(matches),
            "matches": matches,
            "source": "API-Football /fixtures?live=all",
        })
    except Exception as exc:
        return JsonResponse({"error": str(exc), "matches": []}, status=502)


def detalle_partido_en_vivo(request, fixture_id):
    poll_seconds = getattr(settings, "LIVE_POLL_SECONDS", 60)
    return render(
        request,
        "estadisticas/live_detalle.html",
        {"fixture_id": fixture_id, "live_poll_ms": poll_seconds * 1000},
    )


def api_detalle_partido_en_vivo(request, fixture_id):
    try:
        # Solo datos LIVE. No consultamos liga/temporada/coverage porque
        # el plan Free puede bloquear temporadas aunque el fixture esté LIVE.
        cache_key = f"api_football_live_detail_v5_{fixture_id}"
        payload = cache.get(cache_key)

        if payload is None:
            payload = APIFootballLiveClient().obtener_detalle_partido(fixture_id)
            cache.set(
                cache_key,
                payload,
                getattr(settings, "LIVE_CACHE_SECONDS", 50),
            )

        response = payload.get("response", [])
        if not response:
            return JsonResponse(
                {"error": "No se encontró el partido solicitado."},
                status=404,
            )

        item = response[0]
        fixture = item.get("fixture", {})
        league = item.get("league", {})
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        status = fixture.get("status", {})

        events = item.get("events") or []
        statistics = item.get("statistics") or []
        lineups = item.get("lineups") or []
        players = item.get("players") or []

        client = APIFootballLiveClient()
        fallback_used = []

        # /fixtures?id=... normalmente ya trae estos cuatro bloques.
        # Solo hacemos llamadas adicionales para los bloques ausentes.
        if not events:
            try:
                events_payload = client.obtener_eventos_partido(fixture_id)
                events = events_payload.get("response") or []
                if events:
                    fallback_used.append("events")
            except Exception:
                pass

        if not statistics:
            try:
                stats_payload = client.obtener_estadisticas_partido(fixture_id)
                statistics = stats_payload.get("response") or []
                if statistics:
                    fallback_used.append("statistics")
            except Exception:
                pass

        if not lineups:
            try:
                lineups_payload = client.obtener_alineaciones_partido(fixture_id)
                lineups = lineups_payload.get("response") or []
                if lineups:
                    fallback_used.append("lineups")
            except Exception:
                pass

        if not players:
            try:
                players_payload = client.obtener_jugadores_partido(fixture_id)
                players = players_payload.get("response") or []
                if players:
                    fallback_used.append("players")
            except Exception:
                pass

        stats_normalized = []
        for team_stats in statistics:
            team = team_stats.get("team") or {}
            values = {}
            for stat in team_stats.get("statistics") or []:
                stat_type = stat.get("type")
                if stat_type:
                    values[stat_type] = stat.get("value")

            stats_normalized.append({
                "team": team,
                "values": values,
            })

        cards = [
            event for event in events
            if (event.get("type") or "").lower() == "card"
        ]
        goals_events = [
            event for event in events
            if (event.get("type") or "").lower() == "goal"
        ]
        substitutions = [
            event for event in events
            if (event.get("type") or "").lower() in {"subst", "substitution"}
        ]

        return JsonResponse({
            "fixture": {
                "id": fixture.get("id"),
                "date": fixture.get("date"),
                "venue": fixture.get("venue", {}),
                "referee": fixture.get("referee"),
                "status": status,
            },
            "league": league,
            "home": teams.get("home", {}),
            "away": teams.get("away", {}),
            "score": goals,
            "events": events,
            "goals_events": goals_events,
            "cards": cards,
            "substitutions": substitutions,
            "statistics": statistics,
            "statistics_normalized": stats_normalized,
            "lineups": lineups,
            "players": players,
            "meta": {
                "events": len(events),
                "goals": len(goals_events),
                "cards": len(cards),
                "substitutions": len(substitutions),
                "statistics": len(statistics),
                "lineups": len(lineups),
                "players": len(players),
                "fallback_used": fallback_used,
                "source": "API-Football LIVE fixture + missing-block fallbacks",
                "main_payload": {
                    "results": payload.get("results"),
                    "errors": payload.get("errors") or {},
                    "raw_keys": sorted(item.keys()),
                    "raw_counts": {
                        "events": len(item.get("events") or []),
                        "statistics": len(item.get("statistics") or []),
                        "lineups": len(item.get("lineups") or []),
                        "players": len(item.get("players") or []),
                    },
                },
            },
        })
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=502)


def experimento_live(request):
    return render(request, "estadisticas/experimento_live.html", {"live_poll_ms": 5000})


def ecuabet_live(request):
    poll_seconds = 5
    return render(
        request,
        "estadisticas/ecuabet_live.html",
        {"live_poll_ms": poll_seconds * 1000},
    )


def api_ecuabet_live(request):
    """Devuelve todos los eventos LIVE de Ecuabet con todos sus mercados y cuotas."""
    try:
        cache_key = "ecuabet_live_all_v1"
        payload = cache.get(cache_key)

        if payload is None:
            client = EcuabetClient()
            payload = client._request("GET", "GetLivenow", {
                "eventCount": 0,
                "sportId": 66,
            })
            cache.set(cache_key, payload, 3)

        events = payload.get("events", []) or []
        markets = payload.get("markets", []) or []
        odds = payload.get("odds", []) or []
        competitors = payload.get("competitors", []) or []
        sports = payload.get("sports", []) or []
        categories = payload.get("categories", []) or []
        champs = payload.get("champs", []) or []

        markets_by_id = {
            int(item["id"]): item
            for item in markets
            if isinstance(item, dict) and item.get("id") is not None
        }
        odds_by_id = {
            int(item["id"]): item
            for item in odds
            if isinstance(item, dict) and item.get("id") is not None
        }
        competitors_by_id = {
            int(item["id"]): item
            for item in competitors
            if isinstance(item, dict) and item.get("id") is not None
        }
        sports_by_id = {
            int(item["id"]): item
            for item in sports
            if isinstance(item, dict) and item.get("id") is not None
        }
        categories_by_id = {
            int(item["id"]): item
            for item in categories
            if isinstance(item, dict) and item.get("id") is not None
        }
        champs_by_id = {
            int(item["id"]): item
            for item in champs
            if isinstance(item, dict) and item.get("id") is not None
        }

        result = []
        for event in events:
            if not isinstance(event, dict):
                continue

            market_list = []
            for market_id in event.get("marketIds", []) or []:
                market = markets_by_id.get(int(market_id))
                if not market:
                    continue

                selections = []
                for odd_id in market.get("oddIds", []) or []:
                    odd = odds_by_id.get(int(odd_id))
                    if not odd:
                        continue
                    selections.append({
                        "id": int(odd["id"]),
                        "type_id": odd.get("typeId"),
                        "name": odd.get("name", ""),
                        "price": odd.get("price"),
                        "odd_status": odd.get("oddStatus"),
                        "competitor_id": odd.get("competitorId"),
                        "is_mb": odd.get("isMB", False),
                        "is_dbb": odd.get("isDBB", False),
                    })

                if selections:
                    market_list.append({
                        "id": int(market["id"]),
                        "type_id": market.get("typeId"),
                        "sport_market_id": market.get("sportMarketId"),
                        "name": market.get("name", ""),
                        "line": market.get("sv") or market.get("sn"),
                        "selections": selections,
                    })

            competitor_ids = event.get("competitorIds", []) or []
            event_sport_id = event.get("sportId")
            event_cat_id = event.get("catId")
            event_champ_id = event.get("champId")

            result.append({
                "id": event.get("id"),
                "name": event.get("name", ""),
                "live_time": event.get("liveTime"),
                "live_status": event.get("ls"),
                "score": event.get("score", [None, None]),
                "timer": event.get("timer", {}),
                "status": event.get("status"),
                "start_date": event.get("startDate"),
                "has_stream": event.get("hasStream", False),
                "competitors": [
                    competitors_by_id.get(int(cid), {"id": cid, "name": str(cid)})
                    for cid in competitor_ids
                ],
                "sport": sports_by_id.get(int(event_sport_id), {"id": event_sport_id, "name": ""})
                if event_sport_id is not None else {},
                "category": categories_by_id.get(int(event_cat_id), {"id": event_cat_id, "name": ""})
                if event_cat_id is not None else {},
                "champ": champs_by_id.get(int(event_champ_id), {"id": event_champ_id, "name": ""})
                if event_champ_id is not None else {},
                "markets": market_list,
            })

        return JsonResponse({
            "ok": True,
            "count": len(result),
            "events": result,
            "source": "Ecuabet GetLivenow",
            "updated_at": payload.get("updatedAt") or payload.get("lastUpdate"),
        })
    except Exception as exc:
        return JsonResponse(
            {"ok": False, "error": str(exc), "events": []},
            status=502,
        )



def api_live_match_sources(request, ecuabet_event_id, flashscore_event_id):
    """
    Prueba de integración: un mismo LiveMatch alimentado por Ecuabet + Flashscore.

    El ID de Flashscore se recibe explícitamente hasta que terminemos el
    MatchMapper automático.
    """
    try:
        match = LiveMatchCollector().construir(
            ecuabet_event_id=ecuabet_event_id,
            flashscore_event_id=flashscore_event_id,
        )
        return JsonResponse({
            "ok": True,
            "match": match.to_dict(),
            "source": {
                "odds": "Ecuabet GetLivenow",
                "performance": "Flashscore pq_graphql",
            },
        })
    except Exception as exc:
        return JsonResponse(
            {"ok": False, "error": str(exc)},
            status=502,
        )


def _experimento_live_payload():
    """Obtiene una sola vez el feed LIVE completo y deja los eventos listos."""
    payload = EcuabetClient()._request(
        "GET", "GetLivenow", {"eventCount": 0, "sportId": 66}
    )
    events = [
        LiveMatchCollector.enriquecer_evento_desde_payload(event, payload)
        for event in (payload.get("events", []) or [])
        if isinstance(event, dict)
    ]
    return payload, events


def _procesar_experimentos_live(live_events, experiments):
    """Actualiza partidos LIVE reutilizando el feed Ecuabet y en paralelo."""
    event_by_id = {
        int(event["id"]): event
        for event in live_events
        if isinstance(event, dict) and event.get("id") is not None
    }
    tasks = [
        experiment
        for experiment in experiments
        if int(experiment.ecuabet_event_id) in event_by_id
        and experiment.flashscore_event_id
    ]
    if not tasks:
        return []

    def worker(experiment):
        from django.db import close_old_connections

        try:
            close_old_connections()
            event = event_by_id[int(experiment.ecuabet_event_id)]
            collector = LiveMatchCollector()
            match = collector.construir_desde_evento(
                event,
                experiment.flashscore_event_id,
                1.0,
            )
            LiveExperimentManager.process(match)
            return None
        except Exception as exc:
            logger.exception(
                "Error procesando experimento %s (%s vs %s).",
                experiment.id,
                experiment.home_team,
                experiment.away_team,
            )
            return {
                "experiment_id": experiment.id,
                "match": f"{experiment.home_team} vs {experiment.away_team}",
                "error": str(exc),
            }
        finally:
            close_old_connections()

    # Limitar conexiones simultáneas: cada worker puede abrir su propia conexión Django.
    # El ciclo continuo repetido no debe acercarse al límite de PostgreSQL.
    max_workers = min(3, len(tasks))
    if max_workers <= 1:
        return [error for error in (worker(tasks[0]),) if error]

    errors = []
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="live-exp") as executor:
        futures = [executor.submit(worker, experiment) for experiment in tasks]
        for future in futures:
            error = future.result()
            if error:
                errors.append(error)
    return errors


def _limitar_snapshots_estado(experiments, max_snapshots=80):
    """Conserva solo los snapshots recientes que la auditoría de la interfaz puede mostrar."""
    snapshots = [
        (snapshot.get("created_at") or "", snapshot.get("id"), experiment.get("id"))
        for experiment in experiments
        for snapshot in (experiment.get("snapshots") or [])
    ]
    keep = {
        (snapshot_id, experiment_id)
        for _, snapshot_id, experiment_id in sorted(snapshots, reverse=True)[:max_snapshots]
    }
    for experiment in experiments:
        experiment_id = experiment.get("id")
        experiment["snapshots"] = [
            snapshot for snapshot in (experiment.get("snapshots") or [])
            if (snapshot.get("id"), experiment_id) in keep
        ]
    return experiments


def _mapear_eventos_live_en_segundo_plano(events):
    """Vincula eventos nuevos sin bloquear la actualización de los partidos activos."""
    from django.db import close_old_connections

    errors = []
    def map_event(event):
        event_id = int(event["id"])
        try:
            close_old_connections()
            result = _crear_experimento_desde_evento(event)
            if result.get("created"):
                cache.delete(f"live_experiment_map_retry:{event_id}")
            elif result.get("error"):
                errors.append({
                    "event_id": event_id,
                    "match": result.get("match"),
                    "error": result.get("error"),
                })
            return result
        except Exception as exc:
            logger.exception("Error en mapeo asíncrono del evento Ecuabet %s.", event_id)
            errors.append({"event_id": event_id, "error": str(exc)})
            return None
        finally:
            cache.delete(f"live_experiment_map_in_progress:{event_id}")
            close_old_connections()

    try:
        with ThreadPoolExecutor(
            # El mapeo consulta Flashscore y la BD; mantener poca concurrencia evita
            # sumar demasiadas conexiones al procesamiento de partidos ya vinculados.
            max_workers=min(2, len(events)),
            thread_name_prefix="live-map-cycle",
        ) as executor:
            list(executor.map(map_event, events))
    finally:
        cache.set("live_experiment_async_mapping_errors", errors[:20], 120)
        close_old_connections()


def _resumen_motores_diario(target_date=None):
    """Resume todas las apuestas del día, aunque la interfaz limite los partidos detallados."""
    target_date = target_date or timezone.localdate()
    initial_by_motor = {"ESP": 50.0}
    rows = (
        LiveExperimentEntry.objects
        .filter(experiment__started_at__date=target_date)
        .values("motor", "status")
        .annotate(count=Count("id"), staked=Sum("stake"), pnl_sum=Sum("pnl"))
    )
    summary = {}
    for row in rows:
        motor = row["motor"]
        item = summary.setdefault(motor, {
            "decisions": 0, "wins": 0, "losses": 0, "open": 0, "cancelled": 0,
            "total_staked": 0.0, "total_pnl": 0.0, "open_staked": 0.0,
        })
        status = row["status"]
        count = int(row["count"] or 0)
        item["decisions"] += count
        if status == "WON":
            item["wins"] += count
        elif status == "LOST":
            item["losses"] += count
        elif status == "OPEN":
            item["open"] += count
            item["open_staked"] += float(row["staked"] or 0)
        elif status == "CANCELLED":
            item["cancelled"] += count
        item["total_staked"] += float(row["staked"] or 0)
        item["total_pnl"] += float(row["pnl_sum"] or 0)
    for motor, item in summary.items():
        item["starting"] = initial_by_motor.get(motor, 100.0)
        item["total_capital"] = max(0.0, item["starting"] + item["total_pnl"])
        item["available_lives"] = max(0.0, item["total_capital"] - item["open_staked"])
        settled = item["wins"] + item["losses"]
        item["hit_rate"] = item["wins"] / settled * 100 if settled else 0.0
        item["roi"] = item["total_pnl"] / item["total_staked"] * 100 if item["total_staked"] else 0.0
        item["alive"] = item["available_lives"] >= 1.0
    return summary


def _experimento_estado_global():
    """Procesa el laboratorio global sin bloquear el ciclo con consultas repetidas."""
    if cache.get("live_experiment_starting"):
        today = timezone.localdate()
        experiments = list(
            LiveExperiment.objects.filter(
                status__in=["RUNNING", "FINISHED", "STOPPED"],
                started_at__date=today,
            ).order_by("-updated_at")[:100]
        )
        serialized = _limitar_snapshots_estado([LiveExperimentManager.serialize(x, snapshot_limit=3, opportunity_limit=12) for x in experiments])
        return {
            "ok": True, "running": True, "starting": True,
            "experiments": serialized,
            "entries": [
                {**entry, "experiment_id": exp.get("id"), "match_status": exp.get("status")}
                for exp in serialized for entry in exp.get("entries", [])
            ],
            "live_count": 0, "busy": True, "processing_errors": [],
            "start_message": "Preparando partidos LIVE en segundo plano.",
            "daily_motors": _resumen_motores_diario(today),
        }

    lock_key = "live_experiment_global_state_lock"
    if not cache.add(lock_key, True, 60):
        today = timezone.localdate()
        experiments = list(
            LiveExperiment.objects
            .filter(
                status__in=["RUNNING", "FINISHED", "STOPPED"],
                started_at__date=today,
            )
            .order_by("-updated_at")[:100]
        )
        serialized = [LiveExperimentManager.serialize(x, snapshot_limit=3, opportunity_limit=12) for x in experiments]
        return {
            "ok": True,
            "running": any(x.get("status") == "RUNNING" for x in serialized),
            "experiments": serialized,
            "entries": [
                {**entry, "experiment_id": exp.get("id"), "match_status": exp.get("status")}
                for exp in serialized for entry in exp.get("entries", [])
            ],
            "live_count": 0,
            "busy": True,
            "processing_errors": [],
            "daily_motors": _resumen_motores_diario(today),
        }

    try:
        today = timezone.localdate()
        _, live_events = _experimento_live_payload()
        live_ids = {
            int(e.get("id")) for e in live_events if e.get("id") is not None
        }
        collector = LiveMatchCollector()

        running = list(
            LiveExperiment.objects.filter(status="RUNNING").order_by("-started_at")
        )

        # Primero analizar los experimentos ya vinculados: un partido nuevo que tarde
        # en mapearse nunca debe bloquear las apuestas de los partidos que ya corren.
        processing_errors = _procesar_experimentos_live(live_events, running)

        # Programar el mapeo de eventos nuevos en un hilo independiente.
        # Así, los partidos ya vinculados pueden actualizar marcador, minuto y apuestas
        # sin esperar a que terminen las consultas de Flashscore de todos los eventos.
        mapping_errors = cache.get("live_experiment_async_mapping_errors", [])
        if cache.get("live_experiment_worker_enabled"):
            running_ids = {int(x.ecuabet_event_id) for x in running}
            candidates = []
            for event in live_events:
                if event.get("id") is None:
                    continue
                event_id = int(event["id"])
                if (
                    event_id in running_ids
                    or cache.get(f"live_experiment_map_retry:{event_id}")
                ):
                    continue
                if cache.add(f"live_experiment_map_in_progress:{event_id}", True, 120):
                    candidates.append(event)
            if candidates:
                Thread(
                    target=_mapear_eventos_live_en_segundo_plano,
                    args=(candidates,),
                    name="live-map-background",
                    daemon=True,
                ).start()

        finalized_matches = []
        pending_final_count = 0
        for experiment in running:
            if int(experiment.ecuabet_event_id) in live_ids:
                continue
            if not experiment.flashscore_event_id:
                logger.warning(
                    "Experimento %s (%s vs %s) salió de Ecuabet sin flashscore_event_id.",
                    experiment.id,
                    experiment.home_team,
                    experiment.away_team,
                )
                pending_final_count += 1
                continue
            try:
                match = collector.construir_desde_flashscore(
                    experiment.flashscore_event_id,
                    ecuabet_event_id=experiment.ecuabet_event_id,
                    home_team=experiment.home_team,
                    away_team=experiment.away_team,
                )
                if match.is_finished:
                    settled_before = sum(
                        1
                        for entry in LiveExperimentManager.serialize(experiment).get("entries", [])
                        if entry.get("status") == "OPEN"
                    )
                    LiveExperimentManager.process(match)
                    finalized_matches.append({
                        "match": f"{experiment.home_team} vs {experiment.away_team}",
                        "score": f"{match.home_score}-{match.away_score}",
                        "settled_entries": settled_before,
                        "experiment_date": timezone.localtime(experiment.started_at).date().isoformat(),
                    })
                else:
                    pending_final_count += 1
            except Exception:
                pending_final_count += 1
                logger.exception(
                    "Error confirmando final del experimento %s (%s vs %s).",
                    experiment.id,
                    experiment.home_team,
                    experiment.away_team,
                )

        all_experiments = list(
            LiveExperiment.objects
            .filter(status__in=["RUNNING", "FINISHED", "STOPPED"])
            .order_by("-updated_at")[:200]
        )

        for experiment in all_experiments:
            if experiment.status == "FINISHED":
                try:
                    LiveExperimentManager.reconcile_finished(experiment.id)
                except Exception:
                    logger.exception("Error reconciliando experimento %s.", experiment.id)

        experiments = [
            experiment for experiment in all_experiments
            if timezone.localtime(experiment.started_at).date() == today
        ]
        serialized = [LiveExperimentManager.serialize(x, snapshot_limit=3, opportunity_limit=12) for x in experiments]

        entries = []
        for exp in serialized:
            for entry in exp.get("entries", []):
                entry["experiment_id"] = exp.get("id")
                entry["match_status"] = exp.get("status")
                entries.append(entry)
        entries.sort(key=lambda x: x.get("placed_at") or "", reverse=True)

        return {
            "ok": True,
            "running": any(x.get("status") == "RUNNING" for x in serialized),
            "experiments": serialized,
            "entries": entries,
            "live_count": len(live_events),
            "finalized_count": len([
                item for item in finalized_matches
                if item.get("experiment_date") == today.isoformat()
            ]),
            "finalized_matches": [
                item for item in finalized_matches
                if item.get("experiment_date") == today.isoformat()
            ],
            "pending_final_count": pending_final_count,
            "processing_errors": processing_errors[:20],
            "mapping_errors": mapping_errors[:20],
            "mapping_error_count": len(mapping_errors),
            "startup_result": cache.get("live_experiment_start_result"),
            "busy": False,
            "daily_motors": _resumen_motores_diario(today),
        }
    finally:
        cache.delete(lock_key)

def api_live_experiment_save_daily(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido."}, status=405)
    try:
        state = _experimento_estado_global()
        if state.get("busy"):
            return JsonResponse({
                "ok": False,
                "error": "El laboratorio todavía está actualizando partidos. Intenta guardar en unos segundos.",
            }, status=409)

        archive = LiveExperimentManager.save_daily_archive()
        running_count = sum(
            1 for experiment in state.get("experiments", [])
            if experiment.get("status") == "RUNNING"
        )
        return JsonResponse({
            "ok": True,
            "date": archive.experiment_date.isoformat(),
            "saved_at": archive.saved_at.isoformat(),
            "experiment_count": archive.experiment_count,
            "decision_count": archive.decision_count,
            "running_count": running_count,
            "motors": archive.motors_summary,
        })
    except Exception as exc:
        logger.exception("Error guardando archivo diario del experimento.")
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)


def api_live_experiment_reset_today(request):
    """Elimina exclusivamente los datos del laboratorio creados hoy."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido."}, status=405)

    lock_key = "live_experiment_global_state_lock"
    if not cache.add(lock_key, True, 60):
        return JsonResponse({
            "ok": False,
            "error": "El laboratorio está procesando una actualización. Detén la simulación y vuelve a intentar en unos segundos.",
        }, status=409)

    try:
        today = timezone.localdate()
        with transaction.atomic():
            experiments_qs = LiveExperiment.objects.filter(started_at__date=today)
            experiment_count = experiments_qs.count()
            entry_count = sum(
                experiment.entries.count()
                for experiment in experiments_qs
            )
            snapshot_count = sum(
                experiment.snapshots.count()
                for experiment in experiments_qs
            )

            # Las entradas y snapshots están en CASCADE; al eliminar los
            # experimentos también desaparecen sus apuestas y predicciones.
            experiments_qs.delete()

            # Si hoy ya se había guardado un archivo diario, también se
            # elimina para que no conserve datos del experimento incorrecto.
            archive_deleted, _ = LiveExperimentDailyArchive.objects.filter(
                experiment_date=today
            ).delete()

        return JsonResponse({
            "ok": True,
            "date": today.isoformat(),
            "experiment_count": experiment_count,
            "entry_count": entry_count,
            "snapshot_count": snapshot_count,
            "archive_deleted": archive_deleted,
            "message": "El laboratorio de hoy fue reiniciado. Los días anteriores no fueron afectados.",
        })
    except Exception as exc:
        logger.exception("Error reiniciando el laboratorio del día.")
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
    finally:
        cache.delete(lock_key)


def api_live_experiment_history(request):
    if request.method != "GET":
        return JsonResponse({"ok": False, "error": "Método no permitido."}, status=405)
    try:
        archives = LiveExperimentDailyArchive.objects.all()
        return JsonResponse({
            "ok": True,
            "days": [
                {
                    "date": archive.experiment_date.isoformat(),
                    "saved_at": archive.saved_at.isoformat(),
                    "experiment_count": archive.experiment_count,
                    "decision_count": archive.decision_count,
                    "motors": archive.motors_summary,
                }
                for archive in archives
            ],
        })
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)


def _crear_experimento_desde_evento(event):
    """Mapea y crea un experimento para un partido LIVE nuevo."""
    from django.db import close_old_connections

    event_id = int(event["id"])
    event_name = str(event.get("name") or f"Ecuabet {event_id}")
    try:
        close_old_connections()
        collector = LiveMatchCollector()
        mapping = collector.mapper.mapear(event, collector.flashscore)
        if not mapping.get("matched"):
            raise MatchMappingError(
                f"No se pudo vincular Ecuabet {event_id} con Flashscore "
                f"(confianza={float(mapping.get('confidence', 0.0)):.2f}, "
                f"motivo={mapping.get('reason', 'sin coincidencia')})."
            )
        match = collector.construir_desde_evento(
            event,
            mapping["flashscore_event_id"],
            mapping.get("confidence", 1.0),
        )
        if match.is_finished:
            return {
                "event_id": event_id,
                "match": event_name,
                "error": "El partido ya figura como finalizado.",
                "created": False,
                "experiment": None,
            }
        experiment = LiveExperimentManager.start(match)
        return {
            "event_id": event_id,
            "match": event_name,
            "error": None,
            "created": True,
            "experiment": experiment,
        }
    except Exception as exc:
        cache.set(f"live_experiment_map_retry:{event_id}", True, 45)
        logger.exception(
            "No se pudo iniciar experimento para Ecuabet %s (%s).",
            event_id,
            event_name,
        )
        return {
            "event_id": event_id,
            "match": event_name,
            "error": str(exc),
            "created": False,
            "experiment": None,
        }
    finally:
        close_old_connections()


def _bucle_laboratorio_live():
    """Mantiene el análisis LIVE activo sin depender del sondeo del navegador."""
    from django.db import close_old_connections

    intervalo = max(3, int(getattr(settings, "LIVE_EXPERIMENT_CYCLE_SECONDS", 5)))
    try:
        while cache.get("live_experiment_worker_enabled"):
            close_old_connections()
            try:
                state = _experimento_estado_global()
                cache.set("live_experiment_state_payload", state, max(30, intervalo * 6))
                logger.info("Ciclo LIVE: %s partidos, %s experimentos, %s entradas.", state.get("live_count", 0), len(state.get("experiments", [])), len(state.get("entries", [])))
                # Mantener vivo el indicador sin reactivarlo si el usuario pulsa Parar.
                cache.touch("live_experiment_worker_enabled", timeout=3600)
            except Exception:
                logger.exception("Falló un ciclo continuo del laboratorio LIVE.")
            finally:
                close_old_connections()
            time.sleep(intervalo)
    finally:
        cache.delete("live_experiment_worker_enabled")
        close_old_connections()

def _iniciar_laboratorio_live_en_segundo_plano():
    """Libera el arranque rápidamente; el ciclo continuo descubre y vincula partidos."""
    from django.db import close_old_connections

    try:
        close_old_connections()
        # No mapear todos los partidos antes de arrancar el ciclo continuo.
        # _experimento_estado_global procesa primero los partidos ya vinculados
        # y programa el mapeo de eventos nuevos en segundo plano.
        cache.set("live_experiment_start_result", {
            "live_count": 0,
            "created": 0,
            "skipped": 0,
            "start_errors": [],
            "start_error_count": 0,
            "processing_errors": [],
            "processing_error_count": 0,
            "message": "Arranque rápido; los partidos nuevos se vinculan en segundo plano.",
        }, 300)
        logger.info("Arranque rápido del laboratorio LIVE; el mapeo se delega al ciclo continuo.")
    except Exception:
        logger.exception("Error preparando el laboratorio LIVE.")
        cache.set("live_experiment_start_result", {
            "error": "Falló la preparación del laboratorio. Revisa la consola/log de Django.",
        }, 300)
    finally:
        cache.delete("live_experiment_starting")
        close_old_connections()
        if cache.get("live_experiment_worker_enabled"):
            Thread(target=_bucle_laboratorio_live, name="live-laboratory-cycle", daemon=True).start()

def api_live_experiment_start_all(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido."}, status=405)

    if cache.get("live_experiment_worker_enabled"):
        return JsonResponse({"ok": True, "running": True, "starting": False, "busy": True, "start_message": "El análisis continuo ya está activo."})

    if not cache.add("live_experiment_starting", True, 300):
        return JsonResponse({
            "ok": True, "running": True, "starting": True,
            "experiments": [], "entries": [], "live_count": 0,
            "created": 0, "skipped": 0, "start_errors": [],
            "processing_errors": [],
            "start_message": "El laboratorio ya se está preparando en segundo plano.",
            "busy": True,
        })

    try:
        cache.delete("live_experiment_start_result")
        cache.delete("live_experiment_state_payload")
        cache.set("live_experiment_worker_enabled", True, 3600)
        worker = Thread(
            target=_iniciar_laboratorio_live_en_segundo_plano,
            name="live-laboratory-start",
            daemon=True,
        )
        worker.start()
        return JsonResponse({
            "ok": True, "running": True, "starting": True,
            "experiments": [], "entries": [], "live_count": 0,
            "created": 0, "skipped": 0, "start_errors": [],
            "processing_errors": [],
            "start_message": "Arranque aceptado; preparando eventos LIVE y motores en segundo plano.",
            "busy": True,
        })
    except Exception as exc:
        cache.delete("live_experiment_starting")
        logger.exception("No se pudo despachar el arranque del laboratorio LIVE.")
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)

def api_live_experiment_stop_all(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido."}, status=405)
    try:
        cache.delete("live_experiment_worker_enabled")
        running = list(LiveExperiment.objects.filter(status="RUNNING"))
        stopped = 0
        for experiment in running:
            try:
                LiveExperimentManager.stop(experiment.id)
                stopped += 1
            except Exception:
                continue
        state = _experimento_estado_global()
        return JsonResponse({**state, "stopped": stopped})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)


def api_live_experiment_state(request):
    if request.method != "GET":
        return JsonResponse({"ok": False, "error": "Método no permitido."}, status=405)
    try:
        if cache.get("live_experiment_worker_enabled") and request.GET.get("fresh") != "1":
            snapshot = cache.get("live_experiment_state_payload")
            if snapshot is not None:
                return JsonResponse(snapshot)
            return JsonResponse({"ok": True, "running": True, "starting": True, "busy": True, "experiments": [], "entries": [], "live_count": 0, "processing_errors": [], "start_message": "El motor está preparando el primer ciclo de análisis LIVE."})
        state = _experimento_estado_global()
        if cache.get("live_experiment_worker_enabled"):
            cache.set("live_experiment_state_payload", state, 120)
        return JsonResponse(state)
    except Exception as exc:
        logger.exception("Error obteniendo estado del laboratorio LIVE.")
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)


def api_live_experiment_start(request, ecuabet_event_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido."}, status=405)
    try:
        collector = LiveMatchCollector()
        match = collector.construir_automatico(ecuabet_event_id)
        experiment = LiveExperimentManager.start(match)
        return JsonResponse({
            "ok": True,
            "experiment": LiveExperimentManager.serialize(experiment),
        })
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)


def api_live_experiment_stop(request, ecuabet_event_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido."}, status=405)
    try:
        experiment = (
            LiveExperiment.objects
            .filter(ecuabet_event_id=ecuabet_event_id, status="RUNNING")
            .order_by("-started_at")
            .first()
        )
        if not experiment:
            return JsonResponse({
                "ok": True,
                "experiment": None,
                "message": "No existe un experimento RUNNING para este partido.",
            })
        return JsonResponse({
            "ok": True,
            "experiment": LiveExperimentManager.stop(experiment.id),
        })
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)

def ecuabet_live_detalle(request, ecuabet_event_id):
    poll_seconds = 5
    return render(
        request,
        "estadisticas/ecuabet_live_detalle.html",
        {
            "ecuabet_event_id": ecuabet_event_id,
            "live_poll_ms": poll_seconds * 1000,
        },
    )


def api_ecuabet_live_detalle(request, ecuabet_event_id):
    try:
        # Compartimos brevemente el feed LIVE entre pestañas/detalles para
        # evitar que cada refresco vuelva a llamar al proveedor externo.
        live_feed_cache_key = "ecuabet_live_feed_detail_v2"
        payload = cache.get(live_feed_cache_key)
        if payload is None:
            payload = EcuabetClient()._request(
                "GET",
                "GetLivenow",
                {"eventCount": 0, "sportId": 66},
            )
            cache.set(live_feed_cache_key, payload, 5)
        event = next(
            (
                item for item in payload.get("events", []) or []
                if int(item.get("id", -1)) == int(ecuabet_event_id)
            ),
            None,
        )
        if not event:
            # Cuando Ecuabet retira el partido de GetLivenow al terminar,
            # todavía podemos consultar Flashscore con el ID guardado por el
            # experimento y liquidar las entradas con el marcador final.
            finished_experiment = (
                LiveExperiment.objects
                .filter(ecuabet_event_id=ecuabet_event_id)
                .order_by("-started_at")
                .first()
            )
            if finished_experiment and finished_experiment.status == "FINISHED":
                return JsonResponse({
                    "ok": True,
                    "event": {
                        "id": ecuabet_event_id,
                        "name": f"{finished_experiment.home_team} vs. {finished_experiment.away_team}",
                        "live_time": "Final",
                        "live_status": "Finalizado",
                        "score": [
                            finished_experiment.final_home_score,
                            finished_experiment.final_away_score,
                        ],
                        "status": "FINISHED",
                    },
                    "flashscore": {
                        "matched": True,
                        "flashscore_event_id": finished_experiment.flashscore_event_id,
                        "confidence": 1.0,
                        "reason": "Partido finalizado y experimento ya liquidado.",
                    },
                    "match": None,
                    "experiment": LiveExperimentManager.serialize(finished_experiment),
                })

            if finished_experiment and finished_experiment.flashscore_event_id:
                try:
                    collector = LiveMatchCollector()
                    match = collector.construir_desde_flashscore(
                        finished_experiment.flashscore_event_id,
                        ecuabet_event_id=ecuabet_event_id,
                        home_team=finished_experiment.home_team,
                        away_team=finished_experiment.away_team,
                    )
                    if match.is_finished:
                        experiment_state = LiveExperimentManager.process(match)
                        return JsonResponse({
                            "ok": True,
                            "event": {
                                "id": ecuabet_event_id,
                                "name": f"{finished_experiment.home_team} vs. {finished_experiment.away_team}",
                                "live_time": match.minute,
                                "live_status": match.match_status or "Finalizado",
                                "score": [match.home_score, match.away_score],
                                "status": "FINISHED",
                            },
                            "flashscore": {
                                "matched": True,
                                "flashscore_event_id": finished_experiment.flashscore_event_id,
                                "confidence": 1.0,
                                "reason": "Ecuabet retiró el evento de LIVE; estado final recuperado desde Flashscore.",
                            },
                            "match": match.to_dict(),
                            "experiment": experiment_state,
                        })
                except Exception:
                    pass

            return JsonResponse(
                {"ok": False, "error": "El partido ya no está LIVE y todavía no se pudo confirmar el estado final."},
                status=404,
            )

        # GetLivenow suele incluir una oferta reducida. Complementamos con
        # GetEventDetails, cacheado brevemente para no consultar en cada render.
        detail_cache_key = f"ecuabet_event_markets_detail:{ecuabet_event_id}"
        detail_payload = cache.get(detail_cache_key)
        if detail_payload is None:
            try:
                detail_payload = EcuabetClient().obtener_detalle_evento(ecuabet_event_id)
                if isinstance(detail_payload, dict):
                    cache.set(detail_cache_key, detail_payload, 12)
                else:
                    detail_payload = {}
            except Exception:
                logger.exception(
                    "No se pudo ampliar inventario de mercados Ecuabet para evento %s.",
                    ecuabet_event_id,
                )
                detail_payload = {}

        event = EcuabetClient.normalizar_mercados_evento(
            event, payload, detail_payload=detail_payload
        )
        competitors = {
            int(x["id"]): x for x in payload.get("competitors", []) or []
            if isinstance(x, dict) and x.get("id") is not None
        }
        event["competitors"] = [
            competitors.get(int(cid), {"id": cid, "name": str(cid)})
            for cid in event.get("competitorIds", []) or []
        ]

        # El mapeo se cachea brevemente porque el ID Flashscore no cambia
        # mientras el partido sigue siendo el mismo.
        mapper_cache_key = f"live_match_mapping_{ecuabet_event_id}"
        mapping = cache.get(mapper_cache_key)
        collector = LiveMatchCollector()

        if mapping is None:
            mapping = collector.mapper.mapear(event, collector.flashscore)
            cache.set(mapper_cache_key, mapping, 30)

        match_dict = None
        experiment_state = None
        if mapping.get("matched") and mapping.get("flashscore_event_id"):
            try:
                match = collector._construir_desde_evento(
                    event,
                    mapping["flashscore_event_id"],
                    mapping.get("confidence", 0.0),
                )
                match_dict = match.to_dict()

                # Enriquecemos la respuesta de detalle con los niveles del laboratorio.
                for opportunity_key in (
                    "opportunities",
                    "opportunities_v11",
                    "opportunities_v12",
                    "opportunities_v2",
                    "opportunities_v21",
                    "opportunities_v22",
                    "opportunities_v3",
                    "opportunities_v2_ultra",
                    "opportunities_v11_ultra",
                    "opportunities_vpro",
                    "opportunities_vpro11",
                ):
                    match_dict[opportunity_key] = [
                        enrich(dict(opportunity))
                        for opportunity in (match_dict.get(opportunity_key) or [])
                    ]
                match_dict["flashscore_url"] = (
                    f"https://www.flashscore.com/match/{match.flashscore_event_id}/"
                    if match.flashscore_event_id else None
                )

                experiment = (
                    LiveExperiment.objects
                    .filter(ecuabet_event_id=ecuabet_event_id)
                    .order_by("-started_at")
                    .first()
                )
                if experiment:
                    if experiment.status == "RUNNING":
                        experiment_state = LiveExperimentManager.process(match)
                    else:
                        experiment_state = LiveExperimentManager.serialize(experiment)
            except Exception as exc:
                mapping = {
                    **mapping,
                    "matched": False,
                    "reason": f"flashscore_stats_error: {exc}",
                }

        return JsonResponse({
            "ok": True,
            "event": event,
            "flashscore": mapping,
            "match": match_dict,
            "experiment": experiment_state,
        })
    except MatchMappingError as exc:
        return JsonResponse({
            "ok": True,
            "event": event if "event" in locals() else None,
            "flashscore": {
                "matched": False,
                "flashscore_event_id": None,
                "confidence": 0.0,
                "reason": str(exc),
            },
            "match": None,
        })
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)



def laboratorio_patrones(request):
    """Panel de observación; consulta datos guardados y no inicia ni modifica apuestas."""
    profiles = list(TeamBehaviorProfile.objects.all()[:100])
    recent = list(MatchBehaviorSnapshot.objects.all()[:40])
    matches_count = MatchBehaviorSnapshot.objects.values("ecuabet_event_id").distinct().count()
    context = {
        "profiles": profiles,
        "recent_snapshots": recent,
        "snapshots_count": MatchBehaviorSnapshot.objects.count(),
        "matches_count": matches_count,
        "teams_count": TeamBehaviorProfile.objects.count(),
        "last_snapshot": MatchBehaviorSnapshot.objects.order_by("-observed_at").first(),
        "seccion": "patrones",
    }
    return render(request, "estadisticas/laboratorio_patrones.html", context)


def api_patron_oportunidades_partidos(request):
    """Devuelve únicamente partidos LIVE con contexto previo guardado y favorito por cuota."""
    try:
        hoy = timezone.localdate()
        contexts = list(EcuabetPreMatchContext.objects.filter(match_date=hoy).order_by("kickoff", "match_name"))
        def cuota_valida(value):
            try:
                value = float(value)
                return 1.05 <= value <= 2.00
            except (TypeError, ValueError):
                return False

        eligible_contexts = []
        for ctx in contexts:
            if not ctx.favorite:
                continue
            if not (cuota_valida(ctx.home_odds) or cuota_valida(ctx.away_odds)):
                continue
            eligible_contexts.append(ctx)

        if not eligible_contexts:
            return JsonResponse({
                "ok": True, "count": 0, "events": [],
                "contexts_found": len(contexts), "live_found": 0,
                "note": "No hay fichas previas de hoy con favorito dentro de la regla de cuota 1.05–2.00.",
                "updated_at": timezone.localtime().strftime("%H:%M:%S"),
            })

        payload = EcuabetClient()._request("GET", "GetLivenow", {"eventCount": 0, "sportId": 66})
        live_events = payload.get("events", []) if isinstance(payload, dict) else []
        live_by_id = {
            str(event.get("id") or event.get("eventId")): event
            for event in live_events if isinstance(event, dict)
        }
        result = []
        for ctx in eligible_contexts:
            event = live_by_id.get(str(ctx.ecuabet_event_id))
            if not event:
                continue
            result.append({
                "id": ctx.ecuabet_event_id,
                "name": ctx.match_name,
                "home": ctx.home_team,
                "away": ctx.away_team,
                "favorite": ctx.favorite,
                "home_odds": ctx.home_odds,
                "draw_odds": ctx.draw_odds,
                "away_odds": ctx.away_odds,
                "captured_at": timezone.localtime(ctx.captured_at).strftime("%H:%M:%S"),
                "live_time": event.get("liveTime") or event.get("timer") or event.get("status") or "LIVE",
                "score": event.get("score"),
                "championship": ctx.championship,
            })
        return JsonResponse({
            "ok": True, "count": len(result), "events": result,
            "contexts_found": len(contexts), "favorite_contexts": len(eligible_contexts),
            "live_found": len(live_by_id),
            "source": "Ecuabet GetLivenow + contexto previo persistente",
            "updated_at": timezone.localtime().strftime("%H:%M:%S"),
            "note": "Solo se incluyen partidos actualmente LIVE, con contexto guardado y favorito por cuota entre 1.05 y 2.00.",
        })
    except Exception as exc:
        logger.exception("Error filtrando partidos del Patrón de Oportunidades")
        return JsonResponse({"ok": False, "error": str(exc), "events": []}, status=502)




def api_historial_patron_oportunidades(request):
    """Devuelve resultados persistidos del Patrón, con filtros opcionales por partido."""
    try:
        event_id = request.GET.get("event_id", "").strip()
        qs = MatchBehaviorSnapshot.objects.all().order_by("-observed_at")
        if event_id.isdigit():
            qs = qs.filter(ecuabet_event_id=int(event_id))
        records = []
        # Iterar en orden reciente y solo devolver snapshots que contienen resultado del Patrón.
        for snap in qs[:1000]:
            stored = snap.performance if isinstance(snap.performance, dict) else {}
            patron = stored.get("patron_oportunidades")
            if not isinstance(patron, dict):
                continue
            records.append({
                "id": snap.id,
                "event_id": snap.ecuabet_event_id,
                "partido": patron.get("partido") or {
                    "local": snap.home_team, "visitante": snap.away_team,
                    "liga": snap.league, "minuto": snap.minute,
                    "marcador": [snap.home_score, snap.away_score],
                },
                "etapas": patron.get("etapas") or {},
                "guardado_en": patron.get("guardado_en") or timezone.localtime(snap.observed_at).isoformat(),
                "observed_at": timezone.localtime(snap.observed_at).isoformat(),
            })
            if len(records) >= 200:
                break
        return JsonResponse({"ok": True, "count": len(records), "results": records})
    except Exception as exc:
        logger.exception("Error consultando historial del Patrón de Oportunidades")
        return JsonResponse({"ok": False, "error": str(exc), "results": []}, status=500)

def patron_oportunidades(request):
    """Pantalla del patrón conectado al flujo LIVE y motores existentes."""
    return render(
        request,
        "estadisticas/patron_oportunidades.html",
        {"live_poll_ms": 30000, "seccion": "patron_oportunidades"},
    )


def api_simular_patron_oportunidades(request, ecuabet_event_id):
    """Ejecuta una pasada del patrón con el snapshot LIVE y salidas reales de los motores.
    No crea experimentos ni apuestas; solo presenta y evalúa sus resultados.
    """
    from .live_engine.opportunity_engine import LiveOpportunityEngine
    from .live_engine.opportunity_engine_v2 import LiveOpportunityEngineV2
    from .live_engine.opportunity_engine_v11 import LiveOpportunityEngineV11
    from .live_engine.opportunity_engine_v12 import LiveOpportunityEngineV12
    from .live_engine.opportunity_engine_v21 import LiveOpportunityEngineV21
    from .live_engine.opportunity_engine_v22 import LiveOpportunityEngineV22
    from .live_engine.opportunity_engine_v3 import LiveOpportunityEngineV3
    from .live_engine.opportunity_engine_v2_ultra import LiveOpportunityEngineV2Ultra
    from .live_engine.opportunity_engine_v11_ultra import LiveOpportunityEngineV11Ultra
    from .live_engine.opportunity_engine_vpro import LiveOpportunityEngineVPro
    from .live_engine.opportunity_engine_vpro11 import LiveOpportunityEngineVPro11

    try:
        saved_context = EcuabetPreMatchContext.objects.filter(
            ecuabet_event_id=ecuabet_event_id, match_date=timezone.localdate()
        ).first()
        if not saved_context or not saved_context.favorite:
            return JsonResponse({"ok": False, "error": "El partido no tiene un contexto previo guardado con favorito identificado."}, status=409)
        valid_favorite_odds = []
        for value in (saved_context.home_odds, saved_context.away_odds):
            try:
                odd_value = float(value)
                if 1.05 <= odd_value <= 2.00:
                    valid_favorite_odds.append(odd_value)
            except (TypeError, ValueError):
                pass
        if not valid_favorite_odds:
            return JsonResponse({"ok": False, "error": "La cuota del favorito no cumple el rango de 1.05 a 2.00."}, status=409)

        previous = (
            MatchBehaviorSnapshot.objects
            .filter(ecuabet_event_id=ecuabet_event_id)
            .order_by("-observed_at")
            .first()
        )
        match = LiveMatchCollector().construir_automatico(ecuabet_event_id)

        context_data = match.pre_match_context if isinstance(match.pre_match_context, dict) else {}
        source_names = ("lineups", "history", "fixtures")
        source_status = {
            name: (context_data.get(name) or {}).get("status", "unavailable")
            for name in source_names
        }
        available_sources = [name for name, status in source_status.items() if status == "available"]
        context_has_data = bool(available_sources)
        context_summaries = {
            "lineups": "Alineaciones disponibles" if source_status["lineups"] == "available" else "Alineaciones no disponibles",
            "history": "Enfrentamientos directos disponibles" if source_status["history"] == "available" else "Historial directo no disponible",
            "fixtures": "Resultados/calendario reciente disponible" if source_status["fixtures"] == "available" else "Resultados/calendario reciente no disponibles",
        }
        context_stage = {
            "status": "CONTEXTO_PREVIO_GUARDADO",
            "expectativa": saved_context.explanation or "Contexto previo persistido disponible; no se interpreta como certeza de resultado.",
            "fuente": saved_context.source or "Ecuabet · contexto guardado",
            "partido": saved_context.match_name,
            "favorito": saved_context.favorite,
            "cuotas_originales": {
                "local": saved_context.home_odds,
                "empate": saved_context.draw_odds,
                "visitante": saved_context.away_odds,
            },
            "fecha_contexto": saved_context.match_date.isoformat(),
            "capturado_en": timezone.localtime(saved_context.captured_at).isoformat(),
            "fuentes_complementarias": context_summaries,
            "estados_fuentes_complementarias": source_status,
            "datos_complementarios": context_data,
        }

        current_minute = match.minute
        previous_minute = previous.minute_number if previous else None
        try:
            minute_num = int(str(current_minute or "").split("+")[0].replace("'", "").strip())
        except (ValueError, TypeError):
            import re
            found = re.search(r"\d+", str(current_minute or ""))
            minute_num = int(found.group()) if found else None

        prev_score = [previous.home_score, previous.away_score] if previous else None
        now_score = [match.home_score, match.away_score]
        score_delta = None
        if prev_score and None not in prev_score and None not in now_score:
            score_delta = (now_score[0] - prev_score[0]) + (now_score[1] - prev_score[1])

        performance = match.performance or {}
        previous_performance = dict(previous.performance) if previous and isinstance(previous.performance, dict) else {}
        # El bloque de auditoría del Patrón no es una estadística LIVE; no debe aparecer como cambio falso.
        previous_performance.pop("patron_oportunidades", None)
        def _flatten_stats(value, prefix=""):
            flattened = {}
            if isinstance(value, dict):
                for key, child in value.items():
                    flattened.update(_flatten_stats(child, f"{prefix}.{key}" if prefix else str(key)))
            elif isinstance(value, (int, float, str, bool)) or value is None:
                flattened[prefix] = value
            return flattened
        old_stats = _flatten_stats(previous_performance)
        new_stats = _flatten_stats(performance)
        changed_stats = []
        for stat_key in sorted(set(old_stats) | set(new_stats)):
            old_value, new_value = old_stats.get(stat_key), new_stats.get(stat_key)
            if old_value != new_value and (old_value is not None or new_value is not None):
                changed_stats.append({"estadistica": stat_key, "anterior": old_value, "actual": new_value})
        score_changed = bool(previous and prev_score is not None and now_score is not None and prev_score != now_score)
        goal_scored = bool(
            previous and prev_score is not None and now_score is not None
            and None not in prev_score and None not in now_score
            and (now_score[0] > prev_score[0] or now_score[1] > prev_score[1])
        )
        stats_changed = bool(previous and changed_stats)
        monitoring = {
            "status": "SIN_BASELINE_PREVIO" if previous is None else (
                "GOL_NUEVO_DETECTADO" if goal_scored else "ESPERANDO_GOL"
            ),
            "minuto_anterior": previous.minute if previous else None,
            "marcador_anterior": prev_score,
            "minuto_actual": current_minute,
            "marcador_actual": now_score,
            "estadisticas_cambiadas": len(changed_stats),
            "cambios_estadisticos": changed_stats[:30],
            "gol_nuevo": goal_scored,
            "detonante": goal_scored,
            "motivo": (
                "Primera lectura: establece la línea base de marcador y estadísticas LIVE; todavía no activa Acción."
                if previous is None else
                "Se confirmó un aumento en el marcador: el gol nuevo activa Acción."
                if goal_scored else
                "No se detectó un gol nuevo. Los cambios estadísticos por sí solos no activan Acción ni las etapas siguientes."
            ),
        }

        stage_action = {
            "status": "PENDIENTE_DE_DETONANTE",
            "diagnostico": "No se detectó cambio en las estadísticas LIVE; Acción queda pendiente.",
            "datos_evaluados": [],
        }
        stage_probability = {}
        stage_calculation = {}
        stage_reaction = {"status": "SEGUIR_MONITOREANDO", "decision": "SEGUIR_MONITOREANDO", "motivo": "Esperando cambios en los datos LIVE para avanzar a Acción."}

        # Acción evalúa las nuevas estadísticas cuando Monitoreo detecta cambios.
        # Probabilidad se calcula desde estadísticas; Cálculo incorpora cuotas.
        home_sot = None
        away_sot = None
        def stat(side, *keys):
            data = performance.get(side) or {}
            for key in keys:
                val = data.get(key)
                if isinstance(val, dict):
                    val = val.get("value", val.get("raw_value"))
                if val is not None:
                    try: return float(str(val).replace("%", "").replace(",", "."))
                    except (TypeError, ValueError): pass
            return None
        home_sot = stat("home", "shots_on_goal", "shots_on_target", "tiros a puerta")
        away_sot = stat("away", "shots_on_goal", "shots_on_target", "tiros a puerta")
        home = int(match.home_score or 0)
        away = int(match.away_score or 0)
        if home > away:
            score_read = f"{match.home_team} va ganando {home}-{away}"
        elif away > home:
            score_read = f"{match.away_team} va ganando {away}-{home}"
        else:
            score_read = f"el partido está empatado {home}-{away}"
        if home_sot is None or away_sot is None:
            stats_read = "Faltan tiros a puerta de uno o ambos equipos; la lectura estadística es parcial."
        elif home_sot >= away_sot + 2:
            stats_read = f"{match.home_team} tiene ventaja en tiros a puerta ({home_sot:g} contra {away_sot:g})."
        elif away_sot >= home_sot + 2:
            stats_read = f"{match.away_team} tiene ventaja en tiros a puerta ({away_sot:g} contra {home_sot:g})."
        else:
            stats_read = f"Los tiros a puerta no muestran una ventaja clara ({home_sot:g} contra {away_sot:g})."
        if monitoring["detonante"]:
            stage_action = {
                "status": "EVALUADA",
                "diagnostico": f"Tras detectar un gol nuevo, {score_read}; {stats_read}",
                "datos_evaluados": [context_stage["status"], f"minuto {current_minute}", f"marcador {home}-{away}", stats_read],
                "estadisticas_live": performance,
                "cambios_detectados": changed_stats[:30],
            }
        else:
            stage_action = {
                "status": "PENDIENTE_DE_DETONANTE",
                "diagnostico": f"No se activa Acción porque no se detectó un gol nuevo. Estado observado: {score_read}; {stats_read}",
                "datos_evaluados": [context_stage["status"], f"minuto {current_minute}", f"marcador {home}-{away}", stats_read],
                "estadisticas_live": performance,
                "cambios_detectados": changed_stats[:30],
            }

        engine_specs = [
            ("V1", LiveOpportunityEngine, "opportunities"),
            ("V1.1", LiveOpportunityEngineV11, "opportunities_v11"),
            ("V1.2", LiveOpportunityEngineV12, "opportunities_v12"),
            ("V2", LiveOpportunityEngineV2, "opportunities_v2"),
            ("V2.1", LiveOpportunityEngineV21, "opportunities_v21"),
            ("V2.2", LiveOpportunityEngineV22, "opportunities_v22"),
            ("V3", LiveOpportunityEngineV3, "opportunities_v3"),
            ("V2.Ultra", LiveOpportunityEngineV2Ultra, "opportunities_v2_ultra"),
            ("V1.1 Ultra", LiveOpportunityEngineV11Ultra, "opportunities_v11_ultra"),
            ("V.Pro", LiveOpportunityEngineVPro, "opportunities_vpro"),
            ("V.Pro 1.1", LiveOpportunityEngineVPro11, "opportunities_vpro11"),
        ]
        # Probabilidad se calcula en CADA pasada LIVE, no solo cuando cambia el marcador.
        # El gol nuevo activa la etapa Acción; no debe bloquear el análisis de mercados existentes.
        probabilities = {}
        elapsed = None
        if match is not None:
            elapsed = LiveOpportunityEngine._elapsed_minutes(current_minute, match.period)
            lambda_home, lambda_away = LiveOpportunityEngine._remaining_lambda(performance, elapsed)
            probabilities = LiveOpportunityEngine._probabilities(home, away, lambda_home, lambda_away)
            probability_keys = {
                "Victoria local": "home", "Empate": "draw", "Victoria visitante": "away",
                "Más de 0.5 goles": "over_0_5", "Menos de 0.5 goles": "under_0_5",
                "Más de 1.5 goles": "over_1_5", "Menos de 1.5 goles": "under_1_5",
                "Más de 2.5 goles": "over_2_5", "Menos de 2.5 goles": "under_2_5",
                "Más de 3.5 goles": "over_3_5", "Menos de 3.5 goles": "under_3_5",
                "Ambos marcan: sí": "btts_yes", "Ambos marcan: no": "btts_no",
            }
            total_current = home + away
            ranked_probabilities = []
            for label, key in probability_keys.items():
                if key not in probabilities:
                    continue
                market_state = "ABIERTO"
                if key.startswith("over_"):
                    target = {"over_0_5": 1, "over_1_5": 2, "over_2_5": 3, "over_3_5": 4}[key]
                    if total_current >= target:
                        market_state = "YA_CUMPLIDO"
                elif key.startswith("under_"):
                    target = {"under_0_5": 1, "under_1_5": 2, "under_2_5": 3, "under_3_5": 4}.get(key)
                    if target is not None and total_current >= target:
                        market_state = "YA_NO_CUMPLIBLE"
                ranked_probabilities.append({
                    "mercado": label,
                    "clave": key,
                    "probabilidad": round(float(probabilities[key]) * 100, 2),
                    "estado_live": market_state,
                })
            ranked_probabilities.sort(key=lambda item: item["probabilidad"], reverse=True)
            open_probabilities = [item for item in ranked_probabilities if item["estado_live"] == "ABIERTO"]
            best_open = max(open_probabilities, key=lambda item: item["probabilidad"]) if open_probabilities else None
            stage_probability = {
                "status": "PROBABILIDAD_ESTADISTICA_ACTUALIZADA",
                "mercados_probables": ranked_probabilities,
                "mas_probable": best_open,
                "estadisticas_utilizadas": performance,
                "minutos_restantes_estimados": round(max(0.0, 90.0 - elapsed), 1),
                "criterio": "Las probabilidades de resultado final incorporan el marcador actual. Los mercados ya cumplidos o imposibles se identifican y no se presentan como oportunidades futuras.",
                "motivo": "Referencia estadística LIVE calculada tras el detonante; todavía no incorpora cuotas.",
            }
        else:
            stage_probability = {
                "status": "ESPERANDO_DETONANTE",
                "mercados_probables": [],
                "mas_probable": None,
                "estadisticas_utilizadas": {},
                "motivo": "La primera lectura fija la línea base. Acción y las etapas siguientes esperan un gol nuevo confirmado.",
            }

        # Cálculo conserva las señales originales de cada motor y las contrasta
        # con la probabilidad estadística del mismo mercado, sin alterar sus fórmulas.
        # Se ejecuta en cada ciclo LIVE, incluso si no hubo gol nuevo desde el snapshot anterior.
        engine_results = []
        all_opportunities = []

        def _normalizar_texto(value):
            import unicodedata
            return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower().strip()

        def _probability_for_opportunity(op):
            market = str(op.get("mercado") or "")
            selection = str(op.get("seleccion") or "")
            line = op.get("line")
            key = LiveOpportunityEngine._market_key(market, selection, line)
            market_text = _normalizar_texto(market + " " + selection)
            selected = _normalizar_texto(selection)
            home_name = _normalizar_texto(match.home_team)
            away_name = _normalizar_texto(match.away_team)
            if key is None:
                if any(token in market_text for token in ("ambos marcan", "both teams", "btts")):
                    key = "btts_yes" if any(token in selected for token in ("si", "yes", "ambos")) else "btts_no"
                elif any(token in market_text for token in ("doble oportunidad", "double chance")):
                    if "1x" in selected: key = "dc_1x"
                    elif "x2" in selected: key = "dc_x2"
                    elif "12" in selected: key = "dc_12"
                elif any(token in market_text for token in ("1x2", "resultado", "ganador", "match result")):
                    if selected in ("x", "draw", "empate"): key = "draw"
                    elif selected in ("1", "home", "local") or (home_name and home_name in selected): key = "home"
                    elif selected in ("2", "away", "visitante") or (away_name and away_name in selected): key = "away"
                elif any(token in market_text for token in ("total", "over", "under", "mas de", "menos de")):
                    import re
                    raw_line = str(line or "")
                    found = re.search(r"(0[.,]5|1[.,]5|2[.,]5|3[.,]5)", raw_line + " " + market_text)
                    if found:
                        threshold = found.group(1).replace(",", ".")
                        is_over = any(token in selected for token in ("over", "mas", "+"))
                        is_under = any(token in selected for token in ("under", "menos", "-"))
                        if is_over: key = {"0.5": "over_0_5", "1.5": "over_1_5", "2.5": "over_2_5", "3.5": "over_3_5"}.get(threshold)
                        elif is_under: key = {"0.5": "under_0_5", "1.5": "under_1_5", "2.5": "under_2_5", "3.5": "under_3_5"}.get(threshold)
            if key in ("dc_1x", "dc_12", "dc_x2"):
                pair = {"dc_1x": ("home", "draw"), "dc_12": ("home", "away"), "dc_x2": ("draw", "away")}[key]
                value = sum(float(probabilities.get(part, 0.0)) for part in pair) if probabilities else None
            else:
                value = probabilities.get(key) if probabilities and key else None
            return key, value

        if match is not None:
            for label, engine, attr in engine_specs:
                opportunities = getattr(match, attr, None)
                if opportunities is None:
                    opportunities = engine.evaluate(match)
                clean = []
                for op in (opportunities or [])[:10]:
                    item = {
                        "mercado": op.get("market", ""),
                        "seleccion": op.get("selection", ""),
                        "line": op.get("line"),
                        "cuota": op.get("price"),
                        "probabilidad_modelo": op.get("model_probability"),
                        "probabilidad_implicita": op.get("implied_probability"),
                        "edge_pct": op.get("edge_pct"),
                        "confianza": op.get("confidence"),
                        "senal": op.get("signal", ""),
                    }
                    key, stat_probability = _probability_for_opportunity(item)
                    item["mercado_probabilidad_ref"] = key
                    item["estado_mercado_live"] = "ABIERTO"
                    if key and key.startswith("over_"):
                        threshold = {"over_0_5": 1, "over_1_5": 2, "over_2_5": 3, "over_3_5": 4}.get(key)
                        if threshold is not None and home + away >= threshold:
                            item["estado_mercado_live"] = "YA_CUMPLIDO"
                    elif key and key.startswith("under_"):
                        target = {"under_0_5": 1, "under_1_5": 2, "under_2_5": 3, "under_3_5": 4}.get(key)
                        if target is not None and home + away >= target:
                            item["estado_mercado_live"] = "YA_NO_CUMPLIBLE"
                    if stat_probability is not None:
                        item["probabilidad_estadistica_pct"] = round(float(stat_probability) * 100, 2)
                        try:
                            raw_model = float(item["probabilidad_modelo"])
                            model_pct = raw_model * 100 if 0 <= raw_model <= 1 else raw_model
                            item["probabilidad_motor_pct"] = round(model_pct, 2)
                            difference = model_pct - item["probabilidad_estadistica_pct"]
                            item["diferencia_motor_vs_estadistica_pp"] = round(difference, 2)
                            item["consenso_estadistico"] = (
                                "COINCIDE" if abs(difference) <= 10 else
                                "DISCREPANCIA_MODERADA" if abs(difference) <= 20 else
                                "DISCREPANCIA_ALTA"
                            )
                        except (TypeError, ValueError):
                            item["consenso_estadistico"] = "SIN_PROBABILIDAD_DEL_MOTOR"
                        try:
                            price = float(item["cuota"])
                            if price > 1 and item["estado_mercado_live"] == "ABIERTO":
                                item["edge_estadistico_pct"] = round((float(stat_probability) - 1.0 / price) * 100, 2)
                            else:
                                item["edge_estadistico_pct"] = None
                        except (TypeError, ValueError):
                            item["edge_estadistico_pct"] = None
                    else:
                        item["probabilidad_estadistica_pct"] = None
                        item["probabilidad_motor_pct"] = None
                        item["diferencia_motor_vs_estadistica_pp"] = None
                        item["edge_estadistico_pct"] = None
                        item["consenso_estadistico"] = "SIN_REFERENCIA_COMPARABLE"
                    clean.append(item)
                    all_opportunities.append({"motor": label, **item})
                engine_results.append({"motor": label, "senales": len(opportunities or []), "oportunidades": clean})

        stage_calculation = {
            "status": "CALCULO_COMPLETADO",
            "motores": engine_results,
            "oportunidades": all_opportunities[:150],
            "motores_con_senales": sum(1 for item in engine_results if item["senales"]),
            "coinciden_con_probabilidad": sum(1 for item in all_opportunities if item.get("consenso_estadistico") == "COINCIDE"),
            "discrepancias_altas": sum(1 for item in all_opportunities if item.get("consenso_estadistico") == "DISCREPANCIA_ALTA"),
            "motivo": "Cada señal mantiene la salida original del motor y añade contraste estadístico, probabilidad implícita, edge independiente y estado LIVE del mercado.",
        }
        # Registro explícito de todas las señales entregadas a Reacción.
        # Se conserva en la respuesta LIVE y en el historial persistido.
        reaction_inputs = []
        for signal in all_opportunities:
            reaction_inputs.append({
                "motor": signal.get("motor"),
                "mercado": signal.get("mercado"),
                "seleccion": signal.get("seleccion"),
                "cuota": signal.get("cuota"),
                "probabilidad_motor_pct": signal.get("probabilidad_motor_pct"),
                "probabilidad_estadistica_pct": signal.get("probabilidad_estadistica_pct"),
                "probabilidad_implicita": signal.get("probabilidad_implicita"),
                "edge_motor_pct": signal.get("edge_pct"),
                "edge_estadistico_pct": signal.get("edge_estadistico_pct"),
                "consenso_estadistico": signal.get("consenso_estadistico"),
                "diferencia_motor_vs_estadistica_pp": signal.get("diferencia_motor_vs_estadistica_pp"),
                "estado_mercado_live": signal.get("estado_mercado_live"),
                "senal_motor": signal.get("senal"),
            })
        positive = [
            item for item in all_opportunities
            if item.get("estado_mercado_live") == "ABIERTO"
            and isinstance(item.get("edge_estadistico_pct"), (int, float))
            and item["edge_estadistico_pct"] > 0
            and item.get("consenso_estadistico") != "DISCREPANCIA_ALTA"
        ]
        if positive:
            best = max(positive, key=lambda item: (item.get("edge_estadistico_pct", 0), item.get("probabilidad_estadistica_pct", 0)))
            stage_reaction = {
                "senales_recibidas": reaction_inputs,
                "total_senales_recibidas": len(reaction_inputs),
                "status": "SENALES_CON_RESPALDO_ESTADISTICO",
                "decision": "REVISAR_SENAL_CON_RESPALDO",
                "motivo": f"{len(positive)} señales tienen edge estadístico positivo y no presentan discrepancia alta con la referencia. La mejor por edge estadístico: {best['motor']} · {best['mercado']} · {best['seleccion']} (probabilidad estadística {best.get('probabilidad_estadistica_pct', '—')}%, edge estadístico {best.get('edge_estadistico_pct', '—')}%). No se ejecuta una apuesta.",
                "senal_destacada": best,
            }
        else:
            stage_reaction = {
                "senales_recibidas": reaction_inputs,
                "total_senales_recibidas": len(reaction_inputs),
                "status": "SIN_CONSENSO_ESTADISTICO_SUFICIENTE",
                "decision": "SEGUIR_MONITOREANDO",
                "motivo": "No hay señales abiertas con edge estadístico positivo y contraste suficiente. Las señales de edge del motor, por sí solas, no bastan para recomendar una acción.",
            }

        # Guardar cada observación LIVE para que la siguiente pasada compare marcador/minuto.
        import hashlib
        import json
        fingerprint_data = {
            "id": int(match.ecuabet_event_id),
            "minute": str(current_minute or ""),
            "score": now_score,
            "status": str(getattr(match, "status", "") or ""),
        }
        # Persistir también el resultado completo del Patrón para poder auditarlo después.
        saved_performance = dict(performance) if isinstance(performance, dict) else {}
        saved_performance["patron_oportunidades"] = {
            "partido": {
                "id": int(match.ecuabet_event_id),
                "local": str(match.home_team or ""),
                "visitante": str(match.away_team or ""),
                "liga": str(match.league or ""),
                "minuto": str(current_minute or ""),
                "marcador": now_score,
                "calidad_datos": str(match.data_quality or ""),
                "confianza_mapeo": match.mapping_confidence,
            },
            "etapas": {
                "contexto": context_stage,
                "monitoreo": monitoring,
                "accion": stage_action,
                "probabilidad": stage_probability,
                "calculo": stage_calculation,
                "reaccion": stage_reaction,
            },
            "guardado_en": timezone.localtime().isoformat(),
        }
        MatchBehaviorSnapshot.objects.create(
            ecuabet_event_id=int(match.ecuabet_event_id),
            flashscore_event_id=str(getattr(match, "flashscore_event_id", "") or ""),
            home_team=str(match.home_team or ""),
            away_team=str(match.away_team or ""),
            league=str(match.league or ""),
            minute=str(current_minute or ""),
            minute_number=minute_num,
            period=str(getattr(match, "period", "") or ""),
            home_score=home,
            away_score=away,
            status=str(getattr(match, "status", "") or ""),
            performance=saved_performance,
            odds=[],
            fingerprint=hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True, default=str).encode("utf-8")).hexdigest(),
            observed_at=timezone.now(),
        )

        return JsonResponse({
            "ok": True,
            "partido": {
                "id": match.ecuabet_event_id,
                "local": match.home_team,
                "visitante": match.away_team,
                "liga": match.league,
                "minuto": current_minute,
                "marcador": now_score,
                "calidad_datos": match.data_quality,
                "confianza_mapeo": match.mapping_confidence,
            },
            "etapas": {
                "contexto": context_stage,
                "monitoreo": monitoring,
                "accion": stage_action,
                "probabilidad": stage_probability,
                "calculo": stage_calculation,
                "reaccion": stage_reaction,
            },
            "nota": "Simulación del patrón con datos LIVE y motores actuales; no crea apuestas ni modifica capitales.",
        })
    except MatchMappingError as exc:
        return JsonResponse({"ok": False, "error": f"No se pudo vincular el partido con Flashscore: {exc}"}, status=422)
    except Exception as exc:
        logger.exception("Error en simulación del Patrón de Oportunidades para %s", ecuabet_event_id)
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
