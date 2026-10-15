"""Laboratorio independiente de seis corredores virtuales.

Consume exclusivamente las oportunidades que ya genera el Patrón de Oportunidades.
Las cuotas de apuesta son las cuotas LIVE de Ecuabet presentes en la respuesta recién
consultada; la cuota justa nunca se usa como precio de apuesta.
"""
from decimal import Decimal, ROUND_DOWN
import logging
import re

from django.db import transaction
from django.utils import timezone

from ..models import BettingRunner, BettingRunnerBet, BettingRunnerEvaluation
from .experiment import LiveExperimentManager

logger = logging.getLogger(__name__)

RUNNERS = (
    ("valor", "Cazador de valor", "value", "Prioriza valor esperado positivo con precio LIVE confirmado."),
    ("conservador", "Conservador", "conservative", "Prioriza probabilidad alta y ventaja positiva."),
    ("live", "Especialista LIVE", "live_trigger", "Solo decide después de un gol o tarjeta roja nueva."),
    ("contexto", "Analista de contexto", "context", "Contrasta la oportunidad con favorito, marcador y minuto."),
    ("validador", "Validador de datos", "validator", "Exige calidad y cantidad de estadísticas comparables."),
    ("inteligente", "Selector inteligente", "smart", "Combina valor, probabilidad, confianza y calidad."),
)


class BettingRunnerLab:
    INITIAL_LIVES = Decimal("100.0000")

    @classmethod
    def seed_runners(cls):
        for key, name, strategy, description in RUNNERS:
            BettingRunner.objects.get_or_create(
                key=key,
                defaults={
                    "name": name,
                    "strategy": strategy,
                    "description": description,
                    "initial_lives": cls.INITIAL_LIVES,
                    "active": True,
                },
            )

    @classmethod
    def lives(cls, runner, day=None):
        """Mismo libro de vidas de los motores: abierto/perdido descuenta stake,
        ganada suma beneficio neto y cancelada no altera el capital. Reinicio diario.
        """
        day = day or timezone.localdate()
        entries = BettingRunnerBet.objects.filter(
            runner=runner, placed_at__date=day
        ).order_by("placed_at", "id")
        lives = Decimal(str(runner.initial_lives))
        for entry in entries:
            if entry.status in {"OPEN", "LOST"}:
                lives -= Decimal(str(entry.stake))
            elif entry.status == "WON":
                lives += Decimal(str(entry.pnl))
        return max(Decimal("0"), lives)

    @staticmethod
    def _as_float(value, default=None):
        try:
            if value is None or value == "":
                return default
            return float(str(value).replace(",", ".").replace("%", ""))
        except (TypeError, ValueError):
            return default

    @classmethod
    def _normalise_markets(cls, payload):
        stages = payload.get("etapas") or {}
        # REACCIÓN es la única interfaz entre el Patrón y los corredores.
        # Los corredores no consumen directamente el cálculo interno de mercados.
        reaction = stages.get("reaccion") or {}
        reaction_signals = reaction.get("senales_recibidas") or []
        probability_stage = stages.get("probabilidad") or {}
        monitoring = stages.get("monitoreo") or {}
        quality = cls._as_float(probability_stage.get("calidad_datos"), 0.0) or 0.0
        confidence = cls._as_float(probability_stage.get("confianza_calculador"), 0.35) or 0.35
        stat_count = int(cls._as_float(probability_stage.get("cantidad_estadisticas_utilizadas"), 0) or 0)
        match = payload.get("partido") or {}
        context = stages.get("contexto") or {}
        candidates = []
        for source in reaction_signals:
            if not isinstance(source, dict):
                continue
            key = str(source.get("clave") or "").strip()
            price = cls._as_float(source.get("cuota_ecuabet"))
            probability = cls._as_float(source.get("probabilidad_decimal"))
            if probability is None:
                pct = cls._as_float(source.get("probabilidad"))
                probability = pct / 100.0 if pct is not None else None
            if not key or probability is None:
                continue
            # La única cuota válida para registrar una apuesta es la cuota actual de Ecuabet.
            # No se sustituye por cuota justa, cuota prepartido ni una cotización antigua.
            if price is None or price <= 1 or source.get("estado_cuota_ecuabet") != "DISPONIBLE":
                continue
            if source.get("estado_live") == "CERRADO_RESULTADO_DETERMINADO":
                continue
            if not 0 < probability < 1:
                continue
            edge = probability * price - 1.0
            candidates.append({
                "key": key,
                "market": str(source.get("mercado") or key),
                "price": price,
                "probability": probability,
                "confidence": max(0.0, min(1.0, confidence)),
                "quality": max(0.0, min(1.0, quality)),
                "stat_count": stat_count,
                "edge": edge,
                "trigger": bool(monitoring.get("detonante")),
                "favorite": str(context.get("favorito") or ""),
                "minute": str(match.get("minuto") or ""),
                "score": match.get("marcador") or [None, None],
                "source": source,
                "match": match,
            })
        return candidates, {"reaccion": reaction, "senales_recibidas": len(reaction_signals), "etapas": stages}

    @staticmethod
    def _minute(value):
        found = re.search(r"(\d{1,3})", str(value or ""))
        return int(found.group(1)) if found else 0

    @classmethod
    def _context_fit(cls, candidate):
        key = candidate["key"]
        favorite = candidate["favorite"].casefold()
        match = candidate["match"]
        home_name = str(match.get("local") or "").casefold()
        away_name = str(match.get("visitante") or "").casefold()
        score = match.get("marcador") or [None, None]
        try:
            home, away = int(score[0]), int(score[1])
        except (TypeError, ValueError, IndexError):
            home = away = None
        minute = cls._minute(candidate["minute"])
        favorite_home = bool(favorite and home_name and (favorite in home_name or home_name in favorite))
        favorite_away = bool(favorite and away_name and (favorite in away_name or away_name in favorite))
        if favorite_home and key in {"home", "dc_1x"} and not (away is not None and home is not None and minute >= 70 and away > home):
            return True
        if favorite_away and key in {"away", "dc_x2"} and not (away is not None and home is not None and minute >= 70 and home > away):
            return True
        # Los mercados de goles/BTTS pueden tener sentido aunque no sean victoria del favorito.
        return key.startswith(("over_", "under_", "btts_")) and candidate["edge"] >= 0.03

    @classmethod
    def _choose(cls, runner, candidates):
        strategy = runner.strategy
        non_extreme = [c for c in candidates if 0.01 <= c["probability"] <= 0.99]
        if strategy == "value":
            pool = [c for c in non_extreme if c["edge"] >= 0.015]
            return max(pool, key=lambda c: c["edge"], default=None), "Mayor EV positivo con cuota LIVE confirmada."
        if strategy == "conservative":
            # No confiar íntegramente en probabilidades LIVE aún no calibradas:
            # reducir a la mitad la ventaja estimada frente a la probabilidad implícita
            # de la cuota actual. Es un filtro prudencial provisional, no un modelo
            # estadístico entrenado; los valores originales quedan en el snapshot.
            pool = []
            for candidate in non_extreme:
                implied_probability = 1.0 / candidate["price"]
                adjusted_probability = implied_probability + 0.50 * (
                    candidate["probability"] - implied_probability
                )
                adjusted_edge = adjusted_probability * candidate["price"] - 1.0
                if (
                    candidate["probability"] >= 0.72
                    and candidate["price"] >= 1.40
                    and adjusted_probability >= 0.72
                    and adjusted_edge >= 0.03
                ):
                    selected = dict(candidate)
                    selected["original_probability"] = candidate["probability"]
                    selected["conservative_adjusted"] = True
                    selected["probability"] = adjusted_probability
                    selected["edge"] = adjusted_edge
                    pool.append(selected)
            return max(pool, key=lambda c: (c["edge"], c["probability"]), default=None), "Probabilidad prudencial ajustada hacia la cuota LIVE; cuota ≥ 1.40 y EV ajustado ≥ 3%."
        if strategy == "live_trigger":
            pool = [c for c in non_extreme if c["trigger"] and c["edge"] >= 0.005]
            return max(pool, key=lambda c: c["edge"], default=None), "Detonante LIVE nuevo y valor positivo."
        if strategy == "context":
            pool = [c for c in non_extreme if c["edge"] >= 0.01 and cls._context_fit(c)]
            return max(pool, key=lambda c: (c["edge"], c["confidence"]), default=None), "La oportunidad encaja con el contexto y conserva EV positivo."
        if strategy == "validator":
            pool = [
                c for c in non_extreme
                if c["quality"] >= 0.75 and c["stat_count"] >= 3 and c["edge"] >= 0.02
            ]
            return max(pool, key=lambda c: (c["edge"], c["quality"]), default=None), "Calidad ≥ 0.75, tres estadísticas comparables y EV positivo."
        # Selector inteligente: exige un mínimo de valor, luego puntúa señales de forma combinada.
        pool = [c for c in non_extreme if c["edge"] >= 0.01 and c["quality"] >= 0.25]
        def score(c):
            ev_score = max(0.0, min(1.0, c["edge"] / 0.20))
            return 0.40 * ev_score + 0.25 * c["confidence"] + 0.15 * c["probability"] + 0.20 * c["quality"]
        chosen = max(pool, key=score, default=None)
        if chosen:
            chosen["runner_score"] = round(score(chosen), 4)
        return chosen, "Mayor puntuación combinada de EV, confianza, probabilidad y calidad."

    @staticmethod
    def _stake(candidate, lives):
        """Reutiliza el cálculo de stake de LiveExperimentManager sin ejecutar motores."""
        if lives < Decimal("1.00"):
            return Decimal("0")
        edge = Decimal(str(candidate["edge"]))
        confidence = Decimal(str(candidate["confidence"]))
        if edge >= Decimal("0.10") and confidence >= Decimal("0.70"):
            level = 1
        elif edge >= Decimal("0.04") and confidence >= Decimal("0.55"):
            level = 2
        elif edge > 0:
            level = 3
        else:
            return Decimal("0")
        adapted = {
            "level": level,
            "confidence": float(confidence),
            "edge": float(edge),
        }
        # V11 usa los mismos rangos 8–10, 5–7 y 1–4 vidas que el libro existente.
        stake = LiveExperimentManager._stake(adapted, lives, motor="V11")
        return min(stake, lives).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    @staticmethod
    def _market_parts(candidate):
        key = candidate["key"]
        mapping = {
            "home": ("resultado", "local", ""),
            "draw": ("resultado", "empate", ""),
            "away": ("resultado", "visitante", ""),
            "dc_1x": ("doble oportunidad", "1X", ""),
            "dc_12": ("doble oportunidad", "12", ""),
            "dc_x2": ("doble oportunidad", "X2", ""),
            "btts_yes": ("ambos marcan", "sí", ""),
            "btts_no": ("ambos marcan", "no", ""),
        }
        if key in mapping:
            return mapping[key]
        found = re.match(r"^(over|under)_(\d+_\d+)$", key)
        if found:
            line = found.group(2).replace("_", ".")
            return ("total goles", "más" if found.group(1) == "over" else "menos", line)
        return (candidate["market"], candidate["market"], "")

    @classmethod
    @transaction.atomic
    def process_payload(cls, event_id, payload):
        cls.seed_runners()
        if not payload or not payload.get("ok"):
            return {"event_id": event_id, "bets_placed": 0, "error": (payload or {}).get("error", "Respuesta del Patrón no válida.")}
        match = payload.get("partido") or {}
        stages = payload.get("etapas") or {}
        monitoring = stages.get("monitoreo") or {}
        trigger = monitoring.get("ultimo_detonante")
        try:
            event_id = int(event_id)
        except (TypeError, ValueError):
            return {"event_id": event_id, "bets_placed": 0, "error": "ID de evento inválido."}
        if not match.get("local") or not match.get("visitante"):
            return {"event_id": event_id, "bets_placed": 0, "error": "El partido no está identificado correctamente."}

        # Barrera global de seguridad: ninguna estrategia puede apostar si el patrón
        # no entrega un gol/roja nuevos confirmados. No basta con que existan mercados.
        if (
            monitoring.get("detonante") is not True
            or not isinstance(trigger, dict)
            or trigger.get("tipo") not in {"GOL", "TARJETA_ROJA"}
            or not str(trigger.get("id") or "").strip()
        ):
            return {
                "event_id": event_id,
                "bets_placed": 0,
                "evaluations": [],
                "status": "WAITING_TRIGGER",
                "reason": "Sin detonante nuevo confirmado; ningún corredor puede registrar apuestas.",
            }

        candidates, _ = cls._normalise_markets(payload)
        score = match.get("marcador") or [None, None]
        try:
            home_score, away_score = int(score[0]), int(score[1])
        except (TypeError, ValueError, IndexError):
            home_score = away_score = None
        placed = 0
        outcomes = []
        trigger_id = str(trigger["id"])
        for runner in BettingRunner.objects.filter(active=True).order_by("id"):
            existing = BettingRunnerBet.objects.filter(runner=runner, ecuabet_event_id=event_id).first()
            prior_evaluation = BettingRunnerEvaluation.objects.filter(
                runner=runner, ecuabet_event_id=event_id
            ).first()
            prior_snapshot = prior_evaluation.snapshot if prior_evaluation and isinstance(prior_evaluation.snapshot, dict) else {}
            if existing:
                action, reason, selected = "BET_ALREADY_PLACED", "Este corredor ya registró su única apuesta para este partido.", existing.market
            elif (
                prior_snapshot.get("trigger_id") == trigger_id
                and prior_evaluation.action != "WAIT"
            ):
                action = "TRIGGER_PROCESSED"
                reason = "Este detonante ya produjo una decisión final para este corredor."
                selected = prior_evaluation.selected_market or ""
            # Si la evaluación anterior terminó en WAIT, se permite reintentar el
            # mismo detonante cuando REACCIÓN vuelva a entregar oportunidades.
            # Las apuestas existentes siguen bloqueadas por la comprobación anterior.
            else:
                chosen, strategy_reason = cls._choose(runner, candidates)
                if not chosen:
                    action, selected = "WAIT", ""
                    if runner.strategy == "validator":
                        reason = "Ninguna oportunidad superó los filtros de calidad, estadísticas comparables y cuota LIVE válida."
                    elif runner.strategy == "live_trigger" and not any(c["trigger"] for c in candidates):
                        reason = "Esperando un gol o una tarjeta roja nueva; sin detonante no apuesta."
                    elif not candidates:
                        reason = "No hay oportunidades con cuota LIVE vigente de Ecuabet para el mismo mercado y selección."
                    else:
                        reason = "Ninguna oportunidad cumplió los criterios propios de esta estrategia."
                else:
                    lives = cls.lives(runner)
                    stake = cls._stake(chosen, lives)
                    # Limitar la exposición del corredor Conservador: su objetivo es
                    # sobrevivir a errores de estimación, no maximizar el importe.
                    if runner.strategy == "conservative":
                        stake = min(stake, Decimal("5.00"))
                    if stake <= 0:
                        action, selected = "WAIT", ""
                        reason = "Capital disponible insuficiente o stake calculado igual a cero."
                    else:
                        market, selection, line = cls._market_parts(chosen)
                        price = Decimal(str(chosen["price"]))
                        potential_profit = (stake * (price - Decimal("1"))).quantize(Decimal("0.0001"))
                        bet = BettingRunnerBet.objects.create(
                            runner=runner,
                            ecuabet_event_id=event_id,
                            home_team=str(match["local"])[:180],
                            away_team=str(match["visitante"])[:180],
                            market_key=chosen["key"],
                            market=market,
                            selection=selection,
                            line=line,
                            price=price,
                            model_probability=float(chosen["probability"]),
                            confidence=float(chosen["confidence"]),
                            edge=float(chosen["edge"]),
                            stake=stake,
                            potential_profit=potential_profit,
                            status="OPEN",
                            reason=f"{strategy_reason} Precio LIVE de Ecuabet confirmado en esta lectura. {chosen['market']}: probabilidad {chosen['probability']:.2%}, EV {chosen['edge']:+.2%}.",
                            opportunity_snapshot={
                                "oportunidad": chosen["source"],
                                "precio_fuente": "Ecuabet LIVE",
                                "calidad_datos": chosen["quality"],
                                "estadisticas_comparables": chosen["stat_count"],
                                "probabilidad_original": chosen.get("original_probability", chosen["probability"]),
                                "probabilidad_ajustada_conservador": chosen.get("conservative_adjusted", False),
                                "etapas": stages,
                                "runner_score": chosen.get("runner_score"),
                            },
                            placed_minute=str(match.get("minuto") or ""),
                            placed_home_score=home_score,
                            placed_away_score=away_score,
                        )
                        action, reason, selected = "BET", bet.reason, bet.market
                        placed += 1
            evaluation_snapshot = {
                "opportunities_with_live_price": len(candidates),
                "runner_strategy": runner.strategy,
                "trigger_id": trigger_id,
                "trigger_type": trigger.get("tipo"),
                "trigger": trigger,
                # Cada corredor conserva el informe recibido, incluso cuando decide esperar.
                "analisis_patron": stages,
            }
            BettingRunnerEvaluation.objects.update_or_create(
                runner=runner,
                ecuabet_event_id=event_id,
                defaults={
                    "home_team": str(match["local"])[:180],
                    "away_team": str(match["visitante"])[:180],
                    "action": action,
                    "reason": reason,
                    "selected_market": selected,
                    "evaluated_minute": str(match.get("minuto") or ""),
                    "evaluated_home_score": home_score,
                    "evaluated_away_score": away_score,
                    "snapshot": evaluation_snapshot,
                },
            )
            outcomes.append({"runner": runner.key, "action": action, "market": selected, "reason": reason})
        return {"event_id": event_id, "bets_placed": placed, "evaluations": outcomes}

    @staticmethod
    def _market_result(bet, home_score, away_score):
        key = bet.market_key
        total = home_score + away_score
        if key == "home":
            return home_score > away_score
        if key == "draw":
            return home_score == away_score
        if key == "away":
            return away_score > home_score
        if key == "dc_1x":
            return home_score >= away_score
        if key == "dc_12":
            return home_score != away_score
        if key == "dc_x2":
            return away_score >= home_score
        if key == "btts_yes":
            return home_score > 0 and away_score > 0
        if key == "btts_no":
            return home_score == 0 or away_score == 0
        found = re.match(r"^(over|under)_(\d+_\d+)$", key)
        if found:
            line = float(found.group(2).replace("_", "."))
            return total > line if found.group(1) == "over" else total < line
        return None

    @classmethod
    @transaction.atomic
    def settle_event(cls, event_id, home_score, away_score, finished):
        if not finished:
            return 0
        try:
            home_score, away_score = int(home_score), int(away_score)
        except (TypeError, ValueError):
            return 0
        settled = 0
        bets = BettingRunnerBet.objects.select_for_update().filter(
            ecuabet_event_id=int(event_id), status="OPEN"
        )
        for bet in bets:
            won = cls._market_result(bet, home_score, away_score)
            if won is None:
                bet.status, bet.pnl = "CANCELLED", Decimal("0")
            elif won:
                bet.status, bet.pnl = "WON", bet.potential_profit
            else:
                bet.status, bet.pnl = "LOST", -bet.stake
            bet.final_home_score, bet.final_away_score = home_score, away_score
            bet.settled_at = timezone.now()
            bet.save(update_fields=["status", "pnl", "final_home_score", "final_away_score", "settled_at"])
            settled += 1
        return settled
