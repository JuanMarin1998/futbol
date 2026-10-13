"""Vistas del laboratorio de corredores virtuales, separado de los nueve motores."""
import json
import logging
import time
from threading import Thread

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.test import RequestFactory
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .live_engine.betting_runners import BettingRunnerLab
from .models import BettingRunner, BettingRunnerBet, BettingRunnerEvaluation, MatchBehaviorSnapshot

logger = logging.getLogger(__name__)
RUNNER_WORKER_KEY = "betting_runner_lab_enabled"
RUNNER_START_KEY = "betting_runner_lab_starting"
RUNNER_CYCLE_KEY = "betting_runner_lab_cycle_busy"


def _payload(response):
    try:
        return json.loads(response.content.decode("utf-8"))
    except (ValueError, AttributeError, UnicodeDecodeError):
        return {"ok": False, "error": "Respuesta interna no válida."}


def _runner_state():
    BettingRunnerLab.seed_runners()
    today = timezone.localdate()
    runner_rows = []
    for runner in BettingRunner.objects.order_by("id"):
        bets = BettingRunnerBet.objects.filter(runner=runner)
        today_bets = bets.filter(placed_at__date=today)
        pnl_today = sum((bet.pnl for bet in today_bets), start=0)
        runner_rows.append({
            "key": runner.key,
            "name": runner.name,
            "strategy": runner.strategy,
            "description": runner.description,
            "active": runner.active,
            "initial_lives": float(runner.initial_lives),
            "lives": float(BettingRunnerLab.lives(runner, today)),
            "bets_today": today_bets.count(),
            "bets_total": bets.count(),
            "open": bets.filter(status="OPEN").count(),
            "won": bets.filter(status="WON").count(),
            "lost": bets.filter(status="LOST").count(),
            "cancelled": bets.filter(status="CANCELLED").count(),
            "pnl_today": float(pnl_today),
            "pnl_total": float(sum((bet.pnl for bet in bets), start=0)),
            "last_evaluation": (
                runner.evaluations.order_by("-evaluated_at").values(
                    "action", "reason", "selected_market", "home_team", "away_team",
                    "evaluated_minute", "evaluated_home_score", "evaluated_away_score", "evaluated_at"
                ).first()
            ),
        })
    recent_bets = []
    for bet in BettingRunnerBet.objects.select_related("runner").order_by("-placed_at")[:100]:
        recent_bets.append({
            "runner": bet.runner.name,
            "runner_key": bet.runner.key,
            "event_id": bet.ecuabet_event_id,
            "home": bet.home_team,
            "away": bet.away_team,
            "market": bet.market,
            "selection": bet.selection,
            "line": bet.line,
            "price": float(bet.price),
            "probability": bet.model_probability,
            "edge": bet.edge,
            "stake": float(bet.stake),
            "potential_profit": float(bet.potential_profit),
            "status": bet.status,
            "pnl": float(bet.pnl),
            "reason": bet.reason,
            "minute": bet.placed_minute,
            "score": [bet.placed_home_score, bet.placed_away_score],
            "final_score": [bet.final_home_score, bet.final_away_score],
            "placed_at": timezone.localtime(bet.placed_at).isoformat(),
            "settled_at": timezone.localtime(bet.settled_at).isoformat() if bet.settled_at else None,
        })
    recent_evaluations = []
    for ev in BettingRunnerEvaluation.objects.select_related("runner").order_by("-evaluated_at")[:60]:
        recent_evaluations.append({
            "runner": ev.runner.name,
            "event_id": ev.ecuabet_event_id,
            "home": ev.home_team,
            "away": ev.away_team,
            "action": ev.action,
            "reason": ev.reason,
            "selected_market": ev.selected_market,
            "minute": ev.evaluated_minute,
            "score": [ev.evaluated_home_score, ev.evaluated_away_score],
            "evaluated_at": timezone.localtime(ev.evaluated_at).isoformat(),
        })
    return {
        "ok": True,
        "running": bool(cache.get(RUNNER_WORKER_KEY)),
        "starting": bool(cache.get(RUNNER_START_KEY)),
        "busy": bool(cache.get(RUNNER_CYCLE_KEY)),
        "today": today.isoformat(),
        "runners": runner_rows,
        "bets": recent_bets,
        "evaluations": recent_evaluations,
        "last_cycle": cache.get("betting_runner_lab_last_cycle") or {},
        "updated_at": timezone.localtime().isoformat(),
    }


def corredores_apuestas(request):
    BettingRunnerLab.seed_runners()
    return render(request, "estadisticas/corredores_apuestas.html", {
        "seccion": "corredores_apuestas",
    })


@require_GET
def api_corredores_estado(request):
    try:
        return JsonResponse(_runner_state())
    except Exception as exc:
        logger.exception("No se pudo construir el estado del laboratorio de corredores")
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


def _confirm_runner_event_result(event_id, collector=None):
    """Confirma el final con el ID Flashscore persistido; no confía en un marcador LIVE."""
    from .live_engine.collector import LiveMatchCollector

    collector = collector or LiveMatchCollector()
    snapshot = MatchBehaviorSnapshot.objects.filter(
        ecuabet_event_id=int(event_id)
    ).exclude(flashscore_event_id="").order_by("-observed_at").first()

    if snapshot and snapshot.flashscore_event_id:
        match = collector.construir_desde_flashscore(
            snapshot.flashscore_event_id,
            ecuabet_event_id=int(event_id),
            home_team=snapshot.home_team,
            away_team=snapshot.away_team,
        )
    else:
        # Compatibilidad para partidos sin vínculo Flashscore persistido.
        match = collector.construir_automatico(int(event_id))

    if not getattr(match, "is_finished", False):
        return {"settled": 0, "status": getattr(match, "match_status", None) or "PENDIENTE", "reason": "El proveedor todavía no confirma el final."}
    if match.home_score is None or match.away_score is None:
        return {"settled": 0, "status": "FINISHED_PENDING_SCORE", "reason": "El partido figura finalizado, pero falta un marcador final verificable."}

    settled = BettingRunnerLab.settle_event(
        int(event_id), match.home_score, match.away_score, True
    )
    return {
        "settled": settled,
        "status": "FINISHED",
        "score": [int(match.home_score), int(match.away_score)],
        "reason": "Resultado final confirmado desde el feed de Flashscore.",
    }


def _run_cycle():
    if not cache.add(RUNNER_CYCLE_KEY, True, 900):
        return {"ok": True, "busy": True, "message": "El ciclo anterior todavía está procesándose."}
    try:
        BettingRunnerLab.seed_runners()
        from . import views_live
        factory = RequestFactory()
        candidate_response = views_live.api_patron_oportunidades_partidos(factory.get("/api/live/patron-oportunidades/partidos/"))
        candidate_payload = _payload(candidate_response)
        if not candidate_payload.get("ok"):
            return {"ok": False, "error": candidate_payload.get("error", "No se pudieron obtener partidos LIVE."), "events": []}

        events = candidate_payload.get("events") or []
        outcomes = []
        live_ids = set()
        for event in events:
            event_id = event.get("id")
            if not event_id:
                continue
            live_ids.add(int(event_id))
            try:
                response = views_live.api_simular_patron_oportunidades(
                    factory.get(f"/api/live/patron-oportunidades/{int(event_id)}/"),
                    int(event_id),
                )
                payload = _payload(response)
                if payload.get("ok"):
                    outcomes.append(BettingRunnerLab.process_payload(event_id, payload))
                else:
                    outcomes.append({"event_id": event_id, "bets_placed": 0, "error": payload.get("error", "El Patrón no produjo oportunidades válidas.")})
            except Exception as exc:
                logger.exception("Error procesando corredor para evento %s", event_id)
                outcomes.append({"event_id": event_id, "bets_placed": 0, "error": str(exc)})

        # Comprobar apuestas abiertas en cada ciclo. Si el evento ya no está LIVE,
        # usar el ID Flashscore persistido y exigir final + marcador verificable.
        open_event_ids = list(
            BettingRunnerBet.objects.filter(status="OPEN")
            .values_list("ecuabet_event_id", flat=True).distinct()
        )
        for event_id in open_event_ids:
            if int(event_id) in live_ids:
                continue
            try:
                result = _confirm_runner_event_result(event_id)
                outcomes.append({"event_id": int(event_id), **result})
            except Exception as exc:
                # No liquidar por suposición; conservar OPEN y exponer el diagnóstico.
                logger.warning("Resultado aún no confirmado para evento %s: %s", event_id, exc)
                outcomes.append({
                    "event_id": int(event_id),
                    "settled": 0,
                    "status": "ERROR_CONSULTA",
                    "error": str(exc),
                })

        return {
            "ok": True,
            "live_count": len(events),
            "processed": len(outcomes),
            "bets_placed": sum(int(item.get("bets_placed") or 0) for item in outcomes),
            "settled": sum(int(item.get("settled") or 0) for item in outcomes),
            "outcomes": outcomes[:100],
            "updated_at": timezone.localtime().isoformat(),
        }
    finally:
        cache.delete(RUNNER_CYCLE_KEY)


def _runner_worker():
    while cache.get(RUNNER_WORKER_KEY):
        try:
            result = _run_cycle()
            cache.set("betting_runner_lab_last_cycle", result, 3600)
        except Exception as exc:
            logger.exception("Error en el ciclo automático de corredores")
            cache.set("betting_runner_lab_last_cycle", {"ok": False, "error": str(exc)}, 3600)
        # El worker es independiente del navegador; se detiene al borrar la bandera.
        for _ in range(30):
            if not cache.get(RUNNER_WORKER_KEY):
                break
            time.sleep(1)
    cache.delete(RUNNER_START_KEY)


@require_POST
def api_corredores_iniciar(request):
    BettingRunnerLab.seed_runners()
    if cache.get(RUNNER_WORKER_KEY):
        return JsonResponse({"ok": True, "running": True, "message": "El laboratorio ya está activo."})
    if not cache.add(RUNNER_START_KEY, True, 180):
        return JsonResponse({"ok": True, "running": True, "starting": True, "message": "El laboratorio ya se está iniciando."})
    cache.set(RUNNER_WORKER_KEY, True, 7 * 24 * 3600)
    Thread(target=_runner_worker, name="betting-runner-lab", daemon=True).start()
    return JsonResponse({"ok": True, "running": True, "starting": True, "message": "Laboratorio iniciado; primera lectura en segundo plano."})


@require_POST
def api_corredores_pausar(request):
    cache.delete(RUNNER_WORKER_KEY)
    cache.delete(RUNNER_START_KEY)
    return JsonResponse({"ok": True, "running": False, "message": "Laboratorio de corredores pausado. Las apuestas abiertas conservan su estado."})


@require_POST
def api_corredores_ciclo(request):
    try:
        result = _run_cycle()
        cache.set("betting_runner_lab_last_cycle", result, 3600)
        return JsonResponse(result, status=200 if result.get("ok") else 502)
    except Exception as exc:
        logger.exception("Error ejecutando ciclo manual de corredores")
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)


@require_POST
def api_corredores_liquidar(request):
    """Intenta liquidar apuestas abiertas usando el marcador final del proveedor."""
    checked, settled, errors, pending = 0, 0, [], []
    event_ids = list(BettingRunnerBet.objects.filter(status="OPEN").values_list("ecuabet_event_id", flat=True).distinct())
    for event_id in event_ids:
        checked += 1
        try:
            result = _confirm_runner_event_result(event_id)
            settled += int(result.get("settled") or 0)
            if not result.get("settled"):
                pending.append({"event_id": int(event_id), **result})
        except Exception as exc:
            errors.append({"event_id": int(event_id), "status": "ERROR_CONSULTA", "error": str(exc)})
    return JsonResponse({
        "ok": True,
        "checked": checked,
        "settled": settled,
        "pending": pending[:30],
        "errors": errors[:20],
    })


@require_POST
def api_corredores_reiniciar(request):
    """Reinicia el experimento del día conservando las apuestas históricas."""
    from django.db import transaction
    from django.utils import timezone
    today = timezone.localdate()
    with transaction.atomic():
        BettingRunnerBet.objects.filter(status="OPEN", placed_at__date=today).update(
            status="CANCELLED", pnl=0, settled_at=timezone.now()
        )
        # No se borran apuestas ni evaluaciones; el saldo diario vuelve a 100 por el libro del día.
    return JsonResponse({"ok": True, "message": "Experimento reiniciado: se cancelaron las abiertas de hoy y se conservó el historial."})


@require_POST
def api_corredores_borrar_apuestas_hoy(request):
    """Elimina las apuestas del día local y conserva las evaluaciones e historial anterior."""
    from django.db import transaction

    today = timezone.localdate()
    # Pausa el proceso para evitar que vuelva a registrar apuestas durante la limpieza.
    cache.delete(RUNNER_WORKER_KEY)
    cache.delete(RUNNER_START_KEY)
    with transaction.atomic():
        deleted, _ = BettingRunnerBet.objects.filter(placed_at__date=today).delete()
    return JsonResponse({
        "ok": True,
        "running": False,
        "deleted": deleted,
        "message": f"Se eliminaron {deleted} registros de apuestas de hoy ({today}). Se conservaron las evaluaciones y apuestas de días anteriores. Laboratorio pausado.",
    })
