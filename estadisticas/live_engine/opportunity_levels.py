"""
Clasificación común de oportunidades para el experimento V1/V2.

Los niveles son etiquetas experimentales, no probabilidades calibradas.
"""
from typing import Any, Dict


LEVELS = {
    1: {"name": "Muy fuerte", "label": "🟢 Nivel 1 · Muy fuerte"},
    2: {"name": "Fuerte", "label": "🟡 Nivel 2 · Fuerte"},
    3: {"name": "Moderada", "label": "🟠 Nivel 3 · Moderada"},
}


def classify(opportunity: Dict[str, Any]) -> int:
    probability = float(opportunity.get("model_probability") or 0)
    edge = float(opportunity.get("edge") or 0)
    confidence = float(opportunity.get("confidence") or 0)
    coverage = float(opportunity.get("data_coverage") or 0)
    signal = str(opportunity.get("signal_strength") or "").lower()
    contradictions = len(opportunity.get("contradicting_factors") or [])

    # Nivel 1 exige simultáneamente alta probabilidad, ventaja, confianza
    # y cobertura. V2 además no puede venir con una señal débil ni demasiadas
    # contradicciones.
    if (
        probability >= 0.80
        and edge >= 0.08
        and confidence >= 0.72
        and coverage >= 0.70
        and signal != "débil"
        and contradictions <= 2
    ):
        return 1

    if (
        probability >= 0.70
        and edge >= 0.05
        and confidence >= 0.55
        and coverage >= 0.50
    ):
        return 2

    if (
        probability >= 0.60
        and edge >= 0.03
        and confidence >= 0.45
        and coverage >= 0.40
    ):
        return 3

    return 0


def enrich(opportunity: Dict[str, Any]) -> Dict[str, Any]:
    level = classify(opportunity)
    opportunity["level"] = level
    opportunity["level_name"] = LEVELS.get(level, {"name": "Sin nivel"})["name"]
    opportunity["level_label"] = LEVELS.get(level, {"label": "Sin nivel"})["label"]
    return opportunity
