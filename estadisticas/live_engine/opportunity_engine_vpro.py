import re
from typing import Any, Dict, List, Optional

from .opportunity_engine_v2 import LiveOpportunityEngineV2


class LiveOpportunityEngineVPro:
    """V.Pro: rastrea al favorito detectado al inicio de su seguimiento LIVE y
    busca valor con estadísticas coherentes. No asume que dominar posesión
    garantice goles; si faltan datos o hay señales contradictorias, no apuesta.
    """

    MIN_FAVORITE_ODDS = 1.05
    MAX_FAVORITE_ODDS = 1.70
    MIN_POSSESSION_GAP = 11.0
    MIN_EDGE = 0.035
    MIN_CONFIDENCE = 0.52

    @staticmethod
    def _num(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            if isinstance(value, dict):
                value = value.get("value", value.get("raw_value"))
            return float(str(value).replace("%", "").replace(",", ".").strip())
        except (TypeError, ValueError):
            return None

    @classmethod
    def _stat(cls, performance: Dict[str, Any], side: str, *keys: str) -> Optional[float]:
        values = performance.get(side) or {}
        for key in keys:
            if key in values:
                value = cls._num(values.get(key))
                if value is not None:
                    return value
        return None

    @staticmethod
    def _norm(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    @classmethod
    def _is_1x2(cls, opportunity: Dict[str, Any]) -> bool:
        text = f'{opportunity.get("market", "")} {opportunity.get("selection", "")}'.lower()
        return any(term in text for term in ("1x2", "resultado", "ganador", "match winner"))

    @classmethod
    def _selection_side(cls, selection: str, match) -> Optional[str]:
        value = cls._norm(selection)
        home = cls._norm(match.home_team)
        away = cls._norm(match.away_team)
        if value in {"1", "local", "home"} or (home and (value == home or value in home or home in value)):
            return "home"
        if value in {"2", "visitante", "away"} or (away and (value == away or value in away or away in value)):
            return "away"
        return None

    @classmethod
    def _reference(cls, match) -> Optional[Dict[str, Any]]:
        saved = getattr(match, "vpro_reference_odds", None)
        if isinstance(saved, dict) and saved.get("side") in {"home", "away"}:
            try:
                price = float(saved.get("price"))
            except (TypeError, ValueError):
                price = 0
            if cls.MIN_FAVORITE_ODDS <= price <= cls.MAX_FAVORITE_ODDS:
                return saved

        # Respaldo para partidos que aún no tengan referencia persistida:
        # solo se usa la cuota 1X2 observada ahora y se marca como referencia LIVE.
        candidates = []
        for odd in match.odds or []:
            market = str(odd.get("market_name") or "").lower()
            if not any(term in market for term in ("1x2", "resultado", "ganador", "match winner")):
                continue
            side = cls._selection_side(str(odd.get("name") or ""), match)
            price = cls._num(odd.get("price"))
            if side and price and cls.MIN_FAVORITE_ODDS <= price <= cls.MAX_FAVORITE_ODDS:
                candidates.append({"side": side, "team": match.home_team if side == "home" else match.away_team,
                                   "price": price, "source": "cuota_live_observada"})
        return min(candidates, key=lambda item: item["price"]) if candidates else None

    @classmethod
    def _current_price(cls, match, market: str, selection: str) -> Optional[float]:
        wanted_market = cls._norm(market)
        wanted_selection = cls._norm(selection)
        for odd in match.odds or []:
            if cls._norm(odd.get("market_name")) == wanted_market and cls._norm(odd.get("name")) == wanted_selection:
                return cls._num(odd.get("price"))
        return None

    @classmethod
    def evaluate(cls, match) -> List[Dict[str, Any]]:
        if getattr(match, "is_finished", False):
            return []
        try:
            elapsed = LiveOpportunityEngineV2._elapsed(match.minute, match.period)
        except Exception:
            return []
        if elapsed < 12:
            return []

        reference = cls._reference(match)
        if not reference:
            return []

        home = {
            "possession": cls._stat(match.performance or {}, "home", "ball_possession", "possession"),
            "shots": cls._stat(match.performance or {}, "home", "total_shots", "goal_attempts"),
            "shots_on": cls._stat(match.performance or {}, "home", "shots_on_target", "shots_on_goal"),
            "xg": cls._stat(match.performance or {}, "home", "expected_goals", "xg", "expected_goals__general"),
            "big": cls._stat(match.performance or {}, "home", "big_chances", "big_chances_created"),
            "red": cls._stat(match.performance or {}, "home", "red_cards"),
        }
        away = {
            "possession": cls._stat(match.performance or {}, "away", "ball_possession", "possession"),
            "shots": cls._stat(match.performance or {}, "away", "total_shots", "goal_attempts"),
            "shots_on": cls._stat(match.performance or {}, "away", "shots_on_target", "shots_on_goal"),
            "xg": cls._stat(match.performance or {}, "away", "expected_goals", "xg", "expected_goals__general"),
            "big": cls._stat(match.performance or {}, "away", "big_chances", "big_chances_created"),
            "red": cls._stat(match.performance or {}, "away", "red_cards"),
        }
        baseline_side = reference["side"]
        fav, rival = (home, away) if baseline_side == "home" else (away, home)
        supporting, contradicting = [], []
        score = 0.0
        coverage = 0

        possession_gap = None
        if home["possession"] is not None and away["possession"] is not None:
            possession_gap = home["possession"] - away["possession"]
            coverage += 1
            fav_gap = possession_gap if baseline_side == "home" else -possession_gap
            if fav_gap >= cls.MIN_POSSESSION_GAP:
                supporting.append(f"Ventaja de posesión del favorito: {fav_gap:.0f} puntos porcentuales (umbral {cls.MIN_POSSESSION_GAP:.0f})")
                score += 0.22
            elif fav_gap <= -cls.MIN_POSSESSION_GAP:
                contradicting.append(f"El rival supera al favorito en posesión por {abs(fav_gap):.0f} puntos")
                score -= 0.18

        for key, label, weight in (("shots_on", "remates a puerta", 0.20), ("xg", "xG", 0.22),
                                   ("big", "grandes ocasiones", 0.16), ("shots", "remates totales", 0.10)):
            fv, rv = fav[key], rival[key]
            if fv is None or rv is None:
                continue
            coverage += 1
            if fv > rv:
                supporting.append(f"Favorito superior en {label}: {fv:g} vs {rv:g}")
                score += weight
            elif fv < rv:
                contradicting.append(f"Rival superior en {label}: {rv:g} vs {fv:g}")
                score -= weight

        if fav["red"] is not None and fav["red"] > 0:
            contradicting.append("El favorito tiene al menos una tarjeta roja")
            score -= 0.35
        if rival["red"] is not None and rival["red"] > 0:
            supporting.append("El rival tiene al menos una tarjeta roja")
            score += 0.15

        hs, aw = int(match.home_score or 0), int(match.away_score or 0)
        fav_score = hs if baseline_side == "home" else aw
        rival_score = aw if baseline_side == "home" else hs
        if fav_score < rival_score:
            supporting.append(f"El favorito pierde {hs}-{aw}; se revisa valor en doble oportunidad/empate, no se asume remontada")
        elif fav_score > rival_score:
            supporting.append(f"El favorito va ganando {hs}-{aw}")
            score += 0.05

        if coverage < 2:
            return []

        base = LiveOpportunityEngineV2.evaluate(match)
        results = []
        for source in base:
            market = str(source.get("market") or "")
            selection = str(source.get("selection") or "")
            text = f"{market} {selection}".lower()
            side = cls._selection_side(selection, match)
            is_double = any(x in text for x in ("doble oportunidad", "double chance"))
            is_btts = any(x in text for x in ("ambos marcan", "both teams", "btts"))
            is_total = any(x in text for x in ("total", "más", "menos", "over", "under"))
            if not (side in {baseline_side, "home" if baseline_side == "away" else "away"} or is_double or is_btts or is_total):
                continue

            favorite_name = cls._norm(reference.get("team"))
            selection_norm = cls._norm(selection)
            covers_favorite = side == baseline_side or (favorite_name and favorite_name in selection_norm)
            if is_double:
                if "1x" in selection_norm:
                    covers_favorite = baseline_side == "home"
                elif "x2" in selection_norm:
                    covers_favorite = baseline_side == "away"
            selected_favorite = bool(covers_favorite)
            local_support = list(source.get("supporting_factors") or []) + supporting
            local_contra = list(source.get("contradicting_factors") or []) + contradicting
            model_p = float(source.get("model_probability") or 0)
            implied = float(source.get("implied_probability") or 0)
            edge = model_p - implied

            # No se permite que una señal de posesión aislada convierta una
            # apuesta en oportunidad: exigimos consenso estadístico y edge mínimo.
            stat_score = score if selected_favorite else -score
            if is_btts or is_total:
                stat_score = score * 0.55
            coherence = max(0.0, min(1.0, 0.50 + stat_score))
            confidence = min(0.91, 0.38 + 0.12 * min(4, coverage) + 0.22 * coherence)
            if len(local_contra) >= 3:
                confidence -= 0.06
            confidence = max(0.30, confidence)

            # El rival solo se recomienda si sus estadísticas realmente
            # superan al favorito o existe una señal contextual fuerte.
            if side and side != baseline_side and score > -0.12:
                continue
            if edge < cls.MIN_EDGE or confidence < cls.MIN_CONFIDENCE:
                continue

            current_favorite_price = None
            for live_odd in match.odds or []:
                live_side = cls._selection_side(str(live_odd.get("name") or ""), match)
                market_name = str(live_odd.get("market_name") or "").lower()
                if live_side == baseline_side and any(term in market_name for term in ("1x2", "resultado", "ganador", "match winner")):
                    candidate_price = cls._num(live_odd.get("price"))
                    if candidate_price and candidate_price > 1:
                        current_favorite_price = candidate_price
                        break
            quota_change_pct = None
            if current_favorite_price is not None:
                baseline_price = float(reference.get("price") or 0)
                if baseline_price > 0:
                    quota_change_pct = (current_favorite_price / baseline_price - 1.0) * 100
                    if quota_change_pct >= 12:
                        local_support.append(f"Cuota LIVE del favorito subió {quota_change_pct:.1f}% desde la referencia")
                    elif quota_change_pct <= -8:
                        local_support.append(f"Cuota LIVE del favorito bajó {abs(quota_change_pct):.1f}% desde la referencia")

            opportunity = dict(source)
            opportunity.update({
                "model": "vpro_live_favorite_tracker",
                "vpro_reference_team": reference.get("team"),
                "vpro_reference_price": float(reference.get("price")),
                "vpro_reference_source": reference.get("source", "cuota_base_guardada"),
                "vpro_current_favorite_price": current_favorite_price,
                "vpro_favorite_quota_change_pct": round(quota_change_pct, 2) if quota_change_pct is not None else None,
                "vpro_possession_gap_points": round(possession_gap, 2) if possession_gap is not None else None,
                "vpro_statistical_score": round(score, 3),
                "model_probability": round(model_p, 4),
                "implied_probability": round(implied, 4),
                "edge": round(edge, 4),
                "edge_pct": round(edge * 100, 2),
                "confidence": round(confidence, 3),
                "supporting_factors": local_support[:12],
                "contradicting_factors": local_contra[:12],
                "data_coverage": round(min(1.0, coverage / 5), 3),
                "reason": (
                    f"V.Pro: favorito de referencia {reference.get('team')} (cuota base {float(reference.get('price')):.2f}); "
                    f"minuto {match.minute or 'desconocido'}, marcador {hs}-{aw}. "
                    f"Señales a favor: {len(local_support)}; contradicciones: {len(local_contra)}; "
                    f"ventaja estadística estimada {edge*100:.1f} puntos. Umbral de posesión: {cls.MIN_POSSESSION_GAP:.0f} puntos."
                ),
            })
            results.append(opportunity)

        results.sort(key=lambda x: (float(x.get("selection_score") or 0), float(x.get("edge") or 0),
                                    float(x.get("confidence") or 0)), reverse=True)
        return results[:5]
