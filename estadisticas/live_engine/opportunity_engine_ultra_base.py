"""Shared score-modelable market expansion for the two Ultra experiment motors.

Ultra scans every active Ecuabet odd in the snapshot. It emits a modelled
opportunity only when its outcome can be estimated from the live score and
available match statistics; unsupported player/corner/card props are never
given invented probabilities.
"""
import math
import re
from typing import Any, Dict, List, Optional

from .opportunity_engine import LiveOpportunityEngine
from .opportunity_engine_v11 import LiveOpportunityEngineV11
from .opportunity_engine_v12 import LiveOpportunityEngineV12
from .opportunity_engine_v2 import LiveOpportunityEngineV2


class UltraMarketEvaluator:
    @staticmethod
    def _num(value: Any) -> Optional[float]:
        try:
            return float(str(value).strip().replace(",", ".").replace("%", ""))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _active(odd: Dict[str, Any]) -> bool:
        status = str(odd.get("odd_status") or odd.get("status") or "").casefold()
        return not any(x in status for x in ("suspend", "inactive", "closed", "blocked", "settled", "void"))

    @staticmethod
    def _line(odd: Dict[str, Any]) -> Optional[float]:
        text = f"{odd.get('line') or ''} {odd.get('name') or ''} {odd.get('market_name') or ''}".replace(",", ".")
        found = re.search(r"([+-]?\d+(?:\.\d+)?)", text)
        return float(found.group(1)) if found else None

    @staticmethod
    def _poisson_cdf(k: int, lam: float) -> float:
        if k < 0:
            return 0.0
        return sum(LiveOpportunityEngine._poisson_pmf(i, lam) for i in range(k + 1))

    @classmethod
    def _extended_key(cls, odd, match):
        market = str(odd.get("market_name") or "")
        selection = str(odd.get("name") or "")
        text = f"{market} {selection}".casefold()
        line = cls._line(odd)
        # Common score-derived markets already supported by V1.2.
        # Team totals must be handled before the generic total-goals mapper.
        if any(token in text for token in ("team total", "goles del equipo", "goles equipo", "home team goals", "away team goals", "local total", "visitante total")) and line is not None:
            if abs(line * 2 - round(line * 2)) < 0.001 and not line.is_integer():
                normalized_selection = re.sub(r"\\W+", "", selection.casefold())
                home = re.sub(r"\\W+", "", str(match.home_team or "").casefold())
                away = re.sub(r"\\W+", "", str(match.away_team or "").casefold())
                side = "home" if ("home" in text or "local" in text or (home and (home in normalized_selection or normalized_selection in home))) else (
                    "away" if ("away" in text or "visitante" in text or (away and (away in normalized_selection or normalized_selection in away))) else None
                )
                if side and any(token in text for token in ("over", "under", "más", "mas", "menos")):
                    kind = "over_team" if any(token in text for token in ("over", "más", "mas")) else "under_team"
                    return kind, (side, line)

        # Half-goal handicaps only (no push outcome); selection must identify a side.
        if any(token in text for token in ("handicap", "handicap asiático", "asian handicap", "spread")) and line is not None:
            normalized_selection = re.sub(r"\\W+", "", selection.casefold())
            home = re.sub(r"\\W+", "", str(match.home_team or "").casefold())
            away = re.sub(r"\\W+", "", str(match.away_team or "").casefold())
            side = "home" if ("home" in normalized_selection or "local" in normalized_selection or (home and (home in normalized_selection or normalized_selection in home))) else (
                "away" if ("away" in normalized_selection or "visitante" in normalized_selection or (away and (away in normalized_selection or normalized_selection in away))) else None
            )
            if side and abs(line * 2 - round(line * 2)) < 0.001 and not line.is_integer():
                return "handicap", (side, line)

        key = LiveOpportunityEngineV12._market_key(
            market, selection, odd.get("line"), match.home_team, match.away_team
        )
        if key:
            return key, None

        # All half-goal total lines, including lines beyond the base motors'
        # fixed 2.5 line.
        if any(token in text for token in ("total", "over", "under", "más", "mas", "menos", "goles")) and line is not None:
            if abs(line * 2 - round(line * 2)) < 0.001 and not line.is_integer():
                if any(token in text for token in ("over", "más", "mas", "más de", "mas de")):
                    return "over_total", line
                if any(token in text for token in ("under", "menos", "menos de")):
                    return "under_total", line

        # Team total goals: modelable and settleable from the final score.
        if any(token in text for token in ("team total", "goles del equipo", "goles equipo", "home team goals", "away team goals", "local total", "visitante total")) and line is not None:
            if abs(line * 2 - round(line * 2)) < 0.001 and not line.is_integer():
                normalized_selection = re.sub(r"\W+", "", selection.casefold())
                home = re.sub(r"\W+", "", str(match.home_team or "").casefold())
                away = re.sub(r"\W+", "", str(match.away_team or "").casefold())
                side = "home" if ("home" in text or "local" in text or (home and (home in normalized_selection or normalized_selection in home))) else (
                    "away" if ("away" in text or "visitante" in text or (away and (away in normalized_selection or normalized_selection in away))) else None
                )
                if side and any(token in text for token in ("over", "under", "más", "mas", "menos")):
                    kind = "over_team" if any(token in text for token in ("over", "más", "mas")) else "under_team"
                    return kind, (side, line)

        # Half-goal handicaps only (no push outcome); selection must identify a side.
        if any(token in text for token in ("handicap", "handicap asiático", "asian handicap", "spread")) and line is not None:
            normalized_selection = re.sub(r"\W+", "", selection.casefold())
            home = re.sub(r"\W+", "", str(match.home_team or "").casefold())
            away = re.sub(r"\W+", "", str(match.away_team or "").casefold())
            side = "home" if ("home" in normalized_selection or "local" in normalized_selection or (home and (home in normalized_selection or normalized_selection in home))) else (
                "away" if ("away" in normalized_selection or "visitante" in normalized_selection or (away and (away in normalized_selection or normalized_selection in away))) else None
            )
            if side and abs(line * 2 - round(line * 2)) < 0.001 and not line.is_integer():
                return "handicap", (side, line)
        return None, None

    @classmethod
    def _probability(cls, key, extra, probabilities, hs, aw, lh, la):
        if key in probabilities:
            return probabilities[key]
        if key.startswith(("over_", "under_")) and key not in {"over_total", "under_total", "over_team", "under_team"}:
            try:
                line = float(key.split("_", 1)[1])
            except (TypeError, ValueError):
                line = None
            if line is not None and abs(line * 2 - round(line * 2)) < 0.001 and not line.is_integer():
                total = hs + aw
                needed = math.floor(line - total) + 1
                over = 1.0 if needed <= 0 else 1.0 - cls._poisson_cdf(needed - 1, lh + la)
                return over if key.startswith("over_") else 1.0 - over
        if key in {"over_total", "under_total"}:
            line = float(extra)
            total = hs + aw
            needed = math.floor(line - total) + 1
            over = 1.0 if needed <= 0 else 1.0 - cls._poisson_cdf(needed - 1, lh + la)
            return over if key == "over_total" else 1.0 - over
        if key in {"over_team", "under_team"}:
            side, line = extra
            current = hs if side == "home" else aw
            lam = lh if side == "home" else la
            needed = math.floor(line - current) + 1
            over = 1.0 if needed <= 0 else 1.0 - cls._poisson_cdf(needed - 1, lam)
            return over if key == "over_team" else 1.0 - over
        if key == "handicap":
            side, handicap = extra
            covered = 0.0
            for future_home in range(11):
                ph = LiveOpportunityEngine._poisson_pmf(future_home, lh)
                for future_away in range(11):
                    pa = LiveOpportunityEngine._poisson_pmf(future_away, la)
                    diff = (hs + future_home) - (aw + future_away)
                    adjusted = diff + handicap if side == "home" else -diff + handicap
                    if adjusted > 0:
                        covered += ph * pa
            # Only two-way/Asian half-line handicaps are modelled; no push.
            return covered
        return None

    @classmethod
    def evaluate(cls, match, variant: str) -> List[Dict[str, Any]]:
        if getattr(match, "is_finished", False) or match.home_score is None or match.away_score is None:
            return []

        hs, aw = int(match.home_score or 0), int(match.away_score or 0)
        if variant == "V2U":
            elapsed = LiveOpportunityEngineV2._elapsed(match.minute, match.period)
            home = LiveOpportunityEngineV2._features(match.performance or {}, "home")
            away = LiveOpportunityEngineV2._features(match.performance or {}, "away")
            lh, la = LiveOpportunityEngineV2._lambdas(home, away, elapsed)
        else:
            elapsed = LiveOpportunityEngine._elapsed_minutes(match.minute, match.period)
            lh, la = LiveOpportunityEngine._remaining_lambda(match.performance or {}, elapsed)

        probabilities = LiveOpportunityEngineV12._probabilities(hs, aw, lh, la)
        results = []
        for odd in getattr(match, "odds", []) or []:
            if not cls._active(odd):
                continue
            price = cls._num(odd.get("price"))
            if price is None or price <= 1:
                continue
            key, extra = cls._extended_key(odd, match)
            if not key:
                continue
            probability = cls._probability(key, extra, probabilities, hs, aw, lh, la)
            if probability is None or not 0 < probability < 1:
                continue
            implied = 1.0 / price
            edge = probability - implied

            if variant == "V11U":
                raw_probability = probability
                calibrated = LiveOpportunityEngineV11._calibrate_probability(raw_probability, elapsed)
                raw_confidence = min(
                    0.95,
                    max(0.0, 0.50 + min(0.20, edge)
                        + min(0.15, float(getattr(match, "data_quality", 0) or 0) * 0.15)
                        + min(0.10, float(getattr(match, "mapping_confidence", 0) or 0) * 0.10),
                    ),
                )
                temporal = LiveOpportunityEngineV11._temporal_factor(elapsed)
                confidence = 0.50 + (raw_confidence - 0.50) * 0.78
                confidence = 0.50 + (confidence - 0.50) * temporal
                if raw_probability >= 0.90 and elapsed < 30:
                    confidence -= 0.08
                elif raw_probability >= 0.95:
                    confidence -= 0.04
                probability = min(0.97, max(0.03, calibrated))
                confidence = min(0.94, max(0.35, confidence))
                edge = probability - implied
                model_name = "v1_1_ultra_calibrated"
                reason = f"V1.1 Ultra: calibración V1.1 hacia 50%, control temporal {temporal:.2f}; analiza mercado LIVE modelable. Edge {edge*100:+.1f} puntos."
                raw_fields = {"raw_model_probability": round(raw_probability, 4), "temporal_factor": round(temporal, 3), "calibration": "shrink_to_50_v1_1_ultra"}
            else:
                signal_key = key if key in {"home", "draw", "away", "over_2_5", "under_2_5", "btts_yes", "btts_no"} else (
                    "over_2_5" if key in {"over_total", "under_total"} and extra == 2.5 else key
                )
                support, contra, coverage, strength = LiveOpportunityEngineV2._signals(
                    signal_key, home, away, hs, aw, elapsed
                )
                confidence = min(0.95, max(0.0,
                    0.30 + 0.35 * coverage + 0.20 * strength
                    + 0.10 * float(getattr(match, "mapping_confidence", 0) or 0)
                ))
                model_name = "v2_ultra_multi_factor"
                reason = f"V2.Ultra: evaluación multi-factor LIVE; mercado score-modelable. Edge {edge*100:+.1f} puntos."
                raw_fields = {"supporting_factors": support, "contradicting_factors": contra, "data_coverage": round(coverage, 3)}

            results.append({
                "market": odd.get("market_name", ""),
                "selection": odd.get("name", ""),
                "line": odd.get("line"),
                "price": price,
                "model_probability": round(probability, 4),
                "implied_probability": round(implied, 6),
                "edge": round(edge, 6),
                "edge_pct": round(edge * 100, 2),
                "confidence": round(confidence, 3),
                "signal_strength": "fuerte" if confidence >= 0.72 else ("moderada" if confidence >= 0.55 else "débil"),
                "ultra_market_key": key,
                "model": model_name,
                "reason": reason,
                **raw_fields,
            })

        results.sort(key=lambda x: (x["edge"], x["confidence"], x["price"]), reverse=True)
        # Keep a broad audit list; the lab independently applies the Ultra level gate.
        return results[:100]
