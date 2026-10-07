from typing import Any, Dict, Optional

from ..ecuabet_client import EcuabetClient
from ..flashscore_client import FlashscoreClient
from .models import LiveMatch


class LiveMatchCollector:
    """
    Une un evento LIVE de Ecuabet con las estadísticas del evento Flashscore.

    El mapeo automático de IDs se implementará aparte; mientras tanto, el
    collector recibe ambos IDs para evitar asociaciones incorrectas.
    """

    def __init__(self, ecuabet_client=None, flashscore_client=None):
        self.ecuabet = ecuabet_client or EcuabetClient()
        self.flashscore = flashscore_client or FlashscoreClient()

    def construir(
        self,
        ecuabet_event_id: int,
        flashscore_event_id: str,
    ) -> LiveMatch:
        ecuabet = self._obtener_ecuabet_evento(ecuabet_event_id)
        flashscore = self.flashscore.obtener_live_match(flashscore_event_id)

        event = flashscore.get("raw_event") or {}
        participants = event.get("eventParticipants", []) or []

        home = next(
            (
                p for p in participants
                if ((p.get("type") or {}).get("side") or "").upper() == "HOME"
            ),
            {},
        )
        away = next(
            (
                p for p in participants
                if ((p.get("type") or {}).get("side") or "").upper() == "AWAY"
            ),
            {},
        )

        score = ecuabet.get("score") or [None, None]
        if not isinstance(score, list):
            score = [None, None]

        match = LiveMatch(
            ecuabet_event_id=int(ecuabet.get("id")),
            flashscore_event_id=flashscore.get("flashscore_event_id"),
            home_team=self._participant_name(home) or self._split_ecuabet_name(ecuabet)[0],
            away_team=self._participant_name(away) or self._split_ecuabet_name(ecuabet)[1],
            league=(ecuabet.get("champ") or {}).get("name", ""),
            country=(ecuabet.get("category") or {}).get("name", ""),
            start_time=ecuabet.get("start_date"),
            minute=ecuabet.get("live_time"),
            period=ecuabet.get("live_status"),
            home_score=score[0] if len(score) > 0 else None,
            away_score=score[1] if len(score) > 1 else None,
            odds=self._flatten_odds(ecuabet.get("markets", [])),
            performance=flashscore.get("stats", {}),
            mapping_confidence=1.0,
            data_quality=self._calculate_data_quality(flashscore.get("stats", {})),
        )
        return match

    def _obtener_ecuabet_evento(self, event_id: int) -> Dict[str, Any]:
        payload = self.ecuabet._request(
            "GET",
            "GetLivenow",
            {
                "eventCount": 0,
                "sportId": 66,
            },
        )
        event = next(
            (
                item for item in payload.get("events", []) or []
                if int(item.get("id", -1)) == int(event_id)
            ),
            None,
        )
        if not event:
            raise RuntimeError(f"No se encontró el evento LIVE {event_id} en Ecuabet.")

        markets = {
            int(m["id"]): m
            for m in payload.get("markets", []) or []
            if m.get("id") is not None
        }
        odds = {
            int(o["id"]): o
            for o in payload.get("odds", []) or []
            if o.get("id") is not None
        }
        competitors = {
            int(c["id"]): c
            for c in payload.get("competitors", []) or []
            if c.get("id") is not None
        }
        champs = {
            int(c["id"]): c
            for c in payload.get("champs", []) or []
            if c.get("id") is not None
        }
        categories = {
            int(c["id"]): c
            for c in payload.get("categories", []) or []
            if c.get("id") is not None
        }

        event["markets"] = []
        for market_id in event.get("marketIds", []) or []:
            market = markets.get(int(market_id))
            if not market:
                continue
            selections = []
            for odd_id in market.get("oddIds", []) or []:
                odd = odds.get(int(odd_id))
                if not odd:
                    continue
                selections.append({
                    "id": odd.get("id"),
                    "type_id": odd.get("typeId"),
                    "name": odd.get("name", ""),
                    "price": odd.get("price"),
                    "odd_status": odd.get("oddStatus"),
                })
            event["markets"].append({
                "id": market.get("id"),
                "type_id": market.get("typeId"),
                "name": market.get("name", ""),
                "line": market.get("sv") or market.get("sn"),
                "selections": selections,
            })

        event["competitors"] = [
            competitors.get(int(cid), {"id": cid})
            for cid in event.get("competitorIds", []) or []
        ]
        event["champ"] = champs.get(int(event.get("champId", -1)), {})
        event["category"] = categories.get(int(event.get("catId", -1)), {})
        return event

    @staticmethod
    def _participant_name(participant: Dict[str, Any]) -> str:
        return (
            participant.get("name")
            or participant.get("shortName")
            or participant.get("slug")
            or ""
        )

    @staticmethod
    def _split_ecuabet_name(event: Dict[str, Any]):
        name = str(event.get("name") or "")
        parts = name.split(" vs. ", 1)
        if len(parts) != 2:
            parts = name.split(" vs ", 1)
        return parts if len(parts) == 2 else [name, ""]

    @staticmethod
    def _flatten_odds(markets):
        result = []
        for market in markets or []:
            for selection in market.get("selections", []) or []:
                result.append({
                    "market_id": market.get("id"),
                    "market_type_id": market.get("type_id"),
                    "market_name": market.get("name", ""),
                    "line": market.get("line"),
                    **selection,
                })
        return result

    @staticmethod
    def _calculate_data_quality(stats: Dict[str, Any]) -> float:
        home = stats.get("home") or {}
        away = stats.get("away") or {}
        available = len(set(home) | set(away))
        if available == 0:
            return 0.0
        # Por ahora medimos cobertura, no calidad predictiva.
        return round(min(1.0, available / 10.0), 3)
