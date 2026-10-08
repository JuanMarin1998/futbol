from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional

from django.db import transaction
from django.utils import timezone

from ..models import LiveExperiment, LiveExperimentEntry, LiveExperimentSnapshot


class LiveExperimentManager:
    """
    Simulador de 100 vidas para comparar V1 y V2.
    Es puramente virtual: no ejecuta apuestas ni interactúa con Ecuabet.
    """

    INITIAL_LIVES = Decimal("100")
    MAX_STAKE = Decimal("10")
    MIN_STAKE = Decimal("1")

    LEVEL_RANGES = {
        1: (Decimal("8"), Decimal("10")),
        2: (Decimal("5"), Decimal("7")),
        3: (Decimal("1"), Decimal("4")),
    }

    @classmethod
    @transaction.atomic
    def start(cls, match):
        existing = (
            LiveExperiment.objects
            .filter(ecuabet_event_id=match.ecuabet_event_id, status="RUNNING")
            .first()
        )
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
        value = opportunity.get("level")
        try:
            value = int(value)
        except (TypeError, ValueError):
            return 0
        return value if value in cls.LEVEL_RANGES else 0

    @classmethod
    def _stake(cls, opportunity: Dict[str, Any], lives: Decimal) -> Decimal:
        level = cls._level(opportunity)
        if level == 0 or lives < cls.MIN_STAKE:
            return Decimal("0")

        confidence = Decimal(str(opportunity.get("confidence") or 0))
        edge = Decimal(str(opportunity.get("edge") or 0))
        low, high = cls.LEVEL_RANGES[level]

        # El motor no recibe una cantidad fija por nivel: ajusta el riesgo
        # dentro del rango según confianza + ventaja estadística.
        strength = min(Decimal("1"), max(Decimal("0"), (confidence + min(edge * 4, Decimal("0.25")))))
        stake = low + (high - low) * strength
        stake = min(cls.MAX_STAKE, stake)
        stake = min(stake, lives)
        return stake.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    @staticmethod
    def _key(opportunity: Dict[str, Any]) -> str:
        return "|".join(
            str(opportunity.get(k) or "").strip().lower()
            for k in ("market", "selection", "line")
        )

    @staticmethod
    def _level_name(level: int) -> str:
        return {
            1: "Muy fuerte",
            2: "Fuerte",
            3: "Moderada",
        }.get(level, "Sin nivel")

    @staticmethod
    def _is_final(match) -> bool:
        """Determina el final usando el estado normalizado y texto legacy."""
        if bool(getattr(match, "is_finished", False)):
            return True
        status = str(getattr(match, "match_status", "") or "").casefold()
        minute = str(match.minute or "").casefold()
        period = str(match.period or "").casefold()
        final_words = (
            "final", "finished", "full time", "match finished",
            "ft", "finalizado", "terminado", "after extra time",
            "after penalties",
        )
        return any(
            word in status or word in minute or word in period
            for word in final_words
        )

    @classmethod
    def _eligible_opportunity(cls, experiment, motor, opportunity):
        level = cls._level(opportunity)
        if not level:
            return False
        key = cls._key(opportunity)
        if not key:
            return False
        if LiveExperimentEntry.objects.filter(
            experiment=experiment,
            motor=motor,
            opportunity_key=key,
        ).exists():
            return False
        return True

    @classmethod
    def _choose(cls, experiment, motor: str, opportunities):
        lives = Decimal(str(getattr(experiment, f"{motor.lower()}_lives")))
        candidates = [
            o for o in opportunities
            if cls._eligible_opportunity(experiment, motor, o)
        ]
        if not candidates or lives < cls.MIN_STAKE:
            return None, Decimal("0")

        # Primero nivel, después edge, después confianza.
        candidates.sort(
            key=lambda o: (
                cls._level(o),
                float(o.get("edge") or 0),
                float(o.get("confidence") or 0),
            ),
            reverse=True,
        )
        selected = candidates[0]
        stake = cls._stake(selected, lives)
        if stake < cls.MIN_STAKE:
            return None, Decimal("0")
        return selected, stake

    @classmethod
    def _place(cls, experiment, motor, opportunity, stake, match):
        field = f"{motor.lower()}_lives"
        lives_before = Decimal(str(getattr(experiment, field)))
        price = Decimal(str(opportunity.get("price") or 0))
        potential_profit = stake * max(price - Decimal("1"), Decimal("0"))
        lives_after = lives_before - stake

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
        setattr(experiment, field, lives_after)
        setattr(experiment, f"{motor.lower()}_min_lives",
                min(Decimal(str(getattr(experiment, f"{motor.lower()}_min_lives"))), lives_after))
        setattr(experiment, f"{motor.lower()}_max_lives",
                max(Decimal(str(getattr(experiment, f"{motor.lower()}_max_lives"))), lives_after))
        return entry, lives_before, lives_after

    @classmethod
    def _market_result(cls, entry, home_score, away_score, experiment) -> Optional[bool]:
        selection = entry.selection.lower().strip()
        market = entry.market.lower().strip()
        line = entry.line.lower().strip()

        if any(x in market + " " + selection for x in ("total", "over", "under", "más", "menos")):
            if "2.5" in line or "2.5" in selection or "2.5" in market:
                total = home_score + away_score
                if any(x in selection for x in ("over", "más", "mas", "+")):
                    return total >= 3
                if any(x in selection for x in ("under", "menos", "-")):
                    return total <= 2

        if any(x in market + " " + selection for x in ("ambos", "btts", "both teams")):
            both = home_score > 0 and away_score > 0
            if any(x in selection for x in ("sí", "si", "yes")):
                return both
            if any(x in selection for x in ("no", "not")):
                return not both

        if "doble" in market or "double chance" in market:
            result = "1" if home_score > away_score else ("x" if home_score == away_score else "2")
            if "1x" in selection:
                return result in ("1", "x")
            if "12" in selection:
                return result in ("1", "2")
            if "x2" in selection:
                return result in ("x", "2")

        if "1x2" in market or "resultado" in market or "ganador" in market:
            home_name = str(experiment.home_team or "").lower().strip()
            away_name = str(experiment.away_team or "").lower().strip()
            if selection in ("1", "local", "home") or "local" in selection or (home_name and (selection == home_name or selection in home_name or home_name in selection)):
                return home_score > away_score
            if selection in ("x", "empate", "draw"):
                return home_score == away_score
            if selection in ("2", "visitante", "away") or "visitante" in selection or (away_name and (selection == away_name or selection in away_name or away_name in selection)):
                return away_score > home_score

        return None

    @classmethod
    def _settle(cls, experiment, match):
        if not cls._is_final(match):
            return

        for entry in experiment.entries.filter(status="OPEN"):
            won = cls._market_result(entry, int(match.home_score or 0), int(match.away_score or 0), experiment)
            if won is None:
                entry.status = "CANCELLED"
                entry.pnl = Decimal("0")
            elif won:
                entry.status = "WON"
                entry.pnl = entry.potential_profit
                field = f"{entry.motor.lower()}_lives"
                setattr(experiment, field, Decimal(str(getattr(experiment, field))) + entry.stake + entry.potential_profit)
                setattr(experiment, f"{entry.motor.lower()}_wins",
                        getattr(experiment, f"{entry.motor.lower()}_wins") + 1)
            else:
                entry.status = "LOST"
                entry.pnl = -entry.stake
                setattr(experiment, f"{entry.motor.lower()}_losses",
                        getattr(experiment, f"{entry.motor.lower()}_losses") + 1)
            entry.settled_at = timezone.now()
            entry.save(update_fields=["status", "pnl", "settled_at"])

        experiment.final_home_score = match.home_score
        experiment.final_away_score = match.away_score
        experiment.status = "FINISHED"
        experiment.finished_at = timezone.now()

    @classmethod
    @transaction.atomic
    def process(cls, match):
        experiment = (
            LiveExperiment.objects
            .select_for_update()
            .filter(ecuabet_event_id=match.ecuabet_event_id, status="RUNNING")
            .first()
        )
        if not experiment:
            return None

        experiment.last_minute = str(match.minute or "")
        experiment.last_period = str(match.period or "")
        experiment.last_home_score = match.home_score
        experiment.last_away_score = match.away_score
        if match.flashscore_event_id:
            experiment.flashscore_event_id = match.flashscore_event_id

        decisions = {"V1": None, "V2": None}

        for motor, opportunities in (
            ("V1", match.opportunities or []),
            ("V2", match.opportunities_v2 or []),
        ):
            selected, stake = cls._choose(experiment, motor, opportunities)
            lives_before = Decimal(str(getattr(experiment, f"{motor.lower()}_lives")))
            lives_after = lives_before
            if selected is not None:
                entry, lives_before, lives_after = cls._place(
                    experiment, motor, selected, stake, match
                )
                decisions[motor] = {
                    "entry_id": entry.id,
                    "selection": entry.selection,
                    "price": float(entry.price),
                    "stake": float(entry.stake),
                    "level": entry.level,
                    "level_name": entry.level_name,
                    "reason": entry.reason,
                }

            LiveExperimentSnapshot.objects.create(
                experiment=experiment,
                motor=motor,
                minute=str(match.minute or ""),
                period=str(match.period or ""),
                home_score=match.home_score,
                away_score=match.away_score,
                lives_before=lives_before,
                lives_after=lives_after,
                selected_opportunity=selected,
                all_opportunities=opportunities,
                decision_reason=(selected or {}).get("reason", "No tomó oportunidad en esta actualización."),
            )

        cls._settle(experiment, match)

        experiment.v1_max_lives = max(experiment.v1_max_lives, experiment.v1_lives)
        experiment.v2_max_lives = max(experiment.v2_max_lives, experiment.v2_lives)
        experiment.v1_min_lives = min(experiment.v1_min_lives, experiment.v1_lives)
        experiment.v2_min_lives = min(experiment.v2_min_lives, experiment.v2_lives)
        experiment.save()
        return cls.serialize(experiment)

    @classmethod
    @transaction.atomic
    def stop(cls, experiment_id):
        experiment = LiveExperiment.objects.select_for_update().get(id=experiment_id)
        if experiment.status == "RUNNING":
            experiment.status = "STOPPED"
            experiment.stopped_at = timezone.now()
            experiment.entries.filter(status="OPEN").update(
                status="CANCELLED",
                pnl=Decimal("0"),
                settled_at=timezone.now(),
            )
            experiment.save()
        return cls.serialize(experiment)

    @classmethod
    @transaction.atomic
    def reconcile_finished(cls, experiment_id):
        """Recalcula una liquidación final usando el marcador definitivo guardado.
        
        Sirve para corregir liquidaciones históricas si el primer snapshot final
        tenía un marcador desactualizado. Las vidas se reconstruyen desde 100
        respetando el orden en que se tomaron las decisiones.
        """
        experiment = (
            LiveExperiment.objects
            .select_for_update()
            .get(id=experiment_id)
        )
        if experiment.status != "FINISHED":
            return experiment
        if experiment.final_home_score is None or experiment.final_away_score is None:
            return experiment

        final_home = int(experiment.final_home_score)
        final_away = int(experiment.final_away_score)

        experiment.v1_lives = cls.INITIAL_LIVES
        experiment.v2_lives = cls.INITIAL_LIVES
        experiment.v1_wins = 0
        experiment.v1_losses = 0
        experiment.v2_wins = 0
        experiment.v2_losses = 0

        current_lives = {"V1": cls.INITIAL_LIVES, "V2": cls.INITIAL_LIVES}
        min_lives = {"V1": cls.INITIAL_LIVES, "V2": cls.INITIAL_LIVES}
        max_lives = {"V1": cls.INITIAL_LIVES, "V2": cls.INITIAL_LIVES}

        entries = list(experiment.entries.all().order_by("placed_at", "id"))
        for entry in entries:
            if entry.status == "CANCELLED":
                entry.pnl = Decimal("0")
                entry.save(update_fields=["pnl"])
                continue

            result = cls._market_result(entry, final_home, final_away, experiment)
            if result is None:
                entry.status = "CANCELLED"
                entry.pnl = Decimal("0")
            elif result:
                entry.status = "WON"
                entry.pnl = entry.potential_profit
                current_lives[entry.motor] += entry.stake + entry.potential_profit
                if entry.motor == "V1":
                    experiment.v1_wins += 1
                else:
                    experiment.v2_wins += 1
            else:
                entry.status = "LOST"
                entry.pnl = -entry.stake
                if entry.motor == "V1":
                    experiment.v1_losses += 1
                else:
                    experiment.v2_losses += 1

            if entry.status in {"WON", "LOST"}:
                # La apuesta ya fue descontada al momento de tomarla.
                # Reconstruimos desde 100 aplicando ese débito primero.
                if entry.status == "LOST":
                    current_lives[entry.motor] -= entry.stake
                elif entry.status == "WON":
                    current_lives[entry.motor] -= entry.stake
                    # y luego se suma stake + beneficio arriba.
                min_lives[entry.motor] = min(min_lives[entry.motor], current_lives[entry.motor])
                max_lives[entry.motor] = max(max_lives[entry.motor], current_lives[entry.motor])

            entry.settled_at = entry.settled_at or timezone.now()
            entry.save(update_fields=["status", "pnl", "settled_at"])

        experiment.v1_lives = current_lives["V1"]
        experiment.v2_lives = current_lives["V2"]
        experiment.v1_min_lives = min_lives["V1"]
        experiment.v2_min_lives = min_lives["V2"]
        experiment.v1_max_lives = max_lives["V1"]
        experiment.v2_max_lives = max_lives["V2"]
        experiment.save()
        return experiment

    @classmethod
    def serialize(cls, experiment):
        entries = []
        motors = {}
        for motor in ("V1", "V2"):
            motor_entries = list(experiment.entries.filter(motor=motor).order_by("-placed_at"))
            total_pnl = sum((Decimal(str(e.pnl)) for e in motor_entries), Decimal("0"))
            best = max(motor_entries, key=lambda e: (e.level, e.model_probability, e.edge), default=None)
            motors[motor] = {
                "decisions": len(motor_entries),
                "wins": sum(1 for e in motor_entries if e.status == "WON"),
                "losses": sum(1 for e in motor_entries if e.status == "LOST"),
                "open": sum(1 for e in motor_entries if e.status == "OPEN"),
                "cancelled": sum(1 for e in motor_entries if e.status == "CANCELLED"),
                "total_staked": float(sum((Decimal(str(e.stake)) for e in motor_entries), Decimal("0"))),
                "total_pnl": float(total_pnl),
                "best_level": best.level if best else 0,
                "best_probability": float(best.model_probability) if best else 0,
                "best_selection": best.selection if best else "",
            }

        for e in experiment.entries.all():
            entries.append({
                "id": e.id,
                "motor": e.motor,
                "match": f"{experiment.home_team} vs {experiment.away_team}",
                "market": e.market,
                "selection": e.selection,
                "line": e.line,
                "price": float(e.price),
                "model_probability": e.model_probability,
                "implied_probability": e.implied_probability,
                "edge_pct": round(e.edge * 100, 2),
                "level": e.level,
                "level_name": e.level_name,
                "stake": float(e.stake),
                "potential_profit": float(e.potential_profit),
                "status": e.status,
                "pnl": float(e.pnl),
                "reason": e.reason,
                "supporting_factors": e.supporting_factors,
                "contradicting_factors": e.contradicting_factors,
                "placed_minute": e.placed_minute,
                "placed_home_score": e.placed_home_score,
                "placed_away_score": e.placed_away_score,
                "placed_at": e.placed_at.isoformat(),
                "settled_at": e.settled_at.isoformat() if e.settled_at else None,
            })

        ranked = [
            (data["best_level"], data["best_probability"], data["total_pnl"], motor)
            for motor, data in motors.items() if data["decisions"]
        ]
        safest_motor = max(ranked, default=(0, 0, 0, None))[3]

        return {
            "id": experiment.id,
            "status": experiment.status,
            "ecuabet_event_id": experiment.ecuabet_event_id,
            "flashscore_event_id": experiment.flashscore_event_id,
            "home_team": experiment.home_team,
            "away_team": experiment.away_team,
            "match": f"{experiment.home_team} vs {experiment.away_team}",
            "initial_lives": float(experiment.initial_lives),
            "v1_lives": float(experiment.v1_lives),
            "v2_lives": float(experiment.v2_lives),
            "v1_max_lives": float(experiment.v1_max_lives),
            "v2_max_lives": float(experiment.v2_max_lives),
            "v1_min_lives": float(experiment.v1_min_lives),
            "v2_min_lives": float(experiment.v2_min_lives),
            "v1_wins": experiment.v1_wins,
            "v1_losses": experiment.v1_losses,
            "v2_wins": experiment.v2_wins,
            "v2_losses": experiment.v2_losses,
            "last_minute": experiment.last_minute,
            "last_period": experiment.last_period,
            "last_home_score": experiment.last_home_score,
            "last_away_score": experiment.last_away_score,
            "final_home_score": experiment.final_home_score,
            "final_away_score": experiment.final_away_score,
            "started_at": experiment.started_at.isoformat(),
            "stopped_at": experiment.stopped_at.isoformat() if experiment.stopped_at else None,
            "finished_at": experiment.finished_at.isoformat() if experiment.finished_at else None,
            "motors": motors,
            "safest_motor": safest_motor,
            "entries": entries,
        }
