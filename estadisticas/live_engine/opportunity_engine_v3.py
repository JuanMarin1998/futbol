"""Motor V3: agregador conservador e independiente de las seis estrategias existentes.

La probabilidad se aproxima con las estimaciones disponibles de V1/V1.1/V1.2/V2/V2.1/V2.2,
con contracción hacia la probabilidad de mercado sin margen. No se presenta como una
calibración estadística aprendida: esa calibración requiere suficientes resultados históricos
liquidados y separados temporalmente.
"""
from __future__ import annotations

import re
import statistics
from time import monotonic
from typing import Any, Dict, List

from django.utils import timezone

from ..models import LiveExperimentEntry
from .opportunity_engine import LiveOpportunityEngine
from .opportunity_engine_v12 import LiveOpportunityEngineV12

from .opportunity_levels import enrich


class LiveOpportunityEngineV3:
    MIN_PRICE = 1.40
    MAX_PRICE = 2.10
    MIN_EDGE = 0.045
    MAX_EXTREME_EDGE = 0.30
    _CALIBRATION_CACHE = {}

    SOURCE_ATTRS = (
        ("V1", "opportunities"),
        ("V1.1", "opportunities_v11"),
        ("V1.2", "opportunities_v12"),
        ("V2", "opportunities_v2"),
        ("V2.1", "opportunities_v21"),
        ("V2.2", "opportunities_v22"),
    )

    @staticmethod
    def _number(value: Any):
        try:
            return float(str(value).replace("%", "").replace(",", "."))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _norm(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().casefold())

    @classmethod
    def _key(cls, item: Dict[str, Any]) -> str:
        return "|".join(cls._norm(item.get(k)) for k in ("market", "selection", "line"))

    @classmethod
    def _market_group(cls, odd: Dict[str, Any]) -> str:
        return "|".join((cls._norm(odd.get("market_name")), cls._norm(odd.get("line"))))

    @classmethod
    def _market_fair_probabilities(cls, odds: List[Dict[str, Any]]) -> Dict[str, float]:
        groups: Dict[str, list] = {}
        for odd in odds:
            if not cls._active_odd(odd):
                continue
            price = cls._number(odd.get("price"))
            if price is None or price <= 1:
                continue
            groups.setdefault(cls._market_group(odd), []).append((odd, 1.0 / price))
        fair = {}
        for items in groups.values():
            # Solo quitamos margen cuando el proveedor entrega al menos dos
            # selecciones del mismo mercado/línea; si no, conservamos la implícita.
            total = sum(prob for _, prob in items)
            if total <= 0:
                continue
            for odd, raw in items:
                fair[cls._key({
                    "market": odd.get("market_name"),
                    "selection": odd.get("name"),
                    "line": odd.get("line"),
                })] = raw / total if len(items) >= 2 else raw
        return fair

    @staticmethod
    def _active_odd(odd: Dict[str, Any]) -> bool:
        status = str(odd.get("odd_status") or odd.get("status") or "").casefold()
        return not any(token in status for token in ("suspend", "inactive", "closed", "blocked", "settled", "void"))

    @staticmethod
    def _elapsed(match) -> float:
        text = str(match.minute or "").lower()
        found = re.search(r"(\d+)", text)
        minute = float(found.group(1)) if found else 45.0
        if "half" in text or "descanso" in text or str(match.period or "").lower() in {"2nd half", "segunda parte"}:
            minute = max(45.0, minute)
        return min(90.0, max(1.0, minute))

    @classmethod
    def _historical_market_rate(cls, market: str, probability: float):
        """Calibración empírica con caché corta para no frenar el ciclo LIVE."""
        cache_key = (str(market or "").casefold(), round(probability, 1))
        now = monotonic()
        cached = cls._CALIBRATION_CACHE.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]
        lower = max(0.01, probability - 0.10)
        upper = min(0.99, probability + 0.10)
        history = LiveExperimentEntry.objects.filter(
            motor="V3",
            market=market,
            status__in=("WON", "LOST"),
            placed_at__lt=timezone.now(),
            model_probability__gte=lower,
            model_probability__lte=upper,
        )
        total = history.count()
        if total < 20:
            result = (None, total)
        else:
            wins = history.filter(status="WON").count()
            # Suavizado Beta(1,1) evita probabilidades 0/100% con muestras finitas.
            result = ((wins + 1) / (total + 2), total)
        cls._CALIBRATION_CACHE[cache_key] = (now + 30.0, result)
        return result

    @classmethod
    def evaluate(cls, match) -> List[Dict[str, Any]]:
        if getattr(match, "is_finished", False):
            return []
        if getattr(match, "home_score", None) is None or getattr(match, "away_score", None) is None:
            return []

        raw_by_key: Dict[str, list] = {}
        for label, attr in cls.SOURCE_ATTRS:
            # Collector ya evaluó cada motor en este mismo snapshot; reutilizamos
            # esas salidas para no duplicar trabajo en el ciclo LIVE.
            for source in getattr(match, attr, []) or []:
                item = dict(source)
                if not cls._active_odd(item):
                    continue
                price = cls._number(item.get("price"))
                probability = cls._number(item.get("model_probability"))
                if price is None or probability is None or not cls.MIN_PRICE <= price <= cls.MAX_PRICE:
                    continue
                if not 0 < probability < 1:
                    continue
                key = cls._key(item)
                if key:
                    raw_by_key.setdefault(key, []).append((label, item))

        odds = list(getattr(match, "odds", []) or [])
        # Evaluación base propia para ampliar la cobertura de mercados compatibles,
        # incluso cuando ningún otro motor publicó una señal positiva.
        elapsed = LiveOpportunityEngine._elapsed_minutes(match.minute, match.period)
        lh, la = LiveOpportunityEngine._remaining_lambda(match.performance or {}, elapsed)
        probabilities = LiveOpportunityEngineV12._probabilities(
            int(match.home_score or 0), int(match.away_score or 0), lh, la
        )
        for odd in odds:
            price = cls._number(odd.get("price"))
            if price is None or not cls.MIN_PRICE <= price <= cls.MAX_PRICE:
                continue
            market_key = LiveOpportunityEngineV12._market_key(
                str(odd.get("market_name") or ""), str(odd.get("name") or ""),
                odd.get("line"), match.home_team, match.away_team
            )
            probability = probabilities.get(market_key) if market_key else None
            if probability is None or not 0 < probability < 1:
                continue
            item = {
                "market": odd.get("market_name", ""),
                "selection": odd.get("name", ""),
                "line": odd.get("line"),
                "price": price,
                "model_probability": probability,
                "model": "v3_base_poisson",
            }
            key = cls._key(item)
            if key:
                raw_by_key.setdefault(key, []).append(("Base V3", item))

        if not raw_by_key:
            return []

        fair_probs = cls._market_fair_probabilities(odds)
        elapsed = cls._elapsed(match)
        temporal_factor = 0.65 if elapsed < 15 else 0.78 if elapsed < 30 else 0.90 if elapsed < 45 else 1.0
        result = []

        for key, observations in raw_by_key.items():
            exemplar = dict(observations[0][1])
            price = cls._number(exemplar.get("price"))
            if price is None or not cls.MIN_PRICE <= price <= cls.MAX_PRICE:
                continue
            probabilities = [max(0.01, min(0.99, cls._number(o.get("model_probability")))) for _, o in observations]
            median_p = statistics.median(probabilities)
            dispersion = statistics.pstdev(probabilities) if len(probabilities) > 1 else 0.12
            fair_p = fair_probs.get(key, 1.0 / price)
            # Proxy conservador hasta que exista un conjunto histórico suficiente
            # y estrictamente anterior al partido para calibración empírica.
            calibrated = 0.70 * median_p + 0.30 * fair_p
            historical_rate, historical_n = cls._historical_market_rate(
                str(exemplar.get("market") or ""), median_p
            )
            if historical_rate is not None:
                empirical_weight = 0.50 if historical_n >= 50 else 0.35
                calibrated = (1 - empirical_weight) * calibrated + empirical_weight * historical_rate
            calibrated = max(0.02, min(0.98, calibrated))
            raw_implied = 1.0 / price
            edge = calibrated - fair_p
            uncertainty_penalty = min(0.12, 0.02 + dispersion * 0.50)
            conservative_edge = edge - uncertainty_penalty
            consensus_count = len({label for label, _ in observations if label != "Base V3"})
            consensus = consensus_count / len(cls.SOURCE_ATTRS)
            quality = max(0.0, min(1.0, float(getattr(match, "data_quality", 0) or 0)))
            mapping = max(0.0, min(1.0, float(getattr(match, "mapping_confidence", 0) or 0)))
            confidence = max(0.35, min(0.88,
                0.48 + consensus * 0.16 + quality * 0.10 + mapping * 0.08
                + max(-0.08, min(0.08, edge)) - dispersion * 0.35
            ))
            if confidence > 0.50:
                confidence = 0.50 + (confidence - 0.50) * temporal_factor
            extreme = edge >= cls.MAX_EXTREME_EDGE
            if extreme and consensus_count < 2 and not (quality >= 0.75 and mapping >= 0.85):
                # Una ventaja extrema requiere más evidencia; no se descarta automáticamente.
                uncertainty_penalty = min(0.18, uncertainty_penalty + 0.05)
                conservative_edge = edge - uncertainty_penalty
                confidence = max(0.35, confidence - 0.04)
            exceptional = (
                conservative_edge >= 0.10
                and confidence >= 0.68
                and dispersion <= 0.10
                and (consensus >= 2 / len(cls.SOURCE_ATTRS) or (quality >= 0.75 and mapping >= 0.85))
            )
            if conservative_edge < cls.MIN_EDGE or confidence < 0.50:
                continue

            # Edge conservador gobierna nivel y stake; un edge bruto enorme no
            # es suficiente si los motores discrepan o la calidad es baja.
            prepared = dict(exemplar)
            prepared.update({
                "raw_model_probability": round(median_p, 4),
                "model_probability": round(calibrated, 4),
                "implied_probability": round(raw_implied, 4),
                "market_fair_probability": round(fair_p, 4),
                "edge": round(conservative_edge, 4),
                "raw_edge": round(edge, 4),
                "edge_pct": round(conservative_edge * 100, 2),
                "confidence": round(confidence, 3),
                "model": "v3_conservative_ensemble",
                "calibration": "historical_market_calibration" if historical_rate is not None else "market_shrinkage_proxy_pending_20_settled_v3_bets",
                "calibration_sample": historical_n,
                "calibration_sources": [label for label, _ in observations if label != "Base V3"],
                "consensus_score": round(consensus, 3),
                "model_dispersion": round(dispersion, 4),
                "uncertainty_penalty": round(uncertainty_penalty, 4),
                "temporal_factor": temporal_factor,
                "extreme_edge": extreme,
                "exceptional_third_bet": bool(exceptional),
                "data_quality": quality,
                "mapping_confidence": mapping,
                "reason": (
                    f"V3: cuota {price:.2f} dentro de 1.40–2.10; probabilidad prudente "
                    f"{calibrated*100:.1f}%, probabilidad implícita bruta {raw_implied*100:.1f}%, "
                    f"probabilidad justa de mercado {fair_p*100:.1f}%, edge conservador frente al mercado justo "
                    f"{conservative_edge*100:+.1f} puntos; "
                    f"consenso {consensus_count}/6, "
                    f"dispersión {dispersion*100:.1f} puntos, minuto {elapsed:.0f}'. "
                    + ("Edge extremo: penalización extra y validación reforzada por consenso/calidad. " if extreme else "")
                    + ("Candidata excepcional para una tercera apuesta, sujeta a límites de riesgo. " if exceptional else "")
                    + (f"Calibración empírica de mercado con {historical_n} apuestas V3 liquidadas. " if historical_rate is not None else f"Calibración provisional: {historical_n}/20 apuestas históricas V3 liquidadas en el rango. ")
                ),
            })
            prepared = enrich(prepared)
            # Exigir un nivel apostable, sin forzar una probabilidad artificialmente alta.
            if not prepared.get("level"):
                continue
            result.append(prepared)

        result.sort(key=lambda o: (
            float(o.get("edge") or 0),
            float(o.get("confidence") or 0),
            float(o.get("consensus_score") or 0),
        ), reverse=True)
        return result[:20]
