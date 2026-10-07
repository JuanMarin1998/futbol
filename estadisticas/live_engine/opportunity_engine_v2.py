import math
import re
from typing import Any, Dict, List, Optional, Tuple


class LiveOpportunityEngineV2:
    """Motor de análisis estadístico LIVE V2, separado del motor V1."""

    MIN_ELAPSED = 12.0

    @staticmethod
    def _num(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(str(value).strip().replace("%", "").replace(",", "."))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _stat(cls, performance: Dict[str, Any], side: str, *names: str) -> Optional[float]:
        data = performance.get(side) or {}
        for name in names:
            item = data.get(name)
            if isinstance(item, dict):
                for key in ("value", "raw_value"):
                    value = cls._num(item.get(key))
                    if value is not None:
                        return value
            else:
                value = cls._num(item)
                if value is not None:
                    return value
        return None

    @classmethod
    def _features(cls, performance: Dict[str, Any], side: str) -> Dict[str, Optional[float]]:
        aliases = {
            "xg": ("expected_goals", "xg", "expected_goals__general"),
            "xgot": ("xg_on_target", "xgot", "expected_goals_on_target"),
            "shots": ("total_shots", "goal_attempts"),
            "shots_on": ("shots_on_target", "shots_on_goal"),
            "shots_off": ("shots_off_target", "shots_off_goal"),
            "blocked": ("blocked_shots",),
            "big_chances": ("big_chances", "big_chances_created"),
            "big_missed": ("big_chances_missed",),
            "touches_box": ("touches_in_opposition_box", "touches_opposition_box"),
            "corners": ("corner_kicks", "corners"),
            "offsides": ("offsides",),
            "possession": ("ball_possession", "possession"),
            "passes": ("passes",),
            "accurate_passes": ("accurate_passes",),
            "final_third": ("final_third_passes",),
            "accurate_final_third": ("accurate_final_third_passes",),
            "crosses": ("crosses",),
            "xa": ("expected_assists", "xa"),
            "key_passes": ("key_passes",),
            "fouls": ("fouls",),
            "duels_won": ("duels_won",),
            "tackles": ("tackles",),
            "interceptions": ("interceptions",),
            "clearances": ("clearances",),
            "saves": ("goalkeeper_saves", "saves"),
            "xgot_faced": ("xgot_faced",),
            "goals_prevented": ("goals_prevented",),
            "yellow": ("yellow_cards",),
            "red": ("red_cards",),
        }
        return {key: cls._stat(performance, side, *names) for key, names in aliases.items()}

    @staticmethod
    def _elapsed(minute: Any, period: Any) -> float:
        text = str(minute or "").lower()
        m = re.search(r"(\d+(?:[\.,]\d+)?)", text)
        value = float(m.group(1).replace(",", ".")) if m else 45.0
        if "descanso" in text or "half" in text:
            value = max(value, 45.0)
        if str(period or "").lower() in {"2nd half", "segunda parte"}:
            value = max(value, 45.0)
        return min(90.0, max(1.0, value))

    @staticmethod
    def _poisson_pmf(k: int, lam: float) -> float:
        if lam <= 0:
            return 1.0 if k == 0 else 0.0
        return math.exp(-lam) * lam ** k / math.factorial(k)

    @classmethod
    def _poisson_cdf(cls, k: int, lam: float) -> float:
        if k < 0:
            return 0.0
        return sum(cls._poisson_pmf(i, lam) for i in range(k + 1))

    @classmethod
    def _lambdas(cls, home: Dict[str, Optional[float]], away: Dict[str, Optional[float]], elapsed: float):
        remaining = max(0.0, 90.0 - elapsed)

        def rate(f):
            parts = []
            if f["xg"] is not None:
                parts.append((f["xg"] / elapsed) * 0.55)
            if f["xgot"] is not None:
                parts.append((f["xgot"] / elapsed) * 0.20)
            if f["shots_on"] is not None:
                parts.append((f["shots_on"] / elapsed) * 0.11)
            if f["big_chances"] is not None:
                parts.append((f["big_chances"] / elapsed) * 0.10)
            if f["touches_box"] is not None:
                parts.append((f["touches_box"] / elapsed) * 0.012)
            if f["final_third"] is not None:
                parts.append((f["final_third"] / elapsed) * 0.0015)
            if f["xa"] is not None:
                parts.append((f["xa"] / elapsed) * 0.08)
            return min(0.085, max(0.003, sum(parts) if parts else 0.012))

        return rate(home) * remaining, rate(away) * remaining

    @classmethod
    def _probabilities(cls, hs: int, aw: int, lh: float, la: float):
        home = draw = away = 0.0
        for i in range(11):
            for j in range(11):
                p = cls._poisson_pmf(i, lh) * cls._poisson_pmf(j, la)
                fh, fa = hs + i, aw + j
                if fh > fa:
                    home += p
                elif fh == fa:
                    draw += p
                else:
                    away += p

        total = hs + aw
        lam = lh + la

        def over(line):
            needed = math.floor(line - total) + 1
            return 1.0 if needed <= 0 else 1.0 - cls._poisson_cdf(needed - 1, lam)

        if hs > 0 and aw > 0:
            btts = 1.0
        elif hs > 0:
            btts = 1.0 - cls._poisson_cdf(0, la)
        elif aw > 0:
            btts = 1.0 - cls._poisson_cdf(0, lh)
        else:
            btts = (1.0 - cls._poisson_cdf(0, lh)) * (1.0 - cls._poisson_cdf(0, la))

        return {
            "home": home,
            "draw": draw,
            "away": away,
            "over_2_5": over(2.5),
            "under_2_5": 1.0 - over(2.5),
            "btts_yes": btts,
            "btts_no": 1.0 - btts,
        }

    @staticmethod
    def _team_name_key(name: str) -> str:
        return re.sub(r"\W+", "", str(name or "").lower())

    @classmethod
    def _market_key(cls, market: str, selection: str, line: Any, home_team: str, away_team: str):
        m, s = str(market or "").lower(), str(selection or "").strip().lower()
        text = f"{m} {s}"
        sn = cls._team_name_key(s)
        hn, an = cls._team_name_key(home_team), cls._team_name_key(away_team)

        if any(x in text for x in ("1x2", "resultado", "ganador", "match winner")):
            if s in {"1", "local", "home"} or (hn and (sn == hn or sn in hn or hn in sn)):
                return "home"
            if s in {"x", "empate", "draw"}:
                return "draw"
            if s in {"2", "visitante", "away"} or (an and (sn == an or sn in an or an in sn)):
                return "away"

        if "doble" in text or "double chance" in text:
            if "1x" in s: return "dc_1x"
            if "12" in s: return "dc_12"
            if "x2" in s: return "dc_x2"

        if any(x in text for x in ("ambos", "both teams", "btts")):
            return "btts_yes" if any(x in s for x in ("sí", "si", "yes")) else "btts_no"

        if any(x in text for x in ("total", "over", "under", "más", "menos")):
            match = re.search(r"(\d+(?:[\.,]\d+)?)", f"{line or ''} {text}")
            if match and abs(float(match.group(1).replace(",", ".")) - 2.5) < 0.01:
                return "over_2_5" if any(x in s for x in ("over", "más", "mas", "+")) else "under_2_5"
        return None

    @staticmethod
    def _fmt(v):
        if v is None:
            return "—"
        return str(int(round(v))) if abs(v - round(v)) < .01 else f"{v:.2f}"

    @classmethod
    def _signals(cls, key, h, a, hs, aw, elapsed):
        support, contra = [], []
        score = 0.0
        observed = 0
        possible = 0

        def cmp(metric, label, weight, greater):
            nonlocal score, observed, possible
            possible += 1
            hv, av = h.get(metric), a.get(metric)
            if hv is None or av is None:
                return
            observed += 1
            if abs(hv - av) < .01:
                return
            positive = (hv > av) if greater else (hv < av)
            item = f"{label}: {cls._fmt(hv)} vs {cls._fmt(av)}"
            if positive:
                support.append(item)
                score += weight
            else:
                contra.append(item)
                score -= weight

        if key in {"home", "dc_1x"}:
            for args in [
                ("xg", "xG", .22, True), ("xgot", "xGOT", .16, True),
                ("shots_on", "Remates al arco", .13, True),
                ("big_chances", "Grandes ocasiones", .12, True),
                ("touches_box", "Toques en área", .08, True),
                ("final_third", "Pases al último tercio", .06, True),
                ("xa", "xA", .06, True), ("possession", "Posesión", .04, True)]:
                cmp(*args)
            if hs > aw:
                support.append(f"Marcador favorable: {hs}-{aw}"); score += .12
            elif hs < aw:
                contra.append(f"Marcador desfavorable: {hs}-{aw}"); score -= .12

        elif key in {"away", "dc_x2"}:
            for args in [
                ("xg", "xG", .22, False), ("xgot", "xGOT", .16, False),
                ("shots_on", "Remates al arco", .13, False),
                ("big_chances", "Grandes ocasiones", .12, False),
                ("touches_box", "Toques en área", .08, False),
                ("final_third", "Pases al último tercio", .06, False),
                ("xa", "xA", .06, False), ("possession", "Posesión", .04, False)]:
                cmp(*args)
            if aw > hs:
                support.append(f"Marcador favorable: {hs}-{aw}"); score += .12
            elif aw < hs:
                contra.append(f"Marcador desfavorable: {hs}-{aw}"); score -= .12

        elif key == "draw":
            if hs == aw:
                support.append(f"Marcador empatado: {hs}-{aw}"); score += .16
            else:
                contra.append(f"Marcador actual: {hs}-{aw}"); score -= .16
            cmp("xg", "xG", .15, False)
            cmp("xgot", "xGOT", .10, False)
            cmp("shots_on", "Remates al arco", .08, False)

        elif key in {"over_2_5", "under_2_5"}:
            greater = key == "over_2_5"
            for args in [
                ("xg", "xG", .18, greater), ("xgot", "xGOT", .15, greater),
                ("shots", "Remates totales", .10, greater),
                ("shots_on", "Remates al arco", .14, greater),
                ("big_chances", "Grandes ocasiones", .14, greater),
                ("touches_box", "Toques en área", .07, greater),
                ("corners", "Corners", .05, greater)]:
                cmp(*args)
            total = hs + aw
            if total >= 3 and greater:
                support.append(f"Ya hay {total} goles"); score += .15
            elif total >= 3 and not greater:
                contra.append(f"Ya hay {total} goles"); score -= .15
            if elapsed >= 70 and greater:
                contra.append(f"Quedan aproximadamente {90-elapsed:.0f} min"); score -= .08

        elif key in {"btts_yes", "btts_no"}:
            greater = key == "btts_yes"
            for args in [
                ("xg", "xG", .16, greater), ("xgot", "xGOT", .14, greater),
                ("shots_on", "Remates al arco", .12, greater),
                ("big_chances", "Grandes ocasiones", .12, greater),
                ("touches_box", "Toques en área", .06, greater)]:
                cmp(*args)
            if hs > 0 and aw > 0:
                if greater:
                    support.append("Ambos equipos ya marcaron"); score += .30
                else:
                    contra.append("Ambos equipos ya marcaron"); score -= .30
            elif hs == 0 and aw == 0 and elapsed >= 70:
                if greater:
                    contra.append("0-0 con poco tiempo restante"); score -= .15
                else:
                    support.append("0-0 con poco tiempo restante"); score += .15

        coverage = observed / possible if possible else 0.0
        return support[:8], contra[:8], coverage, min(1.0, max(0.0, .5 + score))

    @classmethod
    def evaluate(cls, match) -> List[Dict[str, Any]]:
        performance = match.performance or {}
        elapsed = cls._elapsed(match.minute, match.period)
        if elapsed < cls.MIN_ELAPSED:
            return []

        hs, aw = int(match.home_score or 0), int(match.away_score or 0)
        h, a = cls._features(performance, "home"), cls._features(performance, "away")
        lh, la = cls._lambdas(h, a, elapsed)
        probabilities = cls._probabilities(hs, aw, lh, la)

        markets = {}
        for odd in match.odds or []:
            price = cls._num(odd.get("price"))
            if not price or price <= 1:
                continue
            key = cls._market_key(odd.get("market_name"), odd.get("name"), odd.get("line"), match.home_team, match.away_team)
            if key:
                markets.setdefault(key, []).append({**odd, "price": price})

        results = []
        for key, selections in markets.items():
            model_p = probabilities.get(key)
            if model_p is None:
                model_p = {
                    "dc_1x": probabilities["home"] + probabilities["draw"],
                    "dc_12": probabilities["home"] + probabilities["away"],
                    "dc_x2": probabilities["draw"] + probabilities["away"],
                }.get(key)
            if model_p is None:
                continue

            support, contra, coverage, strength = cls._signals(key, h, a, hs, aw, elapsed)
            for odd in selections:
                implied = 1.0 / odd["price"]
                edge = model_p - implied
                results.append({
                    "market": odd.get("market_name", ""),
                    "selection": odd.get("name", ""),
                    "line": odd.get("line"),
                    "price": odd["price"],
                    "model_probability": round(model_p, 4),
                    "implied_probability": round(implied, 4),
                    "edge": round(edge, 4),
                    "edge_pct": round(edge * 100, 2),
                    "confidence": round(min(.95, .30 + .35 * coverage + .20 * strength + .10 * float(match.mapping_confidence or 0)), 3),
                    "signal_strength": "fuerte" if strength >= .72 else ("moderada" if strength >= .55 else "débil"),
                    "supporting_factors": support,
                    "contradicting_factors": contra,
                    "data_coverage": round(coverage, 3),
                    "remaining_lambda_home": round(lh, 4),
                    "remaining_lambda_away": round(la, 4),
                    "model": "multi_factor_live_v2",
                    "reason": f"V2 combina xG/xGOT, remates, ataque, pases y contexto de marcador/tiempo. Ventaja estadística: {edge*100:.1f} puntos.",
                })

        results.sort(key=lambda x: (x["edge"], x["confidence"], x["data_coverage"]), reverse=True)
        return results[:10]
