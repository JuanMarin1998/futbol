from django.http import JsonResponse
from django.shortcuts import render
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
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
from .models import LiveExperiment, LiveExperimentEntry, LiveExperimentDailyArchive

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
