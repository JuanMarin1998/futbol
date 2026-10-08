from decimal import Decimal, ROUND_DOWN
import re
from typing import Any, Dict, Optional

from django.db import transaction
from django.utils import timezone

from ..models import LiveExperiment, LiveExperimentEntry, LiveExperimentSnapshot, LiveExperimentDailyArchive
from .opportunity_levels import enrich


class LiveExperimentManager:
    """Laboratorio virtual que ejecuta seis motores sobre el mismo snapshot LIVE."""

    INITIAL_LIVES = Decimal("100")
    MAX_STAKE = Decimal("10")
    MIN_STAKE = Decimal("1")
    MOTORS = ("V1", "V11", "V12", "V2", "V21", "V22")
    LABELS = {"V1": "V1", "V11": "V1.1", "V12": "V1.2", "V2": "V2", "V21": "V2.1", "V22": "V2.2"}
    OPPORTUNITY_ATTRS = {
        "V1": "opportunities", "V11": "opportunities_v11", "V12": "opportunities_v12",
        "V2": "opportunities_v2", "V21": "opportunities_v21", "V22": "opportunities_v22",
    }

    LEVEL_RANGES = {
        1: (Decimal("8"), Decimal("10")),
        2: (Decimal("5"), Decimal("7")),
        3: (Decimal("1"), Decimal("4")),
    }

    @classmethod
    @transaction.atomic
    def start(cls, match):
        existing = LiveExperiment.objects.filter(
            ecuabet_event_id=match.ecuabet_event_id, status="RUNNING"
        ).first()
        if existing:
            return existing
        return LiveExperiment.objects.create(
            ecuabet_event_id=match.ecuabet_event_id,
            flashscore_event_id=match.flashscore_event_id or "",
            home_team=match.home_team,
            away_team=match.away_team,
            initial_lives=cls.INITIAL_LIVES,
            v1_lives=cls.INITIAL_LIVES,
            v2_lives=cls.INITIAL_LIVES,
            v1_max_lives=cls.INITIAL_LIVES,
            v2_max_lives=cls.INITIAL_LIVES,
            v1_min_lives=cls.INITIAL_LIVES,
            v2_min_lives=cls.INITIAL_LIVES,
            status="RUNNING",
        )

    @classmethod
    def _prepare_opportunities(cls, motor: str, opportunities):
        """Añade metadatos de nivel solo en la capa del laboratorio.

        V1 y V2 permanecen como motores base originales. Los niveles usados
        para stake/prioridad son una capa externa y no forman parte de sus
        algoritmos de predicción.
        """
        if motor not in {"V1", "V11", "V2", "V12", "V21", "V22"}:
            return list(opportunities or [])
        # V2.2 calcula el nivel al filtrar, pero no lo adjunta al objeto
        # devuelto. El laboratorio necesita ese nivel para validar y apostar.
        return [enrich(dict(opportunity)) for opportunity in (opportunities or [])]

    @classmethod
    def _motor_limit(cls, motor: str) -> int:
        return 2 if motor in {"V12", "V22"} else 999999

    @classmethod
    def _current_bets(cls, experiment, motor: str) -> int:
        return experiment.entries.filter(motor=motor).count()

    @classmethod
    def _exposure(cls, experiment, motor: str) -> Decimal:
        return sum(
            (Decimal(str(x.stake)) for x in experiment.entries.filter(motor=motor)),
            Decimal("0"),
        )

    @classmethod
    def _eligibility_reason(cls, experiment, motor: str, opportunity: Dict[str, Any]) -> str:
        key = cls._key(opportunity)
        if not key:
            return "Descartada: oportunidad sin mercado/selección/línea válidos."
        if cls._current_bets(experiment, motor) >= cls._motor_limit(motor):
            return "Descartada: este motor ya alcanzó el máximo de 2 apuestas por partido."
        price = Decimal(str(opportunity.get("price") or 0))
        level = cls._level(opportunity)
        if level == 0:
            model_p = float(opportunity.get("model_probability") or 0)
            implied = float(opportunity.get("implied_probability") or 0)
            edge = float(opportunity.get("edge") or 0)
            confidence = float(opportunity.get("confidence") or 0)
            signal = str(opportunity.get("signal_strength") or opportunity.get("signal") or "no determinada")
            coverage = opportunity.get("data_coverage")
            coverage_text = f"{float(coverage) * 100:.0f}%" if coverage is not None else "no disponible"
            return (
                f"Descartada {cls.LABELS.get(motor, motor)}: no alcanzó un nivel apostable. "
                f"Probabilidad {model_p * 100:.1f}% vs {implied * 100:.1f}% implícita, "
                f"edge {edge * 100:+.1f} puntos, confianza {confidence * 100:.1f}%, "
                f"señal {signal}, cobertura {coverage_text}. No justifica gastar vidas."
            )
        if motor == "V12":
            if price < Decimal("1.50"):
                return "Descartada V1.2: cuota inferior a 1.50."
            if level not in {1, 2}:
                return "Descartada V1.2: solo permite seguridad alta o media."
        if motor == "V22":
            # V2.2 tiene reglas propias: no se le imponen los filtros de V1.2.
            # Busca valor suficiente y una señal razonablemente respaldada.
            if price < Decimal("1.30"):
                return "Descartada V2.2: cuota inferior a 1.30."
            if float(opportunity.get("edge") or 0) < 0.04:
                return "Descartada V2.2: edge inferior al 4%."
            if float(opportunity.get("confidence") or 0) < 0.52:
                return "Descartada V2.2: confianza inferior al 52%."
            consensus = float(opportunity.get("consensus_score") or 0)
            if consensus < 0.30:
                return "Descartada V2.2: respaldo de indicadores inferior al 30%."
        if LiveExperimentEntry.objects.filter(
            experiment=experiment, motor=motor, opportunity_key=key
        ).exists():
            return "Repetida: el motor ya tomó esta misma oportunidad/mercado."
        return ""

    @classmethod
    def _level(cls, opportunity: Dict[str, Any]) -> int:
        try:
            value = int(opportunity.get("level"))
        except (TypeError, ValueError):
            return 0
        return value if value in cls.LEVEL_RANGES else 0

    @classmethod
    def _ledger_lives(cls, experiment, motor: str) -> Decimal:
        """
        Capital disponible GLOBAL del motor durante el experimento del día.

        Las 100 vidas son un único bankroll por motor, compartido entre todos
        los partidos analizados. Una apuesta OPEN mantiene su stake comprometido;
        una LOST consume el stake y una WON aporta su P/L. CANCELLED no altera
        el capital.
        """
        today = timezone.localdate()
        entries = LiveExperimentEntry.objects.filter(
            experiment__started_at__date=today,
            motor=motor,
        ).order_by("placed_at", "id")

        lives = Decimal(str(cls.INITIAL_LIVES))
        for entry in entries:
            if entry.status in {"OPEN", "LOST"}:
                lives -= Decimal(str(entry.stake))
            elif entry.status == "WON":
                lives += Decimal(str(entry.pnl))
        # Nunca permitimos que el bankroll utilizable quede por debajo de cero.
        return max(Decimal("0"), lives)

    @classmethod
    def _stake(cls, opportunity: Dict[str, Any], lives: Decimal) -> Decimal:
        level = cls._level(opportunity)
        if level == 0 or lives < cls.MIN_STAKE:
            return Decimal("0")
        confidence = Decimal(str(opportunity.get("confidence") or 0))
        edge = Decimal(str(opportunity.get("edge") or 0))
        low, high = cls.LEVEL_RANGES[level]
        strength = min(Decimal("1"), max(Decimal("0"), confidence + min(edge * 4, Decimal("0.25"))))
        return min(cls.MAX_STAKE, lives, low + (high - low) * strength).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    @staticmethod
    def _key(opportunity: Dict[str, Any]) -> str:
        return "|".join(str(opportunity.get(k) or "").strip().lower() for k in ("market", "selection", "line"))

    @staticmethod
    def _level_name(level: int) -> str:
        return {
            1: "Muy fuerte",
            2: "Fuerte",
            3: "Moderada",
            0: "Descartada · Sin nivel",
        }.get(level, "Descartada · Sin nivel")

    @classmethod
    def _audit_reason(cls, experiment, motor: str, opportunity: Dict[str, Any], *, selected: bool = False, stake: Decimal = Decimal("0")) -> str:
        """Construye una justificación auditable de selección o descarte.

        El texto se apoya en los mismos valores que vio el motor: probabilidad,
        cuota, edge, confianza, nivel, contexto LIVE y filtros específicos.
        No modifica la lógica de V1/V2; solo explica la decisión del laboratorio.
        """
        market = str(opportunity.get("market") or "mercado").strip()
        selection = str(opportunity.get("selection") or "selección").strip()
        line = str(opportunity.get("line") or "").strip()
        price = float(opportunity.get("price") or 0)
        model_p = float(opportunity.get("model_probability") or 0)
        implied = float(opportunity.get("implied_probability") or 0)
        edge = float(opportunity.get("edge") or 0)
        confidence = float(opportunity.get("confidence") or 0)
        level = cls._level(opportunity)
        minute = str(getattr(opportunity, "minute", "") or "")
        # El minuto/marcador se incorporan desde el snapshot LIVE en process().
        live_minute = str(getattr(experiment, "last_minute", "") or "")
        home_score = getattr(experiment, "last_home_score", None)
        away_score = getattr(experiment, "last_away_score", None)
        score = (
            f"{home_score}-{away_score}"
            if home_score is not None and away_score is not None
            else "marcador no disponible"
        )
        minute_text = live_minute or minute or "minuto no disponible"
        label = cls.LABELS.get(motor, motor)

        if not selected:
            rejection = cls._eligibility_reason(experiment, motor, opportunity)
            if rejection:
                return rejection
            if level == 0:
                return (
                    f"Descartada {label}: la señal no alcanzó un nivel de seguridad válido "
                    f"(probabilidad {model_p * 100:.1f}%, edge {edge * 100:.1f} puntos, "
                    f"confianza {confidence * 100:.1f}%)."
                )
            if motor == "V22":
                consensus = float(opportunity.get("consensus_score") or 0)
                if consensus < 0.30:
                    return (
                        f"Descartada {label}: respaldo de indicadores insuficiente "
                        f"({consensus * 100:.1f}%), pese a {edge * 100:.1f} puntos de edge."
                    )
            return (
                f"No seleccionada {label}: alcanzó Nivel {level}, pero otra oportunidad "
                f"tuvo mayor prioridad para proteger las vidas disponibles."
            )

        probability_text = f"{model_p * 100:.1f}%"
        implied_text = f"{implied * 100:.1f}%"
        edge_text = f"{edge * 100:+.1f} puntos"
        line_text = f" {line}" if line else ""
        level_name = cls._level_name(level)
        base = (
            f"{selection}{line_text} elegido por {label}: {probability_text} de probabilidad "
            f"frente a {implied_text} implícita ({edge_text} de edge); "
            f"{score} al {minute_text}, Nivel {level} · {level_name}"
        )

        if motor == "V11":
            calibration = opportunity.get("calibration")
            temporal = opportunity.get("temporal_factor")
            if calibration:
                base += f"; calibración hacia 50%"
            if temporal is not None:
                base += f" y factor temporal {float(temporal):.2f}"
        elif motor == "V12":
            base += "; mercado LIVE compatible con la evaluación ampliada de V1.2"
        elif motor == "V21":
            temporal = opportunity.get("temporal_factor")
            if temporal is not None:
                base += f"; control temporal {float(temporal):.2f}"
        elif motor == "V22":
            consensus = float(opportunity.get("consensus_score") or 0)
            base += f"; consenso de indicadores {consensus * 100:.1f}%"

        if confidence:
            base += f"; confianza {confidence * 100:.1f}%"
        if stake:
            base += f"; exposición {stake:.2f} vidas"

        supporting = opportunity.get("supporting_factors") or []
        contradicting = opportunity.get("contradicting_factors") or []
        if supporting:
            base += f"; respaldo: {', '.join(map(str, supporting[:3]))}"
        if contradicting:
            base += f"; cautelas: {', '.join(map(str, contradicting[:2]))}"

        return base + "."

    @classmethod
    def _eligible(cls, experiment, motor, opportunity):
        return not cls._eligibility_reason(experiment, motor, opportunity)

    @classmethod
    def _choose(cls, experiment, motor, opportunities):
        lives = cls._ledger_lives(experiment, motor)
        candidates = [o for o in opportunities if cls._eligible(experiment, motor, o)]
        if not candidates or lives < cls.MIN_STAKE:
            return None, Decimal("0")

        if motor == "V22":
            candidates.sort(key=lambda o: (
                float(o.get("consensus_score") or 0),
                float(o.get("edge") or 0),
                float(o.get("confidence") or 0),
                cls._level(o),
            ), reverse=True)
        else:
            candidates.sort(key=lambda o: (
                cls._level(o), float(o.get("edge") or 0), float(o.get("confidence") or 0)
            ), reverse=True)

        selected = candidates[0]
        stake = cls._stake(selected, lives)

        if motor in {"V12", "V22"}:
            exposure_cap = Decimal("12") if motor == "V12" else Decimal("14")
            remaining_exposure = exposure_cap - cls._exposure(experiment, motor)
            stake = min(stake, remaining_exposure)

        return (selected, stake) if stake >= cls.MIN_STAKE else (None, Decimal("0"))

    @classmethod
    def _place(cls, experiment, motor, opportunity, stake, match):
        price = Decimal(str(opportunity.get("price") or 0))
        potential_profit = stake * max(price - Decimal("1"), Decimal("0"))
        entry = LiveExperimentEntry.objects.create(
            experiment=experiment,
            motor=motor,
            opportunity_key=cls._key(opportunity),
            market=opportunity.get("market", ""),
            selection=opportunity.get("selection", ""),
            line=str(opportunity.get("line") or ""),
            price=price,
            model_probability=float(opportunity.get("model_probability") or 0),
            implied_probability=float(opportunity.get("implied_probability") or 0),
            edge=float(opportunity.get("edge") or 0),
            level=cls._level(opportunity),
            level_name=cls._level_name(cls._level(opportunity)),
            stake=stake,
            potential_profit=potential_profit,
            reason=opportunity.get("reason", ""),
            supporting_factors=opportunity.get("supporting_factors") or [],
            contradicting_factors=opportunity.get("contradicting_factors") or [],
            opportunity_snapshot=opportunity,
            placed_minute=str(match.minute or ""),
            placed_home_score=match.home_score,
            placed_away_score=match.away_score,
        )
        return entry

    @classmethod
    def _market_result(cls, entry, home_score, away_score, experiment) -> Optional[bool]:
        selection = entry.selection.lower().strip()
        market = entry.market.lower().strip()
        line = entry.line.lower().strip()
        text = market + " " + selection
        if any(x in text for x in ("total", "over", "under", "más", "menos")):
            number_match = re.search(r"(\d+(?:[.,]\d+)?)", f"{line} {text}")
            if number_match:
                target = float(number_match.group(1).replace(",", "."))
                total = home_score + away_score
                if any(x in selection for x in ("over", "más", "mas", "+")): return total > target
                if any(x in selection for x in ("under", "menos", "-")): return total < target

        if any(x in text for x in ("sin empate", "draw no bet", "dnb", "empate no acción", "empate no accion")):
            if any(x in selection for x in ("1", "local", "home")):
                return home_score > away_score if home_score != away_score else None
            if any(x in selection for x in ("2", "visitante", "away")):
                return away_score > home_score if home_score != away_score else None
        if any(x in text for x in ("ambos", "btts", "both teams")):
            both = home_score > 0 and away_score > 0
            if any(x in selection for x in ("sí", "si", "yes")): return both
            if any(x in selection for x in ("no", "not")): return not both
        if "doble" in text or "double chance" in text:
            result = "1" if home_score > away_score else ("x" if home_score == away_score else "2")
            if "1x" in selection: return result in ("1", "x")
            if "12" in selection: return result in ("1", "2")
            if "x2" in selection: return result in ("x", "2")
        if "1x2" in text or "resultado" in text or "ganador" in text:
            home = str(experiment.home_team or "").lower().strip()
            away = str(experiment.away_team or "").lower().strip()
            if selection in ("1", "local", "home") or "local" in selection or (home and (selection == home or selection in home or home in selection)):
                return home_score > away_score
            if selection in ("x", "empate", "draw"): return home_score == away_score
            if selection in ("2", "visitante", "away") or "visitante" in selection or (away and (selection == away or selection in away or away in selection)):
                return away_score > home_score
        return None

    @staticmethod
    def _valid_final(match):
        if not getattr(match, "is_finished", False): return False
        try:
            return int(match.home_score) >= 0 and int(match.away_score) >= 0
        except (TypeError, ValueError):
            return False

    @classmethod
    def _settle(cls, experiment, match):
        if not cls._valid_final(match): return False
        final_home, final_away = int(match.home_score), int(match.away_score)
        for entry in experiment.entries.filter(status="OPEN"):
            won = cls._market_result(entry, final_home, final_away, experiment)
            if won is None:
                entry.status, entry.pnl = "CANCELLED", Decimal("0")
            elif won:
                entry.status, entry.pnl = "WON", entry.potential_profit
            else:
                entry.status, entry.pnl = "LOST", -entry.stake
            entry.settled_at = timezone.now()
            entry.save(update_fields=["status", "pnl", "settled_at"])
        experiment.final_home_score = final_home
        experiment.final_away_score = final_away
        experiment.status = "FINISHED"
        experiment.finished_at = timezone.now()
        return True

    @classmethod
    def _sync_legacy_fields(cls, experiment):
        for motor, field in (("V1", "v1_lives"), ("V2", "v2_lives")):
            lives = cls._ledger_lives(experiment, motor)
            setattr(experiment, field, lives)
            values = [Decimal(str(experiment.initial_lives))]
            for entry in experiment.entries.filter(motor=motor).order_by("placed_at", "id"):
                if entry.status == "OPEN": values.append(values[-1] - entry.stake)
                elif entry.status == "LOST": values.append(values[-1] - entry.stake)
                elif entry.status == "WON": values.append(values[-1] + entry.pnl)
            setattr(experiment, f"{motor.lower()}_min_lives", min(values))
            setattr(experiment, f"{motor.lower()}_max_lives", max(values))
            setattr(experiment, f"{motor.lower()}_wins", experiment.entries.filter(motor=motor, status="WON").count())
            setattr(experiment, f"{motor.lower()}_losses", experiment.entries.filter(motor=motor, status="LOST").count())

    @classmethod
    @transaction.atomic
    def process(cls, match):
        # El bankroll es diario y compartido entre todos los partidos.
        # Bloqueamos los experimentos LIVE del día en orden estable para que
        # dos ciclos simultáneos no puedan gastar las mismas vidas.
        today = timezone.localdate()
        daily_experiments = list(
            LiveExperiment.objects.select_for_update()
            .filter(started_at__date=today, status="RUNNING")
            .order_by("id")
        )
        experiment = next(
            (x for x in daily_experiments if x.ecuabet_event_id == match.ecuabet_event_id),
            None,
        )
        if not experiment:
            return None
        experiment.last_minute = str(match.minute or "")
        experiment.last_period = str(match.period or "")
        experiment.last_home_score = match.home_score
        experiment.last_away_score = match.away_score
        if match.flashscore_event_id: experiment.flashscore_event_id = match.flashscore_event_id

        # Si el feed ya confirmó el final, este snapshot solo sirve para
        # liquidar las abiertas. Nunca se debe crear una apuesta nueva en FINAL.
        match_is_final = cls._valid_final(match)

        for motor in cls.MOTORS:
            opportunities = [] if match_is_final else cls._prepare_opportunities(
                motor, getattr(match, cls.OPPORTUNITY_ATTRS[motor], []) or []
            )
            lives_before = cls._ledger_lives(experiment, motor)
            candidates = [o for o in opportunities if cls._eligible(experiment, motor, o)]
            if motor == "V22":
                candidates.sort(key=lambda o: (
                    float(o.get("consensus_score") or 0),
                    float(o.get("edge") or 0),
                    float(o.get("confidence") or 0),
                    cls._level(o),
                ), reverse=True)
            else:
                candidates.sort(key=lambda o: (
                    cls._level(o), float(o.get("edge") or 0), float(o.get("confidence") or 0)
                ), reverse=True)

            selected, stake = cls._choose(experiment, motor, opportunities)
            lives_after = lives_before

            # El motivo auditado se guarda también en la entrada real. Así una
            # apuesta perdida puede reconstruirse exactamente desde la razón que
            # justificó gastar las vidas.
            selected_for_entry = None
            if selected is not None:
                selected_for_entry = dict(selected)
                selected_for_entry["reason"] = cls._audit_reason(
                    experiment, motor, selected_for_entry, selected=True, stake=stake
                )
                selected_for_entry["_audit_status"] = "SELECCIONADA"
                selected_for_entry["_audit_reason"] = selected_for_entry["reason"]
                cls._place(experiment, motor, selected_for_entry, stake, match)
                lives_after = cls._ledger_lives(experiment, motor)

            selected_key = cls._key(selected_for_entry) if selected_for_entry else ""
            audit_opportunities = []
            for opportunity in opportunities:
                item = dict(opportunity)
                key = cls._key(opportunity)
                level = cls._level(opportunity)
                if selected_key and key == selected_key:
                    audit_status = "SELECCIONADA"
                    reason = cls._audit_reason(
                        experiment, motor, item, selected=True, stake=stake
                    )
                else:
                    reason = cls._audit_reason(
                        experiment, motor, item, selected=False
                    )
                    if reason.startswith("Repetida:"):
                        audit_status = "REPETIDA"
                    elif reason.startswith("No seleccionada"):
                        audit_status = "NO_SELECCIONADA"
                    else:
                        audit_status = "RECHAZADA"
                if level == 0 and audit_status == "SELECCIONADA":
                    audit_status = "RECHAZADA"
                item["_audit_status"] = audit_status
                item["_audit_reason"] = reason
                item["audit_status"] = audit_status
                item["audit_reason"] = reason
                item["bettable"] = bool(level in cls.LEVEL_RANGES and audit_status == "SELECCIONADA")
                item["level_label"] = (
                    "🟢 Nivel 1 · Muy fuerte" if level == 1 else
                    "🟡 Nivel 2 · Fuerte" if level == 2 else
                    "🟠 Nivel 3 · Moderada" if level == 3 else
                    "🔴 Descartada · Sin nivel"
                )
                audit_opportunities.append(item)

            LiveExperimentSnapshot.objects.create(
                experiment=experiment, motor=motor,
                minute=str(match.minute or ""), period=str(match.period or ""),
                home_score=match.home_score, away_score=match.away_score,
                lives_before=lives_before, lives_after=lives_after,
                selected_opportunity=selected, all_opportunities=audit_opportunities,
                decision_reason=(selected_for_entry or {}).get("reason", "No tomó oportunidad en esta actualización."),
            )

        cls._settle(experiment, match)
        cls._sync_legacy_fields(experiment)
        experiment.save()
        return cls.serialize(experiment)

    @classmethod
    @transaction.atomic
    def stop(cls, experiment_id):
        experiment = LiveExperiment.objects.select_for_update().get(id=experiment_id)
        if experiment.status == "RUNNING":
            experiment.status = "STOPPED"
            experiment.stopped_at = timezone.now()
            experiment.entries.filter(status="OPEN").update(status="CANCELLED", pnl=Decimal("0"), settled_at=timezone.now())
            cls._sync_legacy_fields(experiment)
            experiment.save()
        return cls.serialize(experiment)

    @classmethod
    @transaction.atomic
    def reconcile_finished(cls, experiment_id):
        experiment = LiveExperiment.objects.select_for_update().get(id=experiment_id)
        if experiment.status != "FINISHED" or experiment.final_home_score is None or experiment.final_away_score is None:
            return experiment
        final_home, final_away = int(experiment.final_home_score), int(experiment.final_away_score)
        for motor in cls.MOTORS:
            current = cls.INITIAL_LIVES
            entries = list(experiment.entries.filter(motor=motor).order_by("placed_at", "id"))
            for entry in entries:
                if entry.status == "CANCELLED":
                    entry.pnl = Decimal("0")
                    entry.save(update_fields=["pnl"])
                    continue
                result = cls._market_result(entry, final_home, final_away, experiment)
                if result is None:
                    entry.status, entry.pnl = "CANCELLED", Decimal("0")
                elif result:
                    entry.status, entry.pnl = "WON", entry.potential_profit
                    current += entry.pnl
                else:
                    entry.status, entry.pnl = "LOST", -entry.stake
                    current -= entry.stake
                entry.settled_at = entry.settled_at or timezone.now()
                entry.save(update_fields=["status", "pnl", "settled_at"])
            
        cls._sync_legacy_fields(experiment)
        experiment.save()
        return experiment

    @classmethod
    @transaction.atomic
    def save_daily_archive(cls, experiment_date=None):
        """Congela todos los experimentos y snapshots del día indicado."""
        target_date = experiment_date or timezone.localdate()
        experiments = list(
            LiveExperiment.objects.filter(started_at__date=target_date).order_by("started_at")
        )
        serialized_experiments = []
        for experiment in experiments:
            data = cls.serialize(experiment)
            data["snapshots"] = [
                {
                    "id": snapshot.id,
                    "motor": snapshot.motor,
                    "minute": snapshot.minute,
                    "period": snapshot.period,
                    "home_score": snapshot.home_score,
                    "away_score": snapshot.away_score,
                    "lives_before": float(snapshot.lives_before),
                    "lives_after": float(snapshot.lives_after),
                    "selected_opportunity": snapshot.selected_opportunity,
                    "all_opportunities": snapshot.all_opportunities,
                    "decision_reason": snapshot.decision_reason,
                    "created_at": snapshot.created_at.isoformat(),
                }
                for snapshot in experiment.snapshots.all().order_by("created_at", "id")
            ]
            serialized_experiments.append(data)

        motors_summary = {}
        for motor in cls.MOTORS:
            aggregate = {
                "label": cls.LABELS[motor],
                "decisions": 0, "wins": 0, "losses": 0, "open": 0, "cancelled": 0,
                "total_staked": 0.0, "total_pnl": 0.0, "current_lives": 100.0,
            }
            for experiment in serialized_experiments:
                item = experiment["motors"].get(motor, {})
                for key in ("decisions", "wins", "losses", "open", "cancelled"):
                    aggregate[key] += int(item.get(key, 0) or 0)
                for key in ("total_staked", "total_pnl"):
                    aggregate[key] += float(item.get(key, 0) or 0)
            aggregate["current_lives"] = 100.0 + aggregate["total_pnl"]
            settled = aggregate["wins"] + aggregate["losses"]
            aggregate["hit_rate"] = (aggregate["wins"] / settled * 100) if settled else 0.0
            aggregate["roi"] = (aggregate["total_pnl"] / aggregate["total_staked"] * 100) if aggregate["total_staked"] else 0.0
            motors_summary[motor] = aggregate

        archive, _ = LiveExperimentDailyArchive.objects.update_or_create(
            experiment_date=target_date,
            defaults={
                "experiment_count": len(serialized_experiments),
                "decision_count": sum(len(x.get("entries", [])) for x in serialized_experiments),
                "motors_summary": motors_summary,
                "experiments_data": serialized_experiments,
            },
        )
        return archive

    @classmethod
    def serialize(cls, experiment):
        entries = []
        motors = {}
        for motor in cls.MOTORS:
            motor_entries = list(experiment.entries.filter(motor=motor).order_by("-placed_at"))
            total_pnl = sum((Decimal(str(e.pnl)) for e in motor_entries), Decimal("0"))
            total_staked = sum((Decimal(str(e.stake)) for e in motor_entries), Decimal("0"))
            best = max(motor_entries, key=lambda e: (e.level, e.model_probability, e.edge), default=None)
            # Reconstruct equity curve from 100 so all six motors are measured identically.
            curve = [cls.INITIAL_LIVES]
            for e in sorted(motor_entries, key=lambda x: (x.placed_at, x.id)):
                if e.status == "OPEN" or e.status == "LOST": curve.append(curve[-1] - e.stake)
                elif e.status == "WON": curve.append(curve[-1] + e.pnl)
            current = cls._ledger_lives(experiment, motor)
            open_staked = sum(
                (Decimal(str(e.stake)) for e in motor_entries if e.status == "OPEN"),
                Decimal("0"),
            )
            total_capital = max(
                Decimal("0"),
                Decimal(str(cls.INITIAL_LIVES)) + total_pnl,
            )
            available_lives = max(Decimal("0"), total_capital - open_staked)
            motors[motor] = {
                "label": cls.LABELS[motor],
                "decisions": len(motor_entries),
                "wins": sum(1 for e in motor_entries if e.status == "WON"),
                "losses": sum(1 for e in motor_entries if e.status == "LOST"),
                "open": sum(1 for e in motor_entries if e.status == "OPEN"),
                "cancelled": sum(1 for e in motor_entries if e.status == "CANCELLED"),
                "total_staked": float(total_staked),
                "total_pnl": float(total_pnl),
                "open_staked": float(open_staked),
                "total_capital": float(total_capital),
                "available_lives": float(available_lives),
                "current_lives": float(max(Decimal("0"), current)),
                "alive": bool(current >= cls.MIN_STAKE),
                "max_lives": float(max(curve)),
                "min_lives": float(min(curve)),
                "roi": float((total_pnl / total_staked) * 100) if total_staked else 0.0,
                "hit_rate": float((sum(1 for e in motor_entries if e.status == "WON") / max(1, sum(1 for e in motor_entries if e.status in {"WON", "LOST"}))) * 100),
                "best_level": best.level if best else 0,
                "best_probability": float(best.model_probability) if best else 0,
                "best_selection": best.selection if best else "",
            }

        for e in experiment.entries.all().order_by("-placed_at"):
            entries.append({
                "id": e.id, "motor": e.motor, "motor_label": cls.LABELS.get(e.motor, e.motor),
                "match": f"{experiment.home_team} vs {experiment.away_team}",
                "market": e.market, "selection": e.selection, "line": e.line,
                "price": float(e.price), "model_probability": e.model_probability,
                "implied_probability": e.implied_probability, "edge_pct": round(e.edge * 100, 2),
                "level": e.level, "level_name": e.level_name, "stake": float(e.stake),
                "potential_profit": float(e.potential_profit), "status": e.status, "pnl": float(e.pnl),
                "reason": e.reason, "supporting_factors": e.supporting_factors,
                "contradicting_factors": e.contradicting_factors,
                "placed_minute": e.placed_minute, "placed_home_score": e.placed_home_score,
                "placed_away_score": e.placed_away_score,
                "current_minute": experiment.last_minute,
                "current_home_score": experiment.last_home_score,
                "current_away_score": experiment.last_away_score,
                "placed_at": e.placed_at.isoformat(),
                "settled_at": e.settled_at.isoformat() if e.settled_at else None,
            })

        ranked = [(data["current_lives"], data["hit_rate"], motor) for motor, data in motors.items() if data["decisions"]]
        safest_motor = max(ranked, default=(0, 0, None))[2]
        return {
            "id": experiment.id, "status": experiment.status,
            "ecuabet_event_id": experiment.ecuabet_event_id, "flashscore_event_id": experiment.flashscore_event_id,
            "home_team": experiment.home_team, "away_team": experiment.away_team,
            "match": f"{experiment.home_team} vs {experiment.away_team}",
            "initial_lives": float(experiment.initial_lives),
            "v1_lives": motors["V1"]["current_lives"], "v2_lives": motors["V2"]["current_lives"],
            "v1_max_lives": motors["V1"]["max_lives"], "v2_max_lives": motors["V2"]["max_lives"],
            "v1_min_lives": motors["V1"]["min_lives"], "v2_min_lives": motors["V2"]["min_lives"],
            "v1_wins": motors["V1"]["wins"], "v1_losses": motors["V1"]["losses"],
            "v2_wins": motors["V2"]["wins"], "v2_losses": motors["V2"]["losses"],
            "last_minute": experiment.last_minute, "last_period": experiment.last_period,
            "last_home_score": experiment.last_home_score, "last_away_score": experiment.last_away_score,
            "final_home_score": experiment.final_home_score, "final_away_score": experiment.final_away_score,
            "started_at": experiment.started_at.isoformat(),
            "stopped_at": experiment.stopped_at.isoformat() if experiment.stopped_at else None,
            "finished_at": experiment.finished_at.isoformat() if experiment.finished_at else None,
            "motors": motors, "safest_motor": safest_motor, "entries": entries,
            "snapshots": [
                {
                    "id": snapshot.id,
                    "motor": snapshot.motor,
                    "minute": snapshot.minute,
                    "period": snapshot.period,
                    "home_score": snapshot.home_score,
                    "away_score": snapshot.away_score,
                    "lives_before": float(snapshot.lives_before),
                    "lives_after": float(snapshot.lives_after),
                    "selected_opportunity": snapshot.selected_opportunity,
                    "all_opportunities": snapshot.all_opportunities,
                    "decision_reason": snapshot.decision_reason,
                    "created_at": snapshot.created_at.isoformat(),
                }
                for snapshot in experiment.snapshots.all().order_by("created_at", "id")
            ],
        }
