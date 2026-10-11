"""V.Pro 1.1: variante experimental y conservadora; V.Pro original queda intacto."""
from typing import Any, Dict, List

from .opportunity_engine_v2 import LiveOpportunityEngineV2
from .opportunity_engine_vpro import LiveOpportunityEngineVPro


class LiveOpportunityEngineVPro11:
    """Filtra oportunidades V.Pro con validación de datos y coherencia estadística.

    No sustituye al motor original. Solo emite oportunidades para el motor VP11.
    La calibración histórica se aplica en LiveExperimentManager, usando únicamente
    apuestas VP11 liquidadas antes de la evaluación actual.
    """

    MIN_FAVORITE_ODDS = 1.05
    MAX_FAVORITE_ODDS = 1.70
    MIN_MINUTE = 12
    MAX_MINUTE = 78
    MIN_MAPPING_CONFIDENCE = 0.70
    MIN_DATA_QUALITY = 0.30
    MIN_EDGE = 0.055
    MIN_CONFIDENCE = 0.58

    @staticmethod
    def _is_combination_market(market: Any, selection: Any) -> bool:
        """No puntúa combinadas como si fueran una selección simple."""
        raw = f"{market or ''} {selection or ''}".lower()
        normalized = LiveOpportunityEngineVPro._norm(raw)
        if any(token in normalized for token in ("multigoles", "combinada", "combinado", "combo")):
            return True
        has_double_chance = any(token in normalized for token in (
            "dobleoportunidad", "doublechance", "1x", "x2", "12",
        ))
        has_total = any(token in normalized for token in (
            "totalgoles", "over", "under", "masde", "menosde", "goles",
        ))
        has_joiner = "&" in raw or "+" in raw or " y " in raw or " and " in raw
        return has_double_chance and has_total and has_joiner

    @classmethod
    def _all_market_candidates(cls, match, elapsed: float) -> List[Dict[str, Any]]:
        """Evalúa todas las cuotas LIVE compatibles, sin heredar el top-10 de V2.

        Cada selección recibe una probabilidad específica del modelo de goles.
        Si el motor no puede estimar un mercado, lo omite en lugar de asignarle
        una probabilidad genérica.
        """
        performance = match.performance or {}
        home = LiveOpportunityEngineV2._features(performance, "home")
        away = LiveOpportunityEngineV2._features(performance, "away")
        hs, aw = int(match.home_score or 0), int(match.away_score or 0)
        lh, la = LiveOpportunityEngineV2._lambdas(home, away, elapsed)
        probabilities = LiveOpportunityEngineV2._probabilities(hs, aw, lh, la)
        candidates = []
        seen = set()

        def identity(item):
            return (
                LiveOpportunityEngineVPro._norm(item.get("market")),
                LiveOpportunityEngineVPro._norm(item.get("selection")),
                LiveOpportunityEngineVPro._norm(item.get("line")),
            )

        # Recorre cada cuota, no solo las oportunidades que V.Pro/V2 dejaron
        # entre sus cinco/diez mejores. Así 1X, empate, BTTS y O/U 2.5 también
        # llegan al filtro prudente de V.Pro 1.1.
        for odd in match.odds or []:
            # Una combinada necesita una probabilidad conjunta; no reutilizar P(1X), P(over), etc.
            if cls._is_combination_market(odd.get("market_name"), odd.get("name")):
                continue
            price = LiveOpportunityEngineVPro._num(odd.get("price"))
            if price is None or price <= 1:
                continue
            key = LiveOpportunityEngineV2._market_key(
                odd.get("market_name"), odd.get("name"), odd.get("line"),
                match.home_team, match.away_team,
            )
            if not key:
                continue
            model_probability = probabilities.get(key)
            if model_probability is None:
                model_probability = {
                    "dc_1x": probabilities["home"] + probabilities["draw"],
                    "dc_12": probabilities["home"] + probabilities["away"],
                    "dc_x2": probabilities["draw"] + probabilities["away"],
                }.get(key)
            if model_probability is None:
                continue
            support, contra, coverage, strength = LiveOpportunityEngineV2._signals(
                key, home, away, hs, aw, elapsed
            )
            item = {
                "market": odd.get("market_name", ""),
                "selection": odd.get("name", ""),
                "line": odd.get("line"),
                "price": price,
                "model_probability": round(max(0.0, min(1.0, model_probability)), 4),
                "implied_probability": round(1.0 / price, 4),
                "edge": round(model_probability - 1.0 / price, 4),
                "edge_pct": round((model_probability - 1.0 / price) * 100, 2),
                "confidence": round(min(.95, .30 + .35 * coverage + .20 * strength + .10 * float(match.mapping_confidence or 0)), 3),
                "signal_strength": "fuerte" if strength >= .72 else ("moderada" if strength >= .55 else "débil"),
                "supporting_factors": support,
                "contradicting_factors": contra,
                "data_coverage": round(coverage, 3),
                "model": "vpro11_market_scan_v2_probability",
            }
            ident = identity(item)
            if ident not in seen:
                seen.add(ident)
                candidates.append(item)

        # Añade líneas de totales y dobles oportunidades que el parser básico
        # de V2 no contempla (por ejemplo, menos de 3.5 goles o selección por nombre).
        try:
            extended = LiveOpportunityEngineVPro._extended_opportunities(match, elapsed)
        except (AttributeError, TypeError, ValueError):
            extended = []
        for item in extended:
            if cls._is_combination_market(item.get("market"), item.get("selection")):
                continue
            ident = identity(item)
            if ident not in seen:
                seen.add(ident)
                candidates.append(dict(item))

        return candidates

    @classmethod
    def evaluate(cls, match) -> List[Dict[str, Any]]:
        if getattr(match, "is_finished", False):
            return []

        try:
            elapsed = LiveOpportunityEngineV2._elapsed(match.minute, match.period)
            mapping_confidence = float(getattr(match, "mapping_confidence", 0) or 0)
            data_quality = float(getattr(match, "data_quality", 0) or 0)
        except (TypeError, ValueError):
            return []

        if elapsed < cls.MIN_MINUTE or elapsed > cls.MAX_MINUTE:
            return []
        if mapping_confidence < cls.MIN_MAPPING_CONFIDENCE:
            return []
        if data_quality < cls.MIN_DATA_QUALITY:
            return []

        reference = LiveOpportunityEngineVPro._reference(match)
        if not isinstance(reference, dict):
            return []
        try:
            favorite_price = float(reference.get("price"))
        except (TypeError, ValueError):
            return []
        if not cls.MIN_FAVORITE_ODDS <= favorite_price <= cls.MAX_FAVORITE_ODDS:
            return []
        if reference.get("source") == "favorito_provisional_por_estadisticas_live":
            return []

        performance = match.performance or {}
        home_pos = LiveOpportunityEngineVPro._stat(performance, "home", "ball_possession", "possession")
        away_pos = LiveOpportunityEngineVPro._stat(performance, "away", "ball_possession", "possession")
        home_shots_on = LiveOpportunityEngineVPro._stat(performance, "home", "shots_on_target", "shots_on_goal")
        away_shots_on = LiveOpportunityEngineVPro._stat(performance, "away", "shots_on_target", "shots_on_goal")
        home_big = LiveOpportunityEngineVPro._stat(performance, "home", "big_chances", "big_chances_created")
        away_big = LiveOpportunityEngineVPro._stat(performance, "away", "big_chances", "big_chances_created")
        xg = LiveOpportunityEngineVPro._xg_check(match)

        side = reference.get("side")
        fav_home = side == "home"
        fav_stats = {
            "shots_on": home_shots_on if fav_home else away_shots_on,
            "big": home_big if fav_home else away_big,
            "xg": xg.get("home") if fav_home else xg.get("away"),
        }
        rival_stats = {
            "shots_on": away_shots_on if fav_home else home_shots_on,
            "big": away_big if fav_home else home_big,
            "xg": xg.get("away") if fav_home else xg.get("home"),
        }

        # La contradicción del favorito no debe bloquear todo el partido:
        # VP11 también debe poder evaluar mercados que cubren al rival/empate.
        coherence_conflict = False
        possession_gap = None
        if home_pos is not None and away_pos is not None:
            possession_gap = (home_pos - away_pos) * (1 if fav_home else -1)
        if possession_gap is not None and abs(possession_gap) >= 11:
            # possession_gap positivo = favorito domina; negativo = rival domina.
            dominant_stats = fav_stats if possession_gap > 0 else rival_stats
            other_stats = rival_stats if possession_gap > 0 else fav_stats
            corroborating = []
            contradicting = []
            for key in ("shots_on", "big", "xg"):
                dv, ov = dominant_stats[key], other_stats[key]
                if dv is None or ov is None:
                    continue
                if dv > ov:
                    corroborating.append(key)
                elif dv < ov:
                    contradicting.append(key)
            fav_score = int(match.home_score or 0) if fav_home else int(match.away_score or 0)
            rival_score = int(match.away_score or 0) if fav_home else int(match.home_score or 0)
            dominant_is_ahead = fav_score > rival_score if possession_gap > 0 else rival_score > fav_score
            if dominant_is_ahead:
                corroborating.append("score")
            coherence_conflict = not corroborating or len(contradicting) >= 2

        # V.Pro original conserva su lista corta; VP11 explora por separado
        # el inventario LIVE completo de mercados que sabe modelar.
        opportunities = cls._all_market_candidates(match, elapsed)
        results = []
        for source in opportunities:
            item = dict(source)
            try:
                price = float(item.get("price") or 0)
                raw_probability = float(item.get("model_probability") or 0)
                edge = raw_probability - (1.0 / price) if price > 1 else -1
            except (TypeError, ValueError):
                continue
            if price <= 1 or not 0 <= raw_probability <= 1:
                continue

            contradictions = list(item.get("contradicting_factors") or [])
            rejection_reasons = []
            if len(contradictions) >= 3:
                rejection_reasons.append("mercado con tres o más contradicciones estadísticas")
            if xg.get("status") in {"estimado", "parcial"} and edge < 0.08:
                rejection_reasons.append("xG estimado/parcial y edge inferior a 8 puntos")

            confidence = float(item.get("confidence") or 0)
            if xg.get("status") in {"estimado", "parcial"}:
                confidence -= 0.06
            if mapping_confidence < 0.90:
                confidence -= 0.04
            if data_quality < 0.60:
                confidence -= 0.03
            confidence = max(0.0, min(0.88, confidence))

            item.update({
                "model": "vpro_1_1_live_calibrated",
                "raw_model_probability": round(raw_probability, 6),
                "model_probability": round(raw_probability, 6),
                "implied_probability": round(1.0 / price, 6),
                "edge": round(edge, 6),
                "edge_pct": round(edge * 100, 2),
                "confidence": round(confidence, 4),
                "vpro11_mapping_confidence": round(mapping_confidence, 3),
                "vpro11_data_quality": round(data_quality, 3),
                "vpro11_minute_window": f"{cls.MIN_MINUTE}-{cls.MAX_MINUTE}",
                "vpro11_possession_gap_favorite": round(possession_gap, 2) if possession_gap is not None else None,
                "vpro11_xg_status": xg.get("status"),
                "vpro11_xg_detail": xg.get("detail"),
                "vpro11_raw_edge": round(edge, 6),
                "vpro11_filters_passed": [
                    "minuto LIVE válido", "mapeo y estadísticas mínimos",
                    "favorito 1X2 entre 1.05 y 1.70", "coherencia posesión/ataque",
                ],
            })
            if coherence_conflict:
                item["vpro11_coherence_warning"] = (
                    "La posesión del favorito contradice los indicadores de producción ofensiva; "
                    "se evalúa cada mercado por separado y no se descarta todo el partido."
                )
            if edge < cls.MIN_EDGE:
                rejection_reasons.append(f"edge {edge * 100:.1f} puntos inferior al mínimo {cls.MIN_EDGE * 100:.1f}")
            if confidence < cls.MIN_CONFIDENCE:
                rejection_reasons.append(f"confianza {confidence * 100:.1f}% inferior al mínimo {cls.MIN_CONFIDENCE * 100:.0f}%")
            item["vpro11_rejection_reason"] = "; ".join(rejection_reasons)
            item["vpro11_eligible"] = not rejection_reasons
            item["reason"] = (
                "V.Pro 1.1 exploró esta cuota LIVE con probabilidad específica del mercado. "
                + ("No apostar: " + item["vpro11_rejection_reason"] + "." if rejection_reasons else
                   "Supera los filtros iniciales; se verificará de nuevo tras calibración histórica.")
            )
            results.append(item)

        results.sort(
            key=lambda item: (
                float(item.get("edge") or 0),
                float(item.get("confidence") or 0),
                float(item.get("vpro_statistical_score") or 0),
            ),
            reverse=True,
        )
        return results[:12]
