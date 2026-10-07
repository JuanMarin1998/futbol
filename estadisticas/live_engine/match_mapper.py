import os
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from ..flashscore_client import FlashscoreAPIError, FlashscoreClient


class MatchMappingError(RuntimeError):
    """No se pudo vincular un partido de Ecuabet con Flashscore."""


class MatchMapper:
    """
    Vincula un partido LIVE de Ecuabet con el mismo partido en Flashscore.

    La lista de candidatos se obtiene del feed LIVE de Flashscore y después
    se compara local, visitante y hora de inicio. Nunca devuelve un candidato
    por debajo del umbral configurado para evitar asociaciones incorrectas.
    """

    MIN_CONFIDENCE = float(os.getenv("FLASHSCORE_MATCH_MIN_CONFIDENCE", "0.78"))
    MIN_MARGIN = float(os.getenv("FLASHSCORE_MATCH_MIN_MARGIN", "0.04"))

    @staticmethod
    def _normalize_name(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.lower().replace("&", " and ")
        text = re.sub(r"\b(fc|cf|sc|cd|ac|afc|club|football|futbol|deportivo|sporting)\b", " ", text)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _team_similarity(cls, left: Any, right: Any) -> float:
        a = cls._normalize_name(left)
        b = cls._normalize_name(right)
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0

        ratio = SequenceMatcher(None, a, b).ratio()
        at = set(a.split())
        bt = set(b.split())
        overlap = len(at & bt) / max(1, min(len(at), len(bt)))

        # Ej.: "Vinotinto del Ecuador" frente a "Vinotinto".
        compact = 0.0
        if len(a) >= 5 and len(b) >= 5 and (a in b or b in a):
            compact = 0.90

        return round(max(ratio, overlap * 0.92, compact), 4)

    @staticmethod
    def _parse_time(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            if text.isdigit():
                return datetime.fromtimestamp(int(text), tz=timezone.utc)
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def _time_similarity(cls, ecuabet_start: Any, flashscore_start: Any) -> float:
        a = cls._parse_time(ecuabet_start)
        b = cls._parse_time(flashscore_start)
        if not a or not b:
            return 0.0
        minutes = abs((a - b).total_seconds()) / 60.0
        if minutes <= 10:
            return 1.0
        if minutes <= 30:
            return 0.95
        if minutes <= 60:
            return 0.85
        if minutes <= 180:
            return 0.65
        if minutes <= 360:
            return 0.35
        return 0.0

    @classmethod
    def _candidate_score(cls, ecuabet_event: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
        competitors = ecuabet_event.get("competitors") or []
        home = (competitors[0] if len(competitors) > 0 else {}).get("name", "")
        away = (competitors[1] if len(competitors) > 1 else {}).get("name", "")

        home_score = cls._team_similarity(home, candidate.get("home_team"))
        away_score = cls._team_similarity(away, candidate.get("away_team"))
        reverse_home = cls._team_similarity(home, candidate.get("away_team"))
        reverse_away = cls._team_similarity(away, candidate.get("home_team"))
        direct = (home_score + away_score) / 2
        reversed_score = (reverse_home + reverse_away) / 2

        if reversed_score > direct:
            home_score, away_score = reverse_home, reverse_away
            team_score = reversed_score
            orientation = "reversed"
        else:
            team_score = direct
            orientation = "direct"

        time_score = cls._time_similarity(
            ecuabet_event.get("startDate"),
            candidate.get("start_time"),
        )
        confidence = round(team_score * 0.84 + time_score * 0.16, 4)

        return {
            "flashscore_event_id": candidate.get("event_id"),
            "home_team": candidate.get("home_team", ""),
            "away_team": candidate.get("away_team", ""),
            "start_time": candidate.get("start_time"),
            "tournament": candidate.get("tournament", ""),
            "home_score": home_score,
            "away_score": away_score,
            "team_score": round(team_score, 4),
            "time_score": round(time_score, 4),
            "confidence": confidence,
            "orientation": orientation,
        }

    @classmethod
    def mapear(cls, ecuabet_event: Dict[str, Any], flashscore_client: Optional[FlashscoreClient] = None) -> Dict[str, Any]:
        client = flashscore_client or FlashscoreClient()
        try:
            candidates = client.obtener_partidos_live()
        except Exception as exc:
            raise MatchMappingError(f"No se pudo obtener la lista LIVE de Flashscore: {exc}") from exc

        scored = [
            cls._candidate_score(ecuabet_event, candidate)
            for candidate in candidates
            if candidate.get("event_id")
        ]
        scored.sort(key=lambda item: item["confidence"], reverse=True)

        if not scored:
            return {
                "matched": False,
                "flashscore_event_id": None,
                "confidence": 0.0,
                "reason": "Flashscore no devolvió candidatos LIVE.",
                "candidates": [],
            }

        best = scored[0]
        second = scored[1] if len(scored) > 1 else None
        margin = round(best["confidence"] - (second["confidence"] if second else 0.0), 4)

        team_ok = best["home_score"] >= 0.55 and best["away_score"] >= 0.55
        accepted = (
            team_ok
            and best["confidence"] >= cls.MIN_CONFIDENCE
            and (second is None or margin >= cls.MIN_MARGIN)
        )

        return {
            "matched": accepted,
            "flashscore_event_id": best["flashscore_event_id"] if accepted else None,
            "confidence": best["confidence"],
            "margin": margin,
            "reason": "match_confirmed" if accepted else "confidence_or_margin_too_low",
            "candidate": best,
            "candidates": scored[:5],
        }
