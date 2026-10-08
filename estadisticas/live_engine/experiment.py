from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional

from django.db import transaction
from django.utils import timezone

from ..models import LiveExperiment, LiveExperimentEntry, LiveExperimentSnapshot


class LiveExperimentManager:
    """Laboratorio virtual que ejecuta V1, V1.1, V2 y V2.2 sobre el mismo snapshot."""

    INITIAL_LIVES = Decimal("100")
    MAX_STAKE = Decimal("10")
    MIN_STAKE = Decimal("1")
    MOTORS = ("V1", "V11", "V2", "V22")
    LABELS = {"V1": "V1", "V11": "V1.1", "V2": "V2", "V22": "V2.2"}
    OPPORTUNITY_ATTRS = {
        "V1": "opportunities", "V11": "opportunities_v11",
        "V2": "opportunities_v2", "V22": "opportunities_v22",
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
    def _level(cls, opportunity: Dict[str, Any]) -> int:
        try:
            value = int(opportunity.get("level"))
        except (TypeError, ValueError):
            return 0
        return value if value in cls.LEVEL_RANGES else 0

    @classmethod
    def _ledger_lives(cls, experiment, motor: str) -> Decimal:
        lives = Decimal(str(experiment.initial_lives))
        for entry in experiment.entries.filter(motor=motor).order_by("placed_at", "id"):
            if entry.status == "OPEN":
                lives -= Decimal(str(entry.stake))
            elif entry.status == "LOST":
                lives -= Decimal(str(entry.stake))
            elif entry.status == "WON":
                lives += Decimal(str(entry.pnl))
        return lives

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
        return {1: "Muy fuerte", 2: "Fuerte", 3: "Moderada"}.get(level, "Sin nivel")

    @classmethod
    def _eligible(cls, experiment, motor, opportunity):
        level = cls._level(opportunity)
        key = cls._key(opportunity)
        if not level or not key:
            return False
        return not LiveExperimentEntry.objects.filter(
            experiment=experiment, motor=motor, opportunity_key=key
        ).exists()

    @classmethod
    def _choose(cls, experiment, motor, opportunities):
        lives = cls._ledger_lives(experiment, motor)
        candidates = [o for o in opportunities if cls._eligible(experiment, motor, o)]
        if not candidates or lives < cls.MIN_STAKE:
            return None, Decimal("0")
        candidates.sort(key=lambda o: (
            cls._level(o), float(o.get("edge") or 0), float(o.get("confidence") or 0)
        ), reverse=True)
        selected = candidates[0]
        stake = cls._stake(selected, lives)
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
        if any(x in text for x in ("total", "over", "under", "más", "menos")) and ("2.5" in line or "2.5" in text):
            total = home_score + away_score
            if any(x in selection for x in ("over", "más", "mas", "+")): return total >= 3
            if any(x in selection for x in ("under", "menos", "-")): return total <= 2
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
        experiment = LiveExperiment.objects.select_for_update().filter(
            ecuabet_event_id=match.ecuabet_event_id, status="RUNNING"
        ).first()
        if not experiment: return None
        experiment.last_minute = str(match.minute or "")
        experiment.last_period = str(match.period or "")
        experiment.last_home_score = match.home_score
        experiment.last_away_score = match.away_score
        if match.flashscore_event_id: experiment.flashscore_event_id = match.flashscore_event_id

        for motor in cls.MOTORS:
            opportunities = list(getattr(match, cls.OPPORTUNITY_ATTRS[motor], []) or [])
            selected, stake = cls._choose(experiment, motor, opportunities)
            lives_before = cls._ledger_lives(experiment, motor)
            lives_after = lives_before
            if selected is not None:
                entry = cls._place(experiment, motor, selected, stake, match)
                lives_after = cls._ledger_lives(experiment, motor)
            LiveExperimentSnapshot.objects.create(
                experiment=experiment, motor=motor,
                minute=str(match.minute or ""), period=str(match.period or ""),
                home_score=match.home_score, away_score=match.away_score,
                lives_before=lives_before, lives_after=lives_after,
                selected_opportunity=selected, all_opportunities=opportunities,
                decision_reason=(selected or {}).get("reason", "No tomó oportunidad en esta actualización."),
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
    def serialize(cls, experiment):
        entries = []
        motors = {}
        for motor in cls.MOTORS:
            motor_entries = list(experiment.entries.filter(motor=motor).order_by("-placed_at"))
            total_pnl = sum((Decimal(str(e.pnl)) for e in motor_entries), Decimal("0"))
            total_staked = sum((Decimal(str(e.stake)) for e in motor_entries), Decimal("0"))
            best = max(motor_entries, key=lambda e: (e.level, e.model_probability, e.edge), default=None)
            # Reconstruct equity curve from 100 so all four motors are measured identically.
            curve = [cls.INITIAL_LIVES]
            for e in sorted(motor_entries, key=lambda x: (x.placed_at, x.id)):
                if e.status == "OPEN" or e.status == "LOST": curve.append(curve[-1] - e.stake)
                elif e.status == "WON": curve.append(curve[-1] + e.pnl)
            current = curve[-1]
            motors[motor] = {
                "label": cls.LABELS[motor],
                "decisions": len(motor_entries),
                "wins": sum(1 for e in motor_entries if e.status == "WON"),
                "losses": sum(1 for e in motor_entries if e.status == "LOST"),
                "open": sum(1 for e in motor_entries if e.status == "OPEN"),
                "cancelled": sum(1 for e in motor_entries if e.status == "CANCELLED"),
                "total_staked": float(total_staked),
                "total_pnl": float(total_pnl),
                "current_lives": float(current),
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
                "placed_away_score": e.placed_away_score, "placed_at": e.placed_at.isoformat(),
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
        }
