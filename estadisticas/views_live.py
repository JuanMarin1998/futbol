from django.http import JsonResponse
from django.shortcuts import render
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
import logging
from concurrent.futures import ThreadPoolExecutor

from .api_football_live import APIFootballLiveClient
from .ecuabet_client import EcuabetClient
from .live_engine.collector import LiveMatchCollector
from .live_engine.match_mapper import MatchMappingError
from .live_engine.experiment import LiveExperimentManager
from .models import LiveExperiment, LiveExperimentDailyArchive

logger = logging.getLogger(__name__)


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
    """Obtiene todos los partidos LIVE y devuelve su payload completo."""
    payload = EcuabetClient()._request(
        "GET", "GetLivenow", {"eventCount": 0, "sportId": 66}
    )
    return payload, payload.get("events", []) or []


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

    max_workers = min(8, len(tasks))
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


def _experimento_estado_global():
    """Procesa el laboratorio global sin bloquear el ciclo con consultas repetidas."""
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
        serialized = [LiveExperimentManager.serialize(x) for x in experiments]
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

        # Detecta partidos LIVE nuevos mientras el laboratorio ya está activo.
        # El mapeo automático solo se hace para partidos que todavía no existen.
        if running:
            running_ids = {int(x.ecuabet_event_id) for x in running}
            for event in live_events:
                if event.get("id") is None:
                    continue
                event_id = int(event["id"])
                if event_id in running_ids:
                    continue
                try:
                    match = collector.construir_automatico(event_id)
                    if match.is_finished:
                        continue
                    experiment = LiveExperimentManager.start(match)
                    running.append(experiment)
                    running_ids.add(event_id)
                except Exception as exc:
                    logger.exception(
                        "No se pudo incorporar el nuevo LIVE %s al laboratorio.",
                        event_id,
                    )

        # Este es el cambio importante: un solo GetLivenow por ciclo y
        # reutilización del flashscore_event_id ya confirmado.
        processing_errors = _procesar_experimentos_live(live_events, running)

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
        serialized = [LiveExperimentManager.serialize(x) for x in experiments]

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
            "busy": False,
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


def api_live_experiment_start_all(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido."}, status=405)
    try:
        _, live_events = _experimento_live_payload()
        collector = LiveMatchCollector()
        created = 0
        skipped = 0
        errors = []

        for event in live_events:
            if event.get("id") is None:
                continue
            event_id = int(event["id"])
            event_name = str(event.get("name") or f"Ecuabet {event_id}")
            if LiveExperiment.objects.filter(
                ecuabet_event_id=event_id, status="RUNNING"
            ).exists():
                skipped += 1
                continue
            try:
                match = collector.construir_automatico(event_id)
                if match.is_finished:
                    errors.append({
                        "event_id": event_id,
                        "match": event_name,
                        "error": "El partido ya figura como finalizado.",
                    })
                    continue
                LiveExperimentManager.start(match)
                created += 1
            except Exception as exc:
                logger.exception(
                    "No se pudo iniciar experimento para Ecuabet %s (%s).",
                    event_id,
                    event_name,
                )
                errors.append({
                    "event_id": event_id,
                    "match": event_name,
                    "error": str(exc),
                })

        today = timezone.localdate()
        experiments = list(
            LiveExperiment.objects
            .filter(
                status__in=["RUNNING", "FINISHED", "STOPPED"],
                started_at__date=today,
            )
            .order_by("-updated_at")[:200]
        )
        serialized = [LiveExperimentManager.serialize(x) for x in experiments]
        entries = [
            {**entry, "experiment_id": exp.get("id"), "match_status": exp.get("status")}
            for exp in serialized
            for entry in exp.get("entries", [])
        ]
        return JsonResponse({
            "ok": True,
            "running": any(x.get("status") == "RUNNING" for x in serialized),
            "experiments": serialized,
            "entries": entries,
            "live_count": len(live_events),
            "created": created,
            "skipped": skipped,
            "start_errors": errors[:20],
            "start_error_count": len(errors),
            "start_message": (
                "Experimentos iniciados correctamente."
                if created
                else (
                    "No se pudo iniciar ningún experimento."
                    if live_events
                    else "Ecuabet no reporta partidos de fútbol LIVE en este momento."
                )
            ),
            "busy": False,
        })
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)


def api_live_experiment_stop_all(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido."}, status=405)
    try:
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
        return JsonResponse(_experimento_estado_global())
    except Exception as exc:
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
        payload = EcuabetClient()._request(
            "GET",
            "GetLivenow",
            {"eventCount": 0, "sportId": 66},
        )
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

        markets = {
            int(m["id"]): m for m in payload.get("markets", []) or []
            if m.get("id") is not None
        }
        odds = {
            int(o["id"]): o for o in payload.get("odds", []) or []
            if o.get("id") is not None
        }
        competitors = {
            int(x["id"]): x for x in payload.get("competitors", []) or []
            if x.get("id") is not None
        }
        event["competitors"] = [
            competitors.get(int(cid), {"id": cid, "name": str(cid)})
            for cid in event.get("competitorIds", []) or []
        ]
        event["markets"] = []
        for market_id in event.get("marketIds", []) or []:
            market = markets.get(int(market_id))
            if not market:
                continue
            selections = []
            for odd_id in market.get("oddIds", []) or []:
                odd = odds.get(int(odd_id))
                if odd:
                    selections.append({
                        "id": odd.get("id"),
                        "name": odd.get("name", ""),
                        "price": odd.get("price"),
                        "type_id": odd.get("typeId"),
                        "odd_status": odd.get("oddStatus"),
                    })
            if selections:
                event["markets"].append({
                    "id": market.get("id"),
                    "name": market.get("name", ""),
                    "type_id": market.get("typeId"),
                    "line": market.get("sv") or market.get("sn"),
                    "selections": selections,
                })

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
