import re
from typing import Any, Dict, List

from .opportunity_engine_v2 import LiveOpportunityEngineV2
from .opportunity_levels import enrich


class LiveOpportunityEngineV22:
    """V2.2: V2 + calibración + consenso + control temporal + extremos."""

    @staticmethod
    def _elapsed(match) -> float:
        text = str(match.minute or "").lower()
        m = re.search(r"(\d+(?:[\.,]\d+)?)", text)
        value = float(m.group(1).replace(",", ".")) if m else 45.0
        if "descanso" in text or "half" in text or str(match.period or "").lower() in {"2nd half", "segunda parte"}:
            value = max(value, 45.0)
        return min(90.0, max(1.0, value))

    @staticmethod
    def _temporal_factor(elapsed: float) -> float:
        if elapsed <= 15: return 0.60
        if elapsed <= 25: return 0.74
        if elapsed <= 35: return 0.86
        if elapsed <= 55: return 0.95
        return 1.0

    @staticmethod
    def _calibrate(raw: float, factor: float) -> float:
        raw = min(.995, max(.005, float(raw)))
        compressed = .50 + (raw - .50) * .72
        return min(.965, max(.035, .50 + (compressed - .50) * factor))

    @classmethod
    def evaluate(cls, match) -> List[Dict[str, Any]]:
        original = LiveOpportunityEngineV2.evaluate(match)
        elapsed = cls._elapsed(match)
        temporal = cls._temporal_factor(elapsed)
        results = []

        for source in original:
            support = list(source.get("supporting_factors") or [])
            contra = list(source.get("contradicting_factors") or [])
            coverage = float(source.get("data_coverage") or 0)
            raw_p = float(source.get("model_probability") or 0)
            raw_conf = float(source.get("confidence") or 0)

            # Consenso: se requieren varias familias de indicadores y se
            # castigan contradicciones. El conteo se basa en factores ya
            # calculados por V2, no en datos futuros.
            support_count = len(support)
            contra_count = len(contra)
            consensus = min(1.0, support_count / 5.0) * (1.0 - min(.55, contra_count * .11))
            if coverage < .50:
                consensus *= .72

            calibrated = cls._calibrate(raw_p, temporal)
            implied = float(source.get("implied_probability") or 0)
            edge = calibrated - implied
            confidence = .50 + (raw_conf - .50) * .72
            confidence = .50 + (confidence - .50) * temporal
            confidence = confidence * (.70 + .30 * consensus)

            # Predicciones >=95% solo pueden conservar confianza alta si existe
            # consenso real entre múltiples indicadores.
            if raw_p >= .95 and (support_count < 3 or consensus < .55):
                confidence = min(confidence, .72)
            if raw_p >= .90 and elapsed < 30:
                confidence -= .06
            confidence = min(.93, max(.35, confidence))

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
                "support_count": support_count,
                "contradiction_count": contra_count,
                "temporal_factor": round(temporal, 3),
                "calibration": "shrink_to_50_v2_2",
                "model": "multi_factor_live_v2_calibrated",
                "reason": f"V2.2 calibra V2, exige consenso de indicadores y controla el minuto ({elapsed:.0f}'). Edge calibrado: {edge*100:.1f} puntos.",
            })
            opportunity["signal_strength"] = "fuerte" if confidence >= .72 else ("moderada" if confidence >= .55 else "débil")
            if edge < .03 or confidence < .45:
                continue
            if enrich(opportunity)["level"]:
                results.append(opportunity)

        results.sort(key=lambda x: (x["edge"], x["confidence"], x.get("consensus_score", 0)), reverse=True)
        return results[:10]
