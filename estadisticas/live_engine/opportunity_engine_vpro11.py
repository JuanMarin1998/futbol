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

        # Una ventaja de posesión >=11 puntos no basta: debe ir acompañada de
        # producción ofensiva, y no puede contradecirse en dos indicadores clave.
        possession_gap = None
        if home_pos is not None and away_pos is not None:
            possession_gap = (home_pos - away_pos) * (1 if fav_home else -1)
        if possession_gap is not None and possession_gap >= 11:
            corroborating = []
            contradicting = []
            for key in ("shots_on", "big", "xg"):
                fv, rv = fav_stats[key], rival_stats[key]
                if fv is None or rv is None:
                    continue
                if fv > rv:
                    corroborating.append(key)
                elif fv < rv:
                    contradicting.append(key)
            fav_score = int(match.home_score or 0) if fav_home else int(match.away_score or 0)
            rival_score = int(match.away_score or 0) if fav_home else int(match.home_score or 0)
            if fav_score > rival_score:
                corroborating.append("score")
            if not corroborating or len(contradicting) >= 2:
                return []

        opportunities = LiveOpportunityEngineVPro.evaluate(match)
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
            if len(contradictions) >= 3:
                continue
            if xg.get("status") in {"estimado", "parcial"} and edge < 0.08:
                continue

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
            if edge < cls.MIN_EDGE or confidence < cls.MIN_CONFIDENCE:
                continue
            item["reason"] = (
                "V.Pro 1.1: señal LIVE filtrada por calidad de datos, cuota de referencia, "
                "coherencia entre posesión y producción ofensiva; la probabilidad se calibrará "
                "solo si existe muestra histórica comparable suficiente."
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
        return results[:5]
