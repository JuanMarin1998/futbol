import re
from typing import Any, Dict, List

from .opportunity_engine_v2 import LiveOpportunityEngineV2


class LiveOpportunityEngineV22:
    """V2.2 experimental: selector inteligente independiente.

    Este motor compite por separado. Parte de V2, pero usa su propio ranking
    de valor, confianza, consenso, cobertura y momento del partido.
    No intenta maximizar apuestas: intenta encontrar la mejor oportunidad.
    """

    @staticmethod
    def _elapsed(match) -> float:
        text = str(match.minute or "").lower()
        m = re.search(r"(\d+(?:[\.,]\d+)?)", text)
        value = float(m.group(1).replace(",", ".")) if m else 45.0
        if "descanso" in text or "half" in text:
            value = max(value, 45.0)
        if str(match.period or "").lower() in {"2nd half", "segunda parte"}:
            value = max(value, 45.0)
        return min(90.0, max(1.0, value))

    @staticmethod
    def _temporal_quality(elapsed: float) -> float:
        if elapsed < 12:
            return 0.35
        if elapsed < 20:
            return 0.62
        if elapsed < 30:
            return 0.82
        if elapsed < 45:
            return 0.93
        if elapsed < 65:
            return 1.00
        if elapsed < 80:
            return 0.94
        return 0.84

    @staticmethod
    def _market_priority(market: str, selection: str) -> float:
        text = f"{market} {selection}".lower()
        if "1x2" in text or "resultado" in text or "ganador" in text:
            return 1.00
        if "doble" in text or "double chance" in text:
            return 0.96
        if "sin empate" in text or "draw no bet" in text:
            return 0.95
        if "ambos" in text or "btts" in text:
            return 0.91
        if "total" in text or "over" in text or "under" in text or "más" in text or "menos" in text:
            return 0.90
        return 0.82

    @classmethod
    def _consensus(cls, source: Dict[str, Any]) -> float:
        support = list(source.get("supporting_factors") or [])
        contra = list(source.get("contradicting_factors") or [])
        coverage = float(source.get("data_coverage") or 0)

        # No exige cinco indicadores. Premia varias señales y castiga
        # contradicciones de forma gradual.
        support_score = min(1.0, len(support) / 4.0)
        contradiction_penalty = min(0.35, len(contra) * 0.08)
        coverage_factor = 0.70 + 0.30 * min(1.0, coverage)
        return max(0.0, min(1.0, support_score * coverage_factor - contradiction_penalty))

    @staticmethod
    def _calibrate_probability(raw: float, elapsed: float) -> float:
        raw = min(0.995, max(0.005, float(raw)))
        calibrated = 0.50 + (raw - 0.50) * 0.82
        if elapsed < 20 and abs(raw - 0.50) > 0.30:
            calibrated = 0.50 + (calibrated - 0.50) * 0.90
        return min(0.96, max(0.04, calibrated))

    @classmethod
    def evaluate(cls, match) -> List[Dict[str, Any]]:
        original = LiveOpportunityEngineV2.evaluate(match)
        elapsed = cls._elapsed(match)
        temporal = cls._temporal_quality(elapsed)
        results: List[Dict[str, Any]] = []

        for source in original:
            raw_p = float(source.get("model_probability") or 0)
            raw_conf = float(source.get("confidence") or 0)
            implied = float(source.get("implied_probability") or 0)
            coverage = float(source.get("data_coverage") or 0)
            consensus = cls._consensus(source)
            calibrated = cls._calibrate_probability(raw_p, elapsed)
            edge = calibrated - implied

            confidence = (
                0.40 * raw_conf
                + 0.25 * consensus
                + 0.20 * coverage
                + 0.15 * temporal
            )

            if raw_p >= 0.90 and consensus < 0.55:
                confidence -= 0.10
            if raw_p <= 0.10 and consensus < 0.55:
                confidence -= 0.10
            if len(source.get("contradicting_factors") or []) >= 3:
                confidence -= 0.08
            confidence = min(0.94, max(0.30, confidence))

            edge_component = max(-0.20, min(0.25, edge)) / 0.25
            value_score = (
                0.40 * edge_component
                + 0.22 * confidence
                + 0.18 * consensus
                + 0.12 * coverage
                + 0.08 * temporal
            )
            value_score *= cls._market_priority(
                source.get("market", ""), source.get("selection", "")
            )

            opportunity = dict(source)
            opportunity.update({
                "raw_model_probability": round(raw_p, 4),
                "raw_confidence": round(raw_conf, 4),
                "model_probability": round(calibrated, 4),
                "implied_probability": round(implied, 4),
                "edge": round(edge, 4),
                "edge_pct": round(edge * 100, 2),
                "confidence": round(confidence, 3),
                "consensus_score": round(consensus, 3),
                "support_count": len(source.get("supporting_factors") or []),
                "contradiction_count": len(source.get("contradicting_factors") or []),
                "temporal_factor": round(temporal, 3),
                "selection_score": round(value_score, 4),
                "calibration": "moderate_shrink_v2_2",
                "model": "v2_2_intelligent_selector",
                "reason": (
                    f"V2.2 selecciona por valor, confianza, consenso, cobertura "
                    f"y momento. Score {value_score:.3f}; edge {edge*100:.1f}%."
                ),
            })
            opportunity["signal_strength"] = (
                "fuerte" if confidence >= 0.72
                else ("moderada" if confidence >= 0.55 else "débil")
            )

            # Umbral mínimo deliberadamente moderado. El control final de
            # riesgo/participación sigue estando en LiveExperimentManager.
            if edge < 0.025 or confidence < 0.45:
                continue
            results.append(opportunity)

        results.sort(
            key=lambda x: (
                float(x.get("selection_score") or 0),
                float(x.get("edge") or 0),
                float(x.get("confidence") or 0),
                float(x.get("consensus_score") or 0),
            ),
            reverse=True,
        )
        return results[:10]
