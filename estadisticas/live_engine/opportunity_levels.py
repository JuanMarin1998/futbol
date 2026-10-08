"""
Clasificación común de oportunidades para el experimento V1/V2.

Los niveles son etiquetas de riesgo/selección, no probabilidades garantizadas.
La clasificación debe premiar edge + confianza, pero impedir que una probabilidad
extrema se convierta automáticamente en una apuesta grande sin respaldo.
"""
from typing import Any, Dict


LEVELS = {
    1: {"name": "Muy fuerte", "label": "🟢 Nivel 1 · Muy fuerte"},
    2: {"name": "Fuerte", "label": "🟡 Nivel 2 · Fuerte"},
    3: {"name": "Moderada", "label": "🟠 Nivel 3 · Moderada"},
    0: {"name": "Descartada · Sin nivel", "label": "🔴 Descartada · Sin nivel"},
}


def _coverage(opportunity: Dict[str, Any]) -> float:
    """Devuelve cobertura si el motor la conoce.

    V1 no publica data_coverage; en ese caso no penalizamos artificialmente
    al motor original. V2 sí la publica y entonces sí participa en el nivel.
    """
    value = opportunity.get("data_coverage")
    if value is None:
        return 1.0
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def classify(opportunity: Dict[str, Any]) -> int:
    probability = max(0.0, min(1.0, float(opportunity.get("model_probability") or 0)))
    edge = float(opportunity.get("edge") or 0)
    confidence = max(0.0, min(1.0, float(opportunity.get("confidence") or 0)))
    coverage = _coverage(opportunity)
    signal = str(
        opportunity.get("signal_strength")
        or opportunity.get("signal")
        or ""
    ).lower()
    contradictions = len(opportunity.get("contradicting_factors") or [])
    support = len(opportunity.get("supporting_factors") or [])

    if not signal:
        signal = "fuerte" if confidence >= 0.72 else (
            "moderada" if confidence >= 0.55 else "débil"
        )

    # Una probabilidad extrema no es automáticamente una señal excelente.
    # Si el modelo dice >=95% o <=5%, exigimos respaldo adicional; de lo
    # contrario, como máximo puede ser una señal moderada (Nivel 3).
    extreme = probability >= 0.95 or probability <= 0.05
    extreme_backed = (
        confidence >= 0.82
        and coverage >= 0.50
        and (support >= 2 or contradictions == 0)
    )

    # Nivel 1: solo señales realmente fuertes.
    if (
        not extreme
        and probability >= 0.75
        and edge >= 0.10
        and confidence >= 0.80
        and coverage >= 0.50
        and signal != "débil"
        and contradictions <= 1
    ):
        return 1

    # Nivel 2: buena oportunidad, pero todavía con riesgo.
    if (
        not extreme
        and probability >= 0.65
        and edge >= 0.07
        and confidence >= 0.65
        and coverage >= 0.35
        and contradictions <= 2
    ):
        return 2

    # Nivel 3: oportunidad moderada. También permite probabilidades altas,
    # pero solo con edge/confianza suficientes. Una señal extrema sin respaldo
    # queda fuera para evitar apuestas grandes basadas en 95-100% artificiales.
    if (
        probability >= 0.55
        and edge >= 0.03
        and confidence >= 0.55
        and coverage >= 0.25
        and contradictions <= 3
    ):
        if extreme and not extreme_backed:
            return 0
        return 3

    return 0


def enrich(opportunity: Dict[str, Any]) -> Dict[str, Any]:
    level = classify(opportunity)
    opportunity["level"] = level
    opportunity["level_name"] = LEVELS.get(level, LEVELS[0])["name"]
    opportunity["level_label"] = LEVELS.get(level, LEVELS[0])["label"]
    opportunity["bettable"] = level in (1, 2, 3)
    return opportunity
