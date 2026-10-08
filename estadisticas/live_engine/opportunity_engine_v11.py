import re
from typing import Any, Dict, List

from .opportunity_engine import LiveOpportunityEngine
from .opportunity_levels import enrich


class LiveOpportunityEngineV11:
    """V1.1: V1 original + calibración, control temporal y control de extremos.

    V1 no se modifica. Esta capa transforma sus oportunidades sobre el mismo
    snapshot LIVE y conserva la señal original para auditoría.
    """

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
        if elapsed <= 15: return 0.64
        if elapsed <= 25: return 0.76
        if elapsed <= 35: return 0.86
        if elapsed <= 55: return 0.94
        return 1.0

    @staticmethod
    def _calibrate_probability(raw: float, elapsed: float) -> float:
        # Shrinkage conservador hacia 50%; evita convertir muestras pequeñas
        # en certezas. El control temporal se aplica sobre la distancia a 50%.
        raw = min(0.995, max(0.005, float(raw)))
        base = 0.50 + (raw - 0.50) * 0.78
        return min(0.97, max(0.03, 0.50 + (base - 0.50) * LiveOpportunityEngineV11._temporal_factor(elapsed)))

    @classmethod
    def evaluate(cls, match) -> List[Dict[str, Any]]:
        original = LiveOpportunityEngine.evaluate(match)
        elapsed = cls._elapsed(match)
        temporal = cls._temporal_factor(elapsed)
        results = []

        for source in original:
            raw_p = float(source.get("model_probability") or 0)
            calibrated = cls._calibrate_probability(raw_p, elapsed)
            implied = float(source.get("implied_probability") or 0)
            edge = calibrated - implied
            raw_conf = float(source.get("confidence") or 0)
            confidence = 0.50 + (raw_conf - 0.50) * 0.78
            confidence = 0.50 + (confidence - 0.50) * temporal

            # Penalización adicional de predicciones extremas sin evidencia
            # temporal suficiente. No elimina todas las señales tempranas.
            if raw_p >= 0.90 and elapsed < 30:
                confidence -= 0.08
            elif raw_p >= 0.95:
                confidence -= 0.04
            confidence = min(0.94, max(0.35, confidence))

            opportunity = dict(source)
            opportunity.update({
                "raw_model_probability": round(raw_p, 4),
                "raw_confidence": round(raw_conf, 4),
                "model_probability": round(calibrated, 4),
                "implied_probability": round(implied, 4),
                "edge": round(edge, 4),
                "edge_pct": round(edge * 100, 2),
                "confidence": round(confidence, 3),
                "temporal_factor": round(temporal, 3),
                "calibration": "shrink_to_50_v1_1",
                "model": "poisson_live_v1_calibrated",
                "reason": f"V1.1 calibra V1 hacia 50%, pondera el minuto ({elapsed:.0f}') y penaliza extremos. Edge calibrado: {edge*100:.1f} puntos.",
            })
            opportunity["signal_strength"] = "fuerte" if confidence >= .72 else ("moderada" if confidence >= .55 else "débil")
            if edge < 0.03 or confidence < 0.45:
                continue
            if enrich(opportunity)["level"]:
                results.append(opportunity)

        results.sort(key=lambda x: (x["edge"], x["confidence"]), reverse=True)
        return results[:10]
