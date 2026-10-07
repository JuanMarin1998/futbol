import math
import re
from typing import Any, Dict, List, Optional, Tuple

from .opportunity_levels import enrich


class LiveOpportunityEngine:
    """
    Motor estadístico v1 para detectar discrepancias entre:
    - probabilidad implícita de la cuota Ecuabet
    - probabilidad estimada por un modelo simple basado en marcador, tiempo y xG.

    No garantiza resultados. Las señales son indicadores cuantitativos y deben
    mantenerse separadas de cualquier decisión de riesgo.
    """

    MIN_EDGE = 0.03
    MIN_CONFIDENCE = 0.55

    @staticmethod
    def _num(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(str(value).replace("%", "").replace(",", "."))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _stat(cls, performance: Dict[str, Any], side: str, *names: str) -> Optional[float]:
        data = performance.get(side) or {}
        for name in names:
            item = data.get(name)
            if isinstance(item, dict):
                value = cls._num(item.get("value"))
                if value is not None:
                    return value
                value = cls._num(item.get("raw_value"))
                if value is not None:
                    return value
            else:
                value = cls._num(item)
                if value is not None:
                    return value
        return None

    @classmethod
    def _elapsed_minutes(cls, minute: Any, period: Any) -> float:
        text = str(minute or "").lower()
        match = re.search(r"(\d+)", text)
        value = float(match.group(1)) if match else 45.0
        if "descanso" in text or "half" in text or "2nd" in text:
            value = max(value, 45.0)
        if str(period or "").lower() in {"2nd half", "segunda parte"}:
            value = max(value, 45.0)
        return min(90.0, max(1.0, value))

    @staticmethod
    def _poisson_pmf(k: int, lam: float) -> float:
        if lam <= 0:
            return 1.0 if k == 0 else 0.0
        return math.exp(-lam) * (lam ** k) / math.factorial(k)

    @classmethod
    def _poisson_cdf(cls, k: int, lam: float) -> float:
        if k < 0:
            return 0.0
        return sum(cls._poisson_pmf(i, lam) for i in range(k + 1))

    @classmethod
    def _remaining_lambda(cls, performance: Dict[str, Any], elapsed: float) -> Tuple[float, float]:
        hxg = cls._stat(performance, "home", "expected_goals", "expected_goals__general")
        axg = cls._stat(performance, "away", "expected_goals", "expected_goals__general")
        hshots = cls._stat(performance, "home", "goal_attempts", "total_shots")
        ashots = cls._stat(performance, "away", "goal_attempts", "total_shots")
        hon = cls._stat(performance, "home", "shots_on_goal", "shots_on_target")
        aon = cls._stat(performance, "away", "shots_on_goal", "shots_on_target")

        remaining = max(0.0, 90.0 - elapsed)
        if elapsed >= 88:
            return 0.0, 0.0

        # xG por minuto es la señal principal; volumen de remates aporta
        # estabilidad cuando xG todavía es pequeño o no está disponible.
        def team_rate(xg, shots, on_target):
            rates = []
            if xg is not None:
                rates.append(max(0.0, xg / elapsed))
            if shots is not None:
                shot_rate = shots / elapsed
                target_rate = (on_target / elapsed) if on_target is not None else shot_rate * 0.34
                rates.append(max(0.0, shot_rate * 0.055 + target_rate * 0.10))
            if not rates:
                return 0.012
            return min(0.075, max(0.004, sum(rates) / len(rates)))

        return team_rate(hxg, hshots, hon) * remaining, team_rate(axg, ashots, aon) * remaining

    @classmethod
    def _probabilities(cls, home_goals: int, away_goals: int, lh: float, la: float) -> Dict[str, float]:
        max_goals = 8
        home_dist = [cls._poisson_pmf(i, lh) for i in range(max_goals + 1)]
        away_dist = [cls._poisson_pmf(i, la) for i in range(max_goals + 1)]

        home_win = draw = away_win = 0.0
        for i, hp in enumerate(home_dist):
            for j, ap in enumerate(away_dist):
                if i > j:
                    home_win += hp * ap
                elif i == j:
                    draw += hp * ap
                else:
                    away_win += hp * ap

        total_current = home_goals + away_goals
        lam_total = lh + la
        over_05 = 1 - cls._poisson_cdf(0, lam_total)
        over_15 = 1 - cls._poisson_cdf(max(0, 1 - total_current), lam_total)
        over_25 = 1 - cls._poisson_cdf(max(0, 2 - total_current), lam_total)
        under_25 = 1 - over_25

        home_scores = 1 - cls._poisson_cdf(0, lh)
        away_scores = 1 - cls._poisson_cdf(0, la)
        btts = home_scores * away_scores

        return {
            "home": home_win,
            "draw": draw,
            "away": away_win,
            "over_0_5": over_05,
            "over_1_5": over_15,
            "over_2_5": over_25,
            "under_2_5": under_25,
            "btts_yes": btts,
            "btts_no": 1 - btts,
            "remaining_goals": lam_total,
        }

    @staticmethod
    def _market_key(market_name: str, selection_name: str, line: Any) -> Optional[str]:
        text = f"{market_name} {selection_name}".lower()
        line_text = str(line or "").replace(",", ".")
        if "1x2" in text or "resultado" in text or "ganador" in text:
            if selection_name.lower() in {"1", "local", "home"} or "local" in selection_name.lower():
                return "home"
            if selection_name.lower() in {"x", "empate", "draw"}:
                return "draw"
            if selection_name.lower() in {"2", "visitante", "away"} or "visitante" in selection_name.lower():
                return "away"
        if "doble" in text or "double chance" in text:
            normalized = selection_name.lower()
            if "1x" in normalized:
                return "dc_1x"
            if "12" in normalized:
                return "dc_12"
            if "x2" in normalized:
                return "dc_x2"
        if "ambos" in text or "both teams" in text or "btts" in text:
            return "btts_yes" if any(x in selection_name.lower() for x in ("sí", "si", "yes")) else "btts_no"
        if "total" in text or "over" in text or "más" in text or "menos" in text or "under" in text:
            line_match = re.search(r"(\d+(?:[\.,]\d+)?)", line_text + " " + text)
            if not line_match:
                return None
            line_value = float(line_match.group(1).replace(",", "."))
            if abs(line_value - 2.5) > 0.01:
                return None
            sel = selection_name.lower()
            if any(x in sel for x in ("over", "más", "mas", "+")):
                return "over_2_5"
            if any(x in sel for x in ("under", "menos", "-")):
                return "under_2_5"
        return None

    @classmethod
    def evaluate(cls, match) -> List[Dict[str, Any]]:
        performance = match.performance or {}
        minute = cls._elapsed_minutes(match.minute, match.period)
        home_goals = int(match.home_score or 0)
        away_goals = int(match.away_score or 0)
        lh, la = cls._remaining_lambda(performance, minute)
        probs = cls._probabilities(home_goals, away_goals, lh, la)

        raw_markets: Dict[str, List[Dict[str, Any]]] = {}
        for odd in match.odds or []:
            price = cls._num(odd.get("price"))
            if not price or price <= 1:
                continue
            key = cls._market_key(
                odd.get("market_name", ""),
                odd.get("name", ""),
                odd.get("line"),
            )
            if key:
                raw_markets.setdefault(key, []).append({**odd, "price": price})

        opportunities = []
        for key, selections in raw_markets.items():
            model_p = probs.get(key)
            if model_p is None:
                if key == "dc_1x":
                    model_p = probs["home"] + probs["draw"]
                elif key == "dc_12":
                    model_p = probs["home"] + probs["away"]
                elif key == "dc_x2":
                    model_p = probs["draw"] + probs["away"]
            if model_p is None:
                continue

            for odd in selections:
                implied = 1.0 / odd["price"]
                edge = model_p - implied
                if edge < cls.MIN_EDGE:
                    continue
                confidence = min(
                    0.95,
                    max(
                        0.0,
                        0.50
                        + min(0.20, edge)
                        + min(0.15, match.data_quality * 0.15)
                        + min(0.10, match.mapping_confidence * 0.10),
                    ),
                )
                opportunity = enrich({
                    "market": odd.get("market_name", ""),
                    "selection": odd.get("name", ""),
                    "line": odd.get("line"),
                    "price": odd["price"],
                    "model_probability": round(model_p, 4),
                    "implied_probability": round(implied, 4),
                    "edge": round(edge, 4),
                    "edge_pct": round(edge * 100, 2),
                    "confidence": round(confidence, 3),
                    "data_coverage": round(match.data_quality, 3),
                    "signal_strength": "fuerte" if confidence >= .72 else ("moderada" if confidence >= .55 else "débil"),
                    "supporting_factors": [],
                    "contradicting_factors": [],
                    "signal": "positive_edge" if confidence >= cls.MIN_CONFIDENCE else "weak_edge",
                    "model": "poisson_live_v1",
                    "reason": f"V1 usa marcador, tiempo, xG y volumen de remates. Ventaja estadística: {edge*100:.1f} puntos.",
                })
                if opportunity["level"]:
                    opportunities.append(opportunity)

        opportunities.sort(key=lambda x: (x["edge"], x["confidence"]), reverse=True)
        return opportunities[:10]
