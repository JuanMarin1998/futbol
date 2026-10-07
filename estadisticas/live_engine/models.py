from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class LiveMatch:
    """Modelo común que reunirá Ecuabet + Flashscore."""

    ecuabet_event_id: Optional[int] = None
    flashscore_event_id: Optional[str] = None

    home_team: str = ""
    away_team: str = ""
    league: str = ""
    country: str = ""

    start_time: Optional[str] = None
    minute: Optional[str] = None
    period: Optional[str] = None
    home_score: Optional[int] = None
    away_score: Optional[int] = None

    odds: list = field(default_factory=list)
    performance: Dict[str, Any] = field(default_factory=dict)
    events: list = field(default_factory=list)
    opportunities: list = field(default_factory=list)
    opportunities_v2: list = field(default_factory=list)

    mapping_confidence: float = 0.0
    data_quality: float = 0.0

    def to_dict(self):
        return {
            "ecuabet_event_id": self.ecuabet_event_id,
            "flashscore_event_id": self.flashscore_event_id,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "league": self.league,
            "country": self.country,
            "start_time": self.start_time,
            "minute": self.minute,
            "period": self.period,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "odds": self.odds,
            "performance": self.performance,
            "events": self.events,
            "opportunities": self.opportunities,
            "opportunities_v2": self.opportunities_v2,
            "mapping_confidence": self.mapping_confidence,
            "data_quality": self.data_quality,
        }
