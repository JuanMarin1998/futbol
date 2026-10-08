import re
from typing import Any, Dict, List, Optional

from .opportunity_engine import LiveOpportunityEngine


class LiveOpportunityEngineV12:
    """V1.2: V1 original + filtros conservadores de selección.

    V1 no se modifica. V1.2 reutiliza su lambda/probabilidad base, pero
    inspecciona una gama más amplia de mercados LIVE que el V1 original:
    1X2, doble oportunidad, DNB, BTTS y líneas de totales de goles.
    """

    MIN_PRICE = 1.50
    MIN_EDGE = 0.05
    MIN_CONFIDENCE = 0.55

    @staticmethod
    def _num(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(str(value).replace("%", "").replace(",", "."))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _line(market: Any, selection: Any, line: Any) -> Optional[float]:
        text = f"{line or ''} {market or ''} {selection or ''}".replace(",", ".")
        m = re.search(r"(\d+(?:\.\d+)?)", text)
        return float(m.group(1)) if m else None

    @classmethod
    def _market_key(cls, market: str, selection: str, line: Any, home_team: str, away_team: str):
        m = str(market or "").lower()
        s = str(selection or "").strip().lower()
        text = f"{m} {s}"

        if any(x in text for x in ("1x2", "resultado", "ganador", "match winner")):
            hn = re.sub(r"\W+", "", str(home_team or "").lower())
            an = re.sub(r"\W+", "", str(away_team or "").lower())
            sn = re.sub(r"\W+", "", s)
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

        if any(x in text for x in ("sin empate", "draw no bet", "dnb", "empate no acción", "empate no accion")):
            hn = re.sub(r"\\W+", "", str(home_team or "").lower())
            an = re.sub(r"\\W+", "", str(away_team or "").lower())
            sn = re.sub(r"\\W+", "", s)
            if s in {"1", "local", "home"} or "local" in s or (hn and (sn == hn or sn in hn or hn in sn)):
                return "dnb_home"
            if s in {"2", "visitante", "away"} or "visitante" in s or (an and (sn == an or sn in an or an in sn)):
                return "dnb_away"

        if any(x in text for x in ("ambos", "both teams", "btts")):
            if any(x in s for x in ("sí", "si", "yes")): return "btts_yes"
            if any(x in s for x in ("no", "not")): return "btts_no"

        if any(x in text for x in ("total", "over", "under", "más", "menos")):
            lv = cls._line(market, selection, line)
            if lv is None or abs(lv * 2 - round(lv * 2)) > 0.01:
                return None
            if any(x in s for x in ("over", "más", "mas", "+")):
                return f"over_{lv:g}"
            if any(x in s for x in ("under", "menos", "-")):
                return f"under_{lv:g}"

        return None

    @classmethod
    def _probabilities(cls, hs: int, aw: int, lh: float, la: float) -> Dict[str, float]:
        home = draw = away = 0.0
        for i in range(11):
            for j in range(11):
                p = LiveOpportunityEngine._poisson_pmf(i, lh) * LiveOpportunityEngine._poisson_pmf(j, la)
                fh, fa = hs + i, aw + j
                if fh > fa: home += p
                elif fh == fa: draw += p
                else: away += p

        total = hs + aw
        lam = lh + la

        def cdf(k):
            return LiveOpportunityEngine._poisson_cdf(k, lam)

        probs = {
            "home": home, "draw": draw, "away": away,
            "dc_1x": home + draw, "dc_12": home + away, "dc_x2": draw + away,
            "dnb_home": home / max(home + away, 1e-9),
            "dnb_away": away / max(home + away, 1e-9),
        }

        for line in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5):
            needed = int(line - total + 1)
            over = 1.0 if needed <= 0 else 1.0 - cdf(needed - 1)
            probs[f"over_{line:g}"] = over
            probs[f"under_{line:g}"] = 1.0 - over

        home_scores = 1.0 - LiveOpportunityEngine._poisson_cdf(0, lh)
        away_scores = 1.0 - LiveOpportunityEngine._poisson_cdf(0, la)
        probs["btts_yes"] = home_scores * away_scores
        probs["btts_no"] = 1.0 - probs["btts_yes"]
        return probs

    @classmethod
    def evaluate(cls, match) -> List[Dict[str, Any]]:
        performance = match.performance or {}
        elapsed = LiveOpportunityEngine._elapsed_minutes(match.minute, match.period)
        hs, aw = int(match.home_score or 0), int(match.away_score or 0)
        lh, la = LiveOpportunityEngine._remaining_lambda(performance, elapsed)
        probabilities = cls._probabilities(hs, aw, lh, la)

        results = []
        for odd in match.odds or []:
            price = cls._num(odd.get("price"))
            if not price or price < cls.MIN_PRICE:
                continue

            key = cls._market_key(
                odd.get("market_name", ""), odd.get("name", ""), odd.get("line"),
                match.home_team, match.away_team,
            )
            model_p = probabilities.get(key) if key else None
            if model_p is None:
                continue

            implied = 1.0 / price
            edge = model_p - implied
            confidence = min(
                0.95,
                max(
                    0.0,
                    0.50
                    + min(0.20, max(0.0, edge))
                    + min(0.15, match.data_quality * 0.15)
                    + min(0.10, match.mapping_confidence * 0.10),
                ),
            )
            if edge < cls.MIN_EDGE or confidence < cls.MIN_CONFIDENCE:
                continue

            results.append({
                "market": odd.get("market_name", ""),
                "selection": odd.get("name", ""),
                "line": odd.get("line"),
                "price": price,
                "model_probability": round(model_p, 4),
                "implied_probability": round(implied, 4),
                "edge": round(edge, 4),
                "edge_pct": round(edge * 100, 2),
                "confidence": round(confidence, 3),
                "signal": "positive_edge_v1_2",
                "model": "poisson_live_v1_2",
                "base_model": "V1",
                "v12_market_key": key,
                "reason": (
                    f"V1.2 reutiliza V1 y amplía la evaluación LIVE a mercados "
                    f"compatibles. Cuota {price:.2f}, edge {edge*100:.1f} puntos."
                ),
            })

        # Seguridad alta primero, después edge y confianza. El nivel final
        # lo asigna la capa del laboratorio; aquí solo se conserva la señal V1.
        results.sort(key=lambda x: (x["edge"], x["confidence"], x["price"]), reverse=True)
        return results[:20]
