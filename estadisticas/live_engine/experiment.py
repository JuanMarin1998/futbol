from decimal import Decimal, ROUND_DOWN
import math
import re
import unicodedata
from typing import Any, Dict, Optional

from django.db import transaction
from django.utils import timezone

from ..models import LiveExperiment, LiveExperimentEntry, LiveExperimentSnapshot, LiveExperimentDailyArchive
from .opportunity_levels import enrich


class LiveExperimentManager:
    """Laboratorio LIVE: siete motores visibles existentes más el Espía independiente."""

    INITIAL_LIVES = Decimal("100")
    INITIAL_LIVES_BY_MOTOR = {"ESP": Decimal("50")}
    MAX_STAKE = Decimal("10")
    MIN_STAKE = Decimal("1")
    MOTORS = ("V1", "V11", "V12", "V2", "V21", "V22", "V3", "V2U", "V11U", "V4", "ESP")
    # V1/V2/V3 quedan en pausa; su código e historial se conservan.
    PAUSED_MOTORS = frozenset({"V1", "V2", "V3"})
    LABELS = {"V1": "V1", "V11": "V1.1", "V12": "V1.2", "V2": "V2", "V21": "V2.1", "V22": "V2.2", "V3": "V3", "V2U": "V2.Ultra", "V11U": "V1.1 Ultra", "V4": "V4 · Calibración prudente", "ESP": "🕵️ Espía de Apuestas"}
    OPPORTUNITY_ATTRS = {
        "V1": "opportunities", "V11": "opportunities_v11", "V12": "opportunities_v12",
        "V2": "opportunities_v2", "V21": "opportunities_v21", "V22": "opportunities_v22",
        "V3": "opportunities_v3", "V2U": "opportunities_v2_ultra",
        "V11U": "opportunities_v11_ultra", "V4": "opportunities_v11", "ESP": "opportunities_v11",
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

    @staticmethod
    def _v4_market_selection_key(opportunity):
        """Familia y selección comparables; no mezcla empate con victoria ni goles."""
        key = LiveExperimentManager._key(opportunity).split("|")
        market = key[0] if key else ""
        selection = key[1] if len(key) > 1 else ""
        if market in {"resultado", "1x2", "ganador"}:
            family = "resultado"
        elif market in {"doble oportunidad"}:
            family = "doble_oportunidad"
        elif market in {"ambos marcan"}:
            family = "ambos_marcan"
        elif market in {"total goles"}:
            family = "total_goles"
        else:
            family = market
        line = key[2] if len(key) > 2 else ""
        # Las líneas de totales no son intercambiables (p. ej., 2.5 y 3.5).
        return family, selection, line if family == "total_goles" else ""

    @classmethod
    def _calibrate_v4_probability(cls, raw_probability: float, opportunity, market_probability: float):
        """Calibra solo con apuestas V1.1 liquidadas del mismo mercado y selección.

        Si no hay una muestra comparable suficiente, no finge precisión: aproxima
        la probabilidad al mercado y devuelve una muestra insuficiente, que V4
        rechazará en sus filtros de elegibilidad.
        """
        raw_probability = max(0.0, min(1.0, float(raw_probability)))
        market_probability = max(0.01, min(0.99, float(market_probability)))
        target_key = cls._v4_market_selection_key(opportunity)
        rows = LiveExperimentEntry.objects.filter(
            motor="V11", status__in=("WON", "LOST")
        ).order_by("-placed_at").values_list(
            "market", "selection", "model_probability", "status"
        )[:2000]
        matched = []
        for market, selection, probability, status in rows:
            if cls._v4_market_selection_key({"market": market, "selection": selection}) != target_key:
                continue
            try:
                probability = max(0.0, min(1.0, float(probability)))
            except (TypeError, ValueError):
                continue
            matched.append((probability, 1.0 if status == "WON" else 0.0))

        sample_size = len(matched)
        if sample_size >= 20:
            # Calibración empírica suavizada con prior de mercado, no con el
            # porcentaje bruto potencialmente inflado del propio modelo.
            prior_weight = 20.0
            observed_rate = sum(result for _, result in matched) / sample_size
            calibrated = (
                sample_size * observed_rate + prior_weight * market_probability
            ) / (sample_size + prior_weight)
            method = "mercado_seleccion_especifica_suavizado"
        else:
            # Sin evidencia comparable suficiente, no se declara edge real.
            calibrated = 0.5 * raw_probability + 0.5 * market_probability
            method = "provisional_retraida_al_mercado_muestra_insuficiente"
        return round(max(0.02, min(0.98, calibrated)), 6), sample_size, method

    @staticmethod
    def _v4_minute(match):
        """Extrae el minuto de feeds como 86', 90+2 o 45+1."""
        raw = str(getattr(match, "minute", "") or "").strip()
        found = re.search(r"(\d{1,3})(?:\s*\+\s*(\d{1,2}))?", raw)
        if not found:
            return None
        minute = int(found.group(1))
        added = int(found.group(2) or 0)
        return min(130, minute + added)

    @staticmethod
    def _v4_is_draw(opportunity):
        key = LiveExperimentManager._v4_market_selection_key(opportunity)
        return key[0] == "resultado" and key[1] == "x"

    @classmethod
    def _v4_live_context_reason(cls, opportunity, match):
        """Evita señales de empate que contradicen un marcador tardío."""
        if not cls._v4_is_draw(opportunity):
            return ""
        try:
            home_score = int(match.home_score)
            away_score = int(match.away_score)
        except (TypeError, ValueError):
            return "V4 descarta el empate: marcador LIVE no verificable."
        minute = cls._v4_minute(match)
        if minute is not None and minute >= 75 and home_score != away_score:
            return (
                f"V4 descarta el empate: al minuto {minute}, el marcador "
                f"{home_score}-{away_score} no está igualado; la señal contradice "
                "el estado actual del partido."
            )
        if minute is not None and minute >= 60 and abs(home_score - away_score) >= 2:
            return (
                f"V4 descarta el empate: diferencia de {abs(home_score - away_score)} "
                f"goles al minuto {minute}; riesgo tardío demasiado alto."
            )
        return ""

    @classmethod
    def _prepare_opportunities(cls, motor: str, opportunities, match=None):
        """Añade metadatos de nivel solo en la capa del laboratorio.

        V1 y V2 permanecen como motores base originales. Los niveles usados
        para stake/prioridad son una capa externa y no forman parte de sus
        algoritmos de predicción.
        """
        prepared = []
        for source in opportunities or []:
            opportunity = dict(source)
            try:
                price = float(str(opportunity.get("price") or 0).replace(",", "."))
                model_probability = float(opportunity.get("model_probability") or 0)
            except (TypeError, ValueError):
                continue

            if motor == "V4":
                raw_probability = model_probability
                if price <= 1:
                    continue
                implied_for_calibration = 1.0 / price
                market_probability = opportunity.get("market_fair_probability")
                try:
                    market_probability = float(market_probability) if market_probability is not None else implied_for_calibration
                except (TypeError, ValueError):
                    market_probability = implied_for_calibration
                if not 0 < market_probability < 1:
                    market_probability = implied_for_calibration
                model_probability, calibration_n, calibration_method = cls._calibrate_v4_probability(
                    raw_probability, opportunity, market_probability
                )
                opportunity["raw_model_probability"] = round(raw_probability, 6)
                opportunity["model_probability"] = model_probability
                opportunity["calibration_sample_size"] = calibration_n
                opportunity["calibration_method"] = calibration_method
                opportunity["calibration_adjustment"] = round(model_probability - raw_probability, 6)
                opportunity["v4_market_probability_used"] = round(market_probability, 6)
                if match is not None:
                    context_reason = cls._v4_live_context_reason(opportunity, match)
                    if context_reason:
                        opportunity["v4_context_rejection"] = context_reason

            # Si el motor no ofrece cuotas completas para una probabilidad justa,
            # se usa la probabilidad implícita y se deja registrada esa limitación.
            if motor != "V3":
                if price <= 1 or not 0 <= model_probability <= 1:
                    continue
                implied = 1.0 / price
                market_probability = implied
                edge_basis = "probabilidad_implícita_de_cuota"
                if motor == "V4" and opportunity.get("market_fair_probability") is not None:
                    try:
                        candidate_fair = float(opportunity["market_fair_probability"])
                        if 0 < candidate_fair < 1:
                            market_probability = candidate_fair
                            edge_basis = "probabilidad_justa_disponible"
                    except (TypeError, ValueError):
                        pass
                edge = model_probability - market_probability
                opportunity["implied_probability"] = round(implied, 6)
                opportunity["edge"] = round(edge, 6)
                opportunity["edge_pct"] = round(edge * 100, 2)
                opportunity["edge_basis"] = edge_basis
                if motor == "V4":
                    opportunity["v4_market_probability_used"] = round(market_probability, 6)
            else:
                # V3 compara contra la probabilidad justa sin margen; su edge
                # conservador no debe confundirse con modelo menos implícita bruta.
                opportunity["edge_basis"] = "probabilidad_justa_de_mercado"
                opportunity["edge_pct"] = round(float(opportunity.get("edge") or 0) * 100, 2)

            if motor in {"V1", "V11", "V2", "V12", "V21", "V22", "V2U", "V11U", "V4"}:
                opportunity = enrich(opportunity)
            prepared.append(opportunity)
        return prepared

    @classmethod
    def _motor_limit(cls, motor: str) -> int:
        if motor == "V3":
            return 3
        if motor == "ESP":
            return 1
        return 2 if motor in {"V12", "V22", "V4"} else 999999

    @classmethod
    def _current_bets(cls, experiment, motor: str) -> int:
        return experiment.entries.filter(motor=motor).count()

    @classmethod
    def _exposure(cls, experiment, motor: str) -> Decimal:
        return sum(
            (Decimal(str(x.stake)) for x in experiment.entries.filter(motor=motor)),
            Decimal("0"),
        )

    @staticmethod
    def _v3_market_family(opportunity: Dict[str, Any]) -> str:
        text = f"{opportunity.get('market', '')} {opportunity.get('selection', '')}".casefold()
        if any(token in text for token in ("ambos", "btts", "both teams", "total", "over", "under", "más", "mas", "menos", "goles")):
            return "goles_btts"
        if any(token in text for token in ("1x2", "resultado", "ganador", "match winner", "doble", "double chance", "sin empate", "draw no bet", "dnb")):
            return "resultado"
        return re.sub(r"\s+", " ", str(opportunity.get("market") or "").casefold().strip())

    @classmethod
    def _eligibility_reason(cls, experiment, motor: str, opportunity: Dict[str, Any]) -> str:
        if motor in cls.PAUSED_MOTORS:
            return f"Motor {cls.LABELS.get(motor, motor)} en pausa: no puede colocar apuestas nuevas; el código y el historial se conservan."
        key = cls._key(opportunity)
        if not key or key.strip("|") == "":
            return "Descartada: oportunidad sin mercado/selección/línea válidos."
        if motor in {"V2U", "V11U"} and opportunity.get("unsupported_market"):
            return "Mercado auditado, no apostable: falta un modelo de probabilidad fiable o datos finales verificables para liquidarlo."
        if motor == "ESP":
            votes = int(opportunity.get("consensus_votes") or 0)
            support_ratio = float(opportunity.get("consensus_support_ratio") or 0)
            if votes < 3:
                return f"Espía rechaza: consenso insuficiente ({votes}/7 motores visibles; mínimo 3)."
            if support_ratio < 0.60:
                return f"Espía rechaza: respaldo de {support_ratio * 100:.1f}% inferior al 60%."
            if cls._level(opportunity) not in {1, 2}:
                return "Espía rechaza: la señal consensuada no alcanza Nivel 1 o 2."
            if Decimal(str(opportunity.get("price") or 0)) < Decimal("1.30"):
                return "Espía rechaza: cuota inferior a 1.30."
            if float(opportunity.get("edge") or 0) < 0.05:
                edge_points = float(opportunity.get("edge") or 0) * 100
                return f"Espía rechaza: edge de {edge_points:.1f} puntos; exige al menos 5."
            if float(opportunity.get("confidence") or 0) < 0.60:
                return "Espía rechaza: confianza media inferior al 60%."
        if motor == "V4":
            if opportunity.get("unsupported_market"):
                return "Descartada V4: mercado sin probabilidad verificable para calibrar y liquidar."
            if opportunity.get("v4_context_rejection"):
                return str(opportunity["v4_context_rejection"])
            if Decimal(str(opportunity.get("price") or 0)) < Decimal("1.25"):
                return "Descartada V4: cuota inferior a 1.25."
            calibration_n = int(opportunity.get("calibration_sample_size") or 0)
            if calibration_n < 20:
                return (
                    "Descartada V4: solo hay "
                    f"{calibration_n} resultados V1.1 liquidados del mismo mercado y selección; "
                    "se requieren al menos 20 para estimar una probabilidad calibrada."
                )
            if cls._level(opportunity) not in {1, 2}:
                return "Descartada V4: solo acepta niveles 1 y 2."
            edge_v4 = float(opportunity.get("edge") or 0)
            confidence_v4 = float(opportunity.get("confidence") or 0)
            if edge_v4 < 0.05:
                return f"Descartada V4: edge calibrado {edge_v4 * 100:.1f} puntos inferior al mínimo 5.0."
            if confidence_v4 < 0.60:
                return "Descartada V4: confianza inferior al 60%."
        # Este control va antes de los filtros de nivel: una repetición debe
        # quedar identificada como tal aunque su señal haya cambiado de nivel.
        if LiveExperimentEntry.objects.filter(
            experiment=experiment, motor=motor, opportunity_key=key
        ).exists():
            return "Repetida: el motor ya tomó esta misma oportunidad/mercado."
        current_bets = cls._current_bets(experiment, motor)
        if current_bets >= cls._motor_limit(motor):
            return "Descartada: este motor ya alcanzó el máximo de apuestas por partido."
        price = Decimal(str(opportunity.get("price") or 0))
        if motor == "V3":
            if current_bets >= 2 and not opportunity.get("exceptional_third_bet"):
                return "Descartada V3: la tercera apuesta requiere justificación excepcional."
            if price < Decimal("1.40") or price > Decimal("2.10"):
                return "Descartada V3: cuota fuera del rango 1.40–2.10."
            if float(opportunity.get("edge") or 0) < 0.045:
                return "Descartada V3: edge conservador inferior a 4.5 puntos."
            if float(opportunity.get("confidence") or 0) < 0.50:
                return "Descartada V3: confianza inferior al 50%."
            if current_bets:
                family = cls._v3_market_family(opportunity)
                previous = experiment.entries.filter(motor="V3").exclude(status="CANCELLED")
                if any(cls._v3_market_family({"market": e.market, "selection": e.selection}) == family for e in previous):
                    return "Descartada V3: exposición correlacionada con una apuesta previa del mismo partido/mercado."
        level = cls._level(opportunity)
        if motor == "V2U" and level != 1:
            return "Descartada V2.Ultra: solo apuesta oportunidades de Nivel 1 · Muy fuerte."
        if motor == "V11U" and level != 2:
            return "Descartada V1.1 Ultra: solo apuesta oportunidades de Nivel 2 · Fuerte."
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
        return ""

    @classmethod
    def _initial_lives(cls, motor: str) -> Decimal:
        """Capital inicial independiente por motor; el Espía arranca con 50 vidas."""
        return Decimal(str(cls.INITIAL_LIVES_BY_MOTOR.get(motor, cls.INITIAL_LIVES)))

    @classmethod
    def _spy_opportunities(cls, opportunities_by_motor):
        """Agrega señales de los motores visibles, aunque no hayan realizado apuesta.

        Se consideran los siete motores visibles, incluido V4: aunque parte de V1.1,
        su calibración y filtros generan una evaluación distinta. Cada motor aporta
        como máximo una señal por mercado/línea.
        """
        source_motors = ("V11", "V12", "V21", "V22", "V2U", "V11U", "V4")
        per_family = {}
        for motor in source_motors:
            best_by_family = {}
            for raw in opportunities_by_motor.get(motor, []):
                opportunity = dict(raw)
                if opportunity.get("unsupported_market") or cls._level(opportunity) not in {1, 2}:
                    continue
                key = cls._key(opportunity)
                if not key or key.count("|") < 2:
                    continue
                parts = key.rsplit("|", 2)
                family_line = parts[0] + "|" + parts[2]
                try:
                    edge = float(opportunity.get("edge") or 0)
                    confidence = float(opportunity.get("confidence") or 0)
                    price = float(opportunity.get("price") or 0)
                except (TypeError, ValueError):
                    continue
                if price < 1.30:
                    continue
                rank = (edge, confidence, -cls._level(opportunity))
                current = best_by_family.get(family_line)
                if current is None or rank > current[0]:
                    best_by_family[family_line] = (rank, key, opportunity)
            for family_line, (_, key, opportunity) in best_by_family.items():
                per_family.setdefault(family_line, []).append({"motor": motor, "key": key, "opportunity": opportunity})
        grouped = {}
        for family_line, signals in per_family.items():
            for signal in signals:
                grouped.setdefault((family_line, signal["key"]), []).append(signal)
        result = []
        for (family_line, key), supporters in grouped.items():
            signal_set = per_family[family_line]
            supporting_motors = sorted({item["motor"] for item in supporters})
            opposing_motors = sorted({item["motor"] for item in signal_set if item["key"] != key})
            total_voters = len({item["motor"] for item in signal_set})
            support_ratio = len(supporting_motors) / total_voters if total_voters else 0.0
            base_items = [item["opportunity"] for item in supporters]
            prices = sorted(float(item.get("price") or 0) for item in base_items if float(item.get("price") or 0) > 1)
            if not prices:
                continue
            price = prices[len(prices) // 2]
            probabilities = [max(0.0, min(1.0, float(item.get("model_probability") or 0))) for item in base_items]
            confidences = [max(0.0, min(1.0, float(item.get("confidence") or 0))) for item in base_items]
            model_probability = sum(probabilities) / len(probabilities)
            implied_probability = 1.0 / price
            edge = model_probability - implied_probability
            levels = [cls._level(item) for item in base_items if cls._level(item) in {1, 2, 3}]
            candidate = dict(base_items[0])
            candidate.update({
                "price": price, "model_probability": round(model_probability, 6),
                "implied_probability": round(implied_probability, 6), "edge": round(edge, 6),
                "edge_pct": round(edge * 100, 2),
                "confidence": round(sum(confidences) / len(confidences), 6),
                "level": min(levels) if levels else 0,
                "consensus_votes": len(supporting_motors),
                "consensus_support_ratio": round(support_ratio, 6),
                "consensus_total_voters": total_voters,
                "consensus_motors": supporting_motors, "opposing_motors": opposing_motors,
                "v4_confirmation": "V4" in supporting_motors,
                "supporting_factors": ["Motor a favor: " + motor for motor in supporting_motors],
                "contradicting_factors": ["Señal contraria: " + motor for motor in opposing_motors],
                "reason": "Consenso del Espía: " + ", ".join(supporting_motors),
                "spy_market_family": family_line,
            })
            result.append(candidate)
        return result

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

        lives = cls._initial_lives(motor)
        for entry in entries:
            if entry.status in {"OPEN", "LOST"}:
                lives -= Decimal(str(entry.stake))
            elif entry.status == "WON":
                lives += Decimal(str(entry.pnl))
        # Nunca permitimos que el bankroll utilizable quede por debajo de cero.
        return max(Decimal("0"), lives)

    @classmethod
    def _stake(cls, opportunity: Dict[str, Any], lives: Decimal, motor: str = "") -> Decimal:
        level = cls._level(opportunity)
        if motor == "ESP":
            if level not in {1, 2} or lives < Decimal("1.00"):
                return Decimal("0")
            # El Espía puede apostar dinámicamente entre 1 y 50 vidas por apuesta.
            # El capital disponible también limita el stake: nunca apuesta dinero virtual que no tiene.
            votes = Decimal(str(opportunity.get("consensus_votes") or 0))
            ratio = Decimal(str(opportunity.get("consensus_support_ratio") or 0))
            confidence = Decimal(str(opportunity.get("confidence") or 0))
            edge = Decimal(str(opportunity.get("edge") or 0))
            votes_score = min(Decimal("1"), max(Decimal("0"), votes / Decimal("7")))
            ratio_score = min(Decimal("1"), max(Decimal("0"), ratio))
            confidence_score = min(Decimal("1"), max(Decimal("0"), confidence))
            edge_score = min(Decimal("1"), max(Decimal("0"), edge / Decimal("0.20")))
            strength = votes_score * Decimal("0.30") + ratio_score * Decimal("0.30") + confidence_score * Decimal("0.20") + edge_score * Decimal("0.20")
            stake = Decimal("1") + (lives - Decimal("1")) * strength
            return min(Decimal("50"), lives, max(Decimal("1"), stake)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if level == 0 or lives < cls.MIN_STAKE:
            return Decimal("0")
        if motor == "V4":
            edge = Decimal(str(opportunity.get("edge") or 0))
            confidence = Decimal(str(opportunity.get("confidence") or 0))
            stake = Decimal("2") if edge >= Decimal("0.10") and confidence >= Decimal("0.70") else Decimal("1")
            return min(stake, Decimal("2"), lives).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if motor in {"V2U", "V11U"}:
            required_level = 1 if motor == "V2U" else 2
            if level != required_level:
                return Decimal("0")
            max_stake = Decimal("20") if motor == "V2U" else Decimal("15")
            confidence = Decimal(str(opportunity.get("confidence") or 0))
            edge = Decimal(str(opportunity.get("edge") or 0))
            strength = min(Decimal("1"), max(Decimal("0"), confidence + min(edge * 2, Decimal("0.20"))))
            stake = Decimal("1") + (max_stake - Decimal("1")) * strength
            return min(max_stake, lives, stake).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        confidence = Decimal(str(opportunity.get("confidence") or 0))
        edge = Decimal(str(opportunity.get("edge") or 0))
        low, high = cls.LEVEL_RANGES[level]
        strength = min(Decimal("1"), max(Decimal("0"), confidence + min(edge * 4, Decimal("0.25"))))
        return min(cls.MAX_STAKE, lives, low + (high - low) * strength).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    @staticmethod
    def _key(opportunity: Dict[str, Any]) -> str:
        """Clave estable para que variaciones de texto no dupliquen una apuesta."""
        def normalize(value):
            text = unicodedata.normalize("NFKD", str(value or "").casefold())
            text = "".join(char for char in text if not unicodedata.combining(char))
            return re.sub(r"\s+", " ", text).strip()

        market = normalize(opportunity.get("market"))
        selection = normalize(opportunity.get("selection"))
        line = normalize(opportunity.get("line")).replace(",", ".")
        if not line and any(token in f"{market} {selection}" for token in ("total", "over", "under", "goles", "mas", "menos")):
            found_line = re.search(r"(\d+(?:\.\d+)?)", f"{market} {selection}".replace(",", "."))
            if found_line:
                line = found_line.group(1)
        # Unifica nombres habituales del mismo mercado entre feeds.
        if any(token in market for token in ("1x2", "resultado", "ganador", "match winner")):
            market = "resultado"
        elif any(token in market for token in ("doble", "double chance")):
            market = "doble oportunidad"
        elif any(token in market for token in ("ambos", "btts", "both teams")):
            market = "ambos marcan"
            if selection in {"si", "yes", "ambos si", "both yes"}:
                selection = "si"
            elif selection in {"no", "ambos no", "both no"}:
                selection = "no"
        elif any(token in market for token in ("total", "over", "under", "goles", "mas", "menos")):
            market = "total goles"
        # Normaliza selecciones equivalentes, sin mezclar líneas diferentes.
        if selection in {"home", "local", "1"}:
            selection = "1"
        elif selection in {"away", "visitante", "2"}:
            selection = "2"
        elif selection in {"draw", "empate", "x"}:
            selection = "x"
        elif any(token in selection for token in ("over", "mas de", "mas")):
            selection = "over"
        elif any(token in selection for token in ("under", "menos de", "menos")):
            selection = "under"
        elif selection in {"1x", "1 x"}:
            selection = "1x"
        elif selection in {"12", "1 2"}:
            selection = "12"
        elif selection in {"x2", "x 2"}:
            selection = "x2"
        # 2.50 y 2,5 se consideran la misma línea.
        try:
            if line:
                numeric_line = float(line)
                line = str(int(numeric_line)) if numeric_line.is_integer() else f"{numeric_line:g}"
        except ValueError:
            pass
        return "|".join((market, selection, line))

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

        if motor == "ESP":
            votes = int(opportunity.get("consensus_votes") or 0)
            ratio = float(opportunity.get("consensus_support_ratio") or 0) * 100
            supporters = ", ".join(opportunity.get("consensus_motors") or [])
            return (
                f"Espía apuesta {selection}{line_text}: consenso de {votes}/7 motores visibles ({ratio:.0f}% de respaldo; {supporters}); "
                f"probabilidad agregada {model_p * 100:.1f}%, edge {edge * 100:+.1f} puntos, confianza media {confidence * 100:.1f}%; "
                f"stake dinámico {stake:.2f} vidas según consenso, confianza y edge; puede usar de 1 hasta todo el capital disponible (50 vidas iniciales). Solo una apuesta por partido. "
                f"Contexto LIVE: minuto {minute_text}, marcador {score}."
            )
        probability_text = f"{model_p * 100:.1f}%"
        implied_text = f"{implied * 100:.1f}%"
        edge_text = f"{edge * 100:+.1f} puntos"
        line_text = f" {line}" if line and line.casefold() not in selection.casefold() else ""
        level_name = cls._level_name(level)
        if motor == "V3":
            market_fair = float(opportunity.get("market_fair_probability") or implied)
            market_fair_text = f"{market_fair * 100:.1f}%"
            base = (
                f"{selection}{line_text} elegido por V3: probabilidad prudente {probability_text}; "
                f"probabilidad implícita bruta de la cuota {implied_text}, probabilidad justa de mercado {market_fair_text}; "
                f"edge conservador {edge_text} calculado contra la probabilidad justa de mercado, después de penalizar incertidumbre; "
                f"contexto al momento de apostar: {score} al {minute_text}, Nivel {level} · {level_name}"
            )
            base += "; filtro de cuota 1.40–2.10 y consenso auxiliar"
        else:
            base = (
                f"{selection}{line_text} elegido por {label}: {probability_text} de probabilidad "
                f"frente a {implied_text} implícita ({edge_text} de edge); "
                f"{score} al {minute_text}, Nivel {level} · {level_name}"
            )

        if motor == "V3":
            if opportunity.get("exceptional_third_bet"):
                base += "; candidata excepcional por edge conservador >=10 puntos, confianza >=68% y baja dispersión"
            if cls._current_bets(experiment, motor) >= 2:
                base += "; tercera apuesta autorizada solo porque aporta una familia de mercado distinta, mantiene el tope de 4 vidas por partido y el máximo de 10 vidas abiertas globales"
        elif motor == "V4":
            raw_p = float(opportunity.get("raw_model_probability") or model_p)
            calibration_n = int(opportunity.get("calibration_sample_size") or 0)
            calibration_method = str(opportunity.get("calibration_method") or "sin datos")
            base += (
                f"; V4 deriva de V1.1 y calibra {raw_p * 100:.1f}% a {model_p * 100:.1f}% "
                f"({calibration_method}, {calibration_n} casos históricos en el intervalo); "
                "stake prudente de 1–2 vidas, máximo 2 apuestas por partido y 10 vidas abiertas por día"
            )
        elif motor == "V11U":
            temporal = opportunity.get("temporal_factor")
            if temporal is not None:
                base += f"; control temporal Ultra {float(temporal):.2f}"
            base += "; filtro exclusivo Nivel 2 · Fuerte, stake máximo 15 vidas"
        elif motor == "V2U":
            base += "; filtro exclusivo Nivel 1 · Muy fuerte, stake máximo 20 vidas"
        elif motor == "V11":
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
        # Defensa adicional: un motor pausado jamás devuelve una apuesta seleccionada.
        if motor in cls.PAUSED_MOTORS:
            return None, Decimal("0")
        lives = cls._ledger_lives(experiment, motor)
        candidates = [o for o in opportunities if cls._eligible(experiment, motor, o)]
        if not candidates or lives < cls.MIN_STAKE:
            return None, Decimal("0")

        if motor == "ESP":
            candidates.sort(key=lambda o: (
                int(o.get("consensus_votes") or 0),
                float(o.get("consensus_support_ratio") or 0),
                float(o.get("edge") or 0),
                float(o.get("confidence") or 0),
            ), reverse=True)
            for candidate in candidates:
                stake = cls._stake(candidate, lives, motor)
                if stake >= Decimal("1.00"):
                    return candidate, stake
            return None, Decimal("0")

        if motor == "V4":
            candidates.sort(key=lambda o: (
                float(o.get("edge") or 0),
                float(o.get("confidence") or 0),
                cls._level(o),
            ), reverse=True)
            daily_open = LiveExperimentEntry.objects.filter(
                experiment__started_at__date=timezone.localdate(), motor="V4", status="OPEN"
            )
            committed_today = sum((Decimal(str(e.stake)) for e in daily_open), Decimal("0"))
            remaining_daily = max(Decimal("0"), Decimal("10") - committed_today)
            for candidate in candidates:
                stake = min(cls._stake(candidate, lives, motor), remaining_daily)
                stake = stake.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                if stake >= cls.MIN_STAKE:
                    return candidate, stake
            return None, Decimal("0")

        if motor == "V3":
            candidates.sort(key=lambda o: (
                float(o.get("edge") or 0),
                float(o.get("confidence") or 0),
                float(o.get("consensus_score") or 0),
            ), reverse=True)
            daily_open = LiveExperimentEntry.objects.filter(
                experiment__started_at__date=timezone.localdate(), motor="V3", status="OPEN"
            )
            committed_today = sum((Decimal(str(e.stake)) for e in daily_open), Decimal("0"))
            remaining_daily = max(Decimal("0"), Decimal("10") - committed_today)
            remaining_match = max(Decimal("0"), Decimal("4") - cls._exposure(experiment, "V3"))
            for candidate in candidates:
                edge = Decimal(str(candidate.get("edge") or 0))
                confidence = Decimal(str(candidate.get("confidence") or 0))
                stake = min(Decimal("1.00"), Decimal("0.50") + max(Decimal("0"), edge) * Decimal("2") + max(Decimal("0"), confidence - Decimal("0.50")))
                stake = min(stake, lives, remaining_daily, remaining_match, Decimal("2.00"))
                stake = stake.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                if stake >= Decimal("0.50"):
                    return candidate, stake
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
        stake = cls._stake(selected, lives, motor)

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
        # Ultra score-derived markets: team totals and half-line handicaps.
        if any(x in text for x in ("team total", "goles del equipo", "goles equipo", "home team goals", "away team goals", "local total", "visitante total")):
            number_match = re.search(r"([+-]?\d+(?:[.,]\d+)?)", f"{line} {text}")
            if number_match:
                target = float(number_match.group(1).replace(",", "."))
                home_name = str(experiment.home_team or "").casefold()
                away_name = str(experiment.away_team or "").casefold()
                side = "home" if any(x in text for x in ("home", "local")) or (home_name and (home_name in selection or selection in home_name)) else (
                    "away" if any(x in text for x in ("away", "visitante")) or (away_name and (away_name in selection or selection in away_name)) else None
                )
                if side:
                    goals = home_score if side == "home" else away_score
                    if any(x in selection for x in ("over", "más", "mas", "+")): return goals > target
                    if any(x in selection for x in ("under", "menos")): return goals < target

        if any(x in text for x in ("handicap", "asian handicap", "handicap asiático", "spread")):
            number_match = re.search(r"([+-]?\d+(?:[.,]\d+)?)", f"{line} {selection}")
            if number_match:
                handicap = float(number_match.group(1).replace(",", "."))
                home_name = str(experiment.home_team or "").casefold()
                away_name = str(experiment.away_team or "").casefold()
                if "home" in selection or "local" in selection or (home_name and (home_name in selection or selection in home_name)):
                    return (home_score + handicap) > away_score
                if "away" in selection or "visitante" in selection or (away_name and (away_name in selection or selection in away_name)):
                    return (away_score + handicap) > home_score

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

        opportunities_by_motor = {}
        for motor in cls.MOTORS:
            if motor == "ESP":
                opportunities = [] if match_is_final else cls._spy_opportunities(opportunities_by_motor)
            else:
                opportunities = [] if match_is_final else cls._prepare_opportunities(
                    motor, getattr(match, cls.OPPORTUNITY_ATTRS[motor], []) or [], match=match
                )
            opportunities_by_motor[motor] = opportunities
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
            current = cls._initial_lives(motor)
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
                "total_staked": 0.0, "total_pnl": 0.0, "current_lives": float(cls._initial_lives(motor)),
            }
            for experiment in serialized_experiments:
                item = experiment["motors"].get(motor, {})
                for key in ("decisions", "wins", "losses", "open", "cancelled"):
                    aggregate[key] += int(item.get(key, 0) or 0)
                for key in ("total_staked", "total_pnl"):
                    aggregate[key] += float(item.get(key, 0) or 0)
            aggregate["current_lives"] = float(cls._initial_lives(motor)) + aggregate["total_pnl"]
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

    @staticmethod
    def _calibration_summary(rows):
        """Métricas históricas de calibración; no alteran las predicciones."""
        observations = []
        for probability, status in rows:
            try:
                probability = max(0.0, min(1.0, float(probability)))
            except (TypeError, ValueError):
                continue
            if status not in {"WON", "LOST"}:
                continue
            observations.append((probability, 1.0 if status == "WON" else 0.0))

        total = len(observations)
        if not total:
            return {
                "sample_size": 0, "win_rate": None, "mean_probability": None,
                "brier_score": None, "log_loss": None, "expected_calibration_error": None,
                "bins": [],
            }

        brier = sum((p - y) ** 2 for p, y in observations) / total
        log_loss = sum(
            -math.log(max(0.0001, min(0.9999, p))) if y else
            -math.log(max(0.0001, min(0.9999, 1.0 - p)))
            for p, y in observations
        ) / total
        bins = []
        weighted_gap = 0.0
        for index in range(10):
            items = [(p, y) for p, y in observations if min(9, int(p * 10)) == index]
            if not items:
                continue
            mean_p = sum(p for p, _ in items) / len(items)
            actual = sum(y for _, y in items) / len(items)
            weighted_gap += len(items) / total * abs(mean_p - actual)
            bins.append({
                "range": f"{index * 10}–{(index + 1) * 10}%",
                "count": len(items),
                "mean_probability": round(mean_p * 100, 2),
                "observed_win_rate": round(actual * 100, 2),
                "absolute_gap_points": round(abs(mean_p - actual) * 100, 2),
            })
        return {
            "sample_size": total,
            "win_rate": round(sum(y for _, y in observations) / total * 100, 2),
            "mean_probability": round(sum(p for p, _ in observations) / total * 100, 2),
            "brier_score": round(brier, 6),
            "log_loss": round(log_loss, 6),
            "expected_calibration_error": round(weighted_gap * 100, 2),
            "bins": bins,
        }

    @classmethod
    def serialize(cls, experiment, snapshot_limit=None, opportunity_limit=None):
        entries = []
        motors = {}
        for motor in cls.MOTORS:
            motor_entries = list(experiment.entries.filter(motor=motor).order_by("-placed_at"))
            total_pnl = sum((Decimal(str(e.pnl)) for e in motor_entries), Decimal("0"))
            total_staked = sum((Decimal(str(e.stake)) for e in motor_entries), Decimal("0"))
            best = max(motor_entries, key=lambda e: (e.level, e.model_probability, e.edge), default=None)
            # Reconstruye la curva desde el capital inicial propio de cada motor.
            curve = [cls._initial_lives(motor)]
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
                cls._initial_lives(motor) + total_pnl,
            )
            available_lives = max(Decimal("0"), total_capital - open_staked)
            settled_entries = [e for e in motor_entries if e.status in {"WON", "LOST"}]
            historical_rows = LiveExperimentEntry.objects.filter(
                motor=motor, status__in=("WON", "LOST")
            ).order_by("-placed_at").values_list("model_probability", "status")[:1000]
            historical_calibration = cls._calibration_summary(historical_rows)
            brier_score = (
                sum((float(e.model_probability) - (1.0 if e.status == "WON" else 0.0)) ** 2 for e in settled_entries)
                / len(settled_entries)
            ) if settled_entries else None
            log_loss = (
                sum(
                    -math.log(max(0.0001, min(0.9999, float(e.model_probability))))
                    if e.status == "WON"
                    else -math.log(1 - max(0.0001, min(0.9999, float(e.model_probability))))
                    for e in settled_entries
                ) / len(settled_entries)
            ) if settled_entries else None
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
                "brier_score": brier_score,
                "log_loss": log_loss,
                "historical_calibration": historical_calibration,
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
                "implied_probability": e.implied_probability,
                "market_fair_probability": (
                    e.opportunity_snapshot.get("market_fair_probability")
                    if isinstance(e.opportunity_snapshot, dict) else None
                ),
                "edge_pct": round(e.edge * 100, 2),
                "edge_basis": (
                    e.opportunity_snapshot.get("edge_basis")
                    if isinstance(e.opportunity_snapshot, dict) else None
                ),
                "raw_edge": (
                    e.opportunity_snapshot.get("raw_edge")
                    if isinstance(e.opportunity_snapshot, dict) else None
                ),
                "uncertainty_penalty": (
                    e.opportunity_snapshot.get("uncertainty_penalty")
                    if isinstance(e.opportunity_snapshot, dict) else None
                ),
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
        snapshot_rows = experiment.snapshots.all().order_by(
            "-created_at", "-id"
        )
        if snapshot_limit is not None:
            snapshot_rows = snapshot_rows[:max(0, int(snapshot_limit))]
        snapshot_rows = list(snapshot_rows)
        if snapshot_limit is not None:
            snapshot_rows.reverse()
        serialized_snapshots = []
        for snapshot in snapshot_rows:
            opportunities = snapshot.all_opportunities or []
            if opportunity_limit is not None and isinstance(opportunities, list):
                opportunities = opportunities[:max(0, int(opportunity_limit))]
            serialized_snapshots.append({
                "id": snapshot.id,
                "motor": snapshot.motor,
                "minute": snapshot.minute,
                "period": snapshot.period,
                "home_score": snapshot.home_score,
                "away_score": snapshot.away_score,
                "lives_before": float(snapshot.lives_before),
                "lives_after": float(snapshot.lives_after),
                "selected_opportunity": snapshot.selected_opportunity,
                "all_opportunities": opportunities,
                "decision_reason": snapshot.decision_reason,
                "created_at": snapshot.created_at.isoformat(),
            })
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
            "snapshots": serialized_snapshots,
        }
