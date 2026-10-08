from typing import Any, Dict

from ..ecuabet_client import EcuabetClient
from ..flashscore_client import FlashscoreClient
from .match_mapper import MatchMapper, MatchMappingError
from .models import LiveMatch
from .opportunity_engine import LiveOpportunityEngine
from .opportunity_engine_v2 import LiveOpportunityEngineV2


class LiveMatchCollector:
    """Une un evento LIVE de Ecuabet con datos LIVE de Flashscore."""

    def __init__(self, ecuabet_client=None, flashscore_client=None, mapper=None):
        self.ecuabet = ecuabet_client or EcuabetClient()
        self.flashscore = flashscore_client or FlashscoreClient()
        self.mapper = mapper or MatchMapper()

    def construir(self, ecuabet_event_id: int, flashscore_event_id: str) -> LiveMatch:
        ecuabet = self._obtener_ecuabet_evento(ecuabet_event_id)
        return self._construir_desde_evento(ecuabet, flashscore_event_id, 1.0)

    def construir_automatico(self, ecuabet_event_id: int) -> LiveMatch:
        """Encuentra automáticamente el ID Flashscore y construye el LiveMatch."""
        ecuabet = self._obtener_ecuabet_evento(ecuabet_event_id)
        mapping = self.mapper.mapear(ecuabet, self.flashscore)

        if not mapping.get("matched"):
            reason = mapping.get("reason", "sin coincidencia")
            confidence = mapping.get("confidence", 0.0)
            raise MatchMappingError(
                f"No se pudo vincular Ecuabet {ecuabet_event_id} con Flashscore "
                f"(confianza={confidence:.2f}, motivo={reason})."
            )

        return self._construir_desde_evento(
            ecuabet,
            mapping["flashscore_event_id"],
            mapping["confidence"],
        )

    def mapear_automaticamente(self, ecuabet_event_id: int) -> Dict[str, Any]:
        """Expone el resultado del MatchMapper para diagnóstico/UI."""
        ecuabet = self._obtener_ecuabet_evento(ecuabet_event_id)
        return self.mapper.mapear(ecuabet, self.flashscore)

    def _construir_desde_evento(
        self,
        ecuabet: Dict[str, Any],
        flashscore_event_id: str,
        mapping_confidence: float,
    ) -> LiveMatch:
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

        stats = flashscore.get("stats", {})
        raw_event = flashscore.get("raw_event") or {}
        match_status, is_finished = self._extract_match_status(
            raw_event,
            ecuabet.get("status"),
            ecuabet.get("ls"),
            ecuabet.get("liveTime"),
        )

        # Nunca damos por terminado un partido solo por un snapshot de
        # GraphQL/Ecuabet. Si detectamos un posible final, lo confirmamos
        # contra el feed diario de Flashscore (AB=3) y tomamos de allí el
        # marcador definitivo.
        final_feed = None
        if is_finished:
            try:
                final_feed = self.flashscore.obtener_partido_por_id(flashscore_event_id)
            except Exception:
                final_feed = None

            if not (final_feed and final_feed.get("finished")):
                match_status = "LIVE"
                is_finished = False
            elif final_feed.get("home_score") is not None and final_feed.get("away_score") is not None:
                score = [
                    final_feed.get("home_score"),
                    final_feed.get("away_score"),
                ]
                match_status = "FINISHED"
                is_finished = True
            else:
                # Estado final sin marcador verificable: no liquidar todavía.
                match_status = "FINISHED_PENDING_SCORE"
                is_finished = False

        match = LiveMatch(
            ecuabet_event_id=int(ecuabet.get("id")),
            flashscore_event_id=flashscore.get("flashscore_event_id"),
            home_team=self._participant_name(home) or self._split_ecuabet_name(ecuabet)[0],
            away_team=self._participant_name(away) or self._split_ecuabet_name(ecuabet)[1],
            league=(ecuabet.get("champ") or {}).get("name", ""),
            country=(ecuabet.get("category") or {}).get("name", ""),
            start_time=ecuabet.get("startDate"),
            minute=ecuabet.get("liveTime"),
            period=ecuabet.get("ls"),
            home_score=score[0] if len(score) > 0 else None,
            away_score=score[1] if len(score) > 1 else None,
            odds=self._flatten_odds(ecuabet.get("markets", [])),
            performance=stats,
            mapping_confidence=mapping_confidence,
            data_quality=self._calculate_data_quality(stats),
        )
        # Si el proveedor confirma FINAL, los motores dejan de generar
        # oportunidades nuevas. El experimento solo debe liquidar las abiertas.
        if match.is_finished:
            match.opportunities = []
            match.opportunities_v2 = []
        else:
            match.opportunities = LiveOpportunityEngine.evaluate(match)
            match.opportunities_v2 = LiveOpportunityEngineV2.evaluate(match)
        return match

    @classmethod
    def _extract_match_status(cls, raw_event, ecuabet_status=None, ecuabet_period=None, ecuabet_minute=None):
        """Normaliza el estado del partido y determina si ya terminó."""
        raw_event = raw_event if isinstance(raw_event, dict) else {}
        status = raw_event.get("status")
        candidates = []

        def collect(value):
            if isinstance(value, dict):
                for k, v in value.items():
                    if str(k).lower() in {
                        "type", "code", "short", "long", "name", "status",
                        "period", "periodname", "description",
                    }:
                        candidates.append(str(v))
                    if isinstance(v, (dict, list)):
                        collect(v)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
            elif value is not None:
                candidates.append(str(value))

        collect(status)
        if not candidates:
            candidates.extend(
                str(value) for value in (
                    raw_event.get("statusCode"),
                    raw_event.get("statusType"),
                    raw_event.get("statusName"),
                    ecuabet_status,
                    ecuabet_period,
                    ecuabet_minute,
                ) if value is not None
            )

        normalized = " ".join(candidates).strip()
        lowered = normalized.casefold()
        finished_tokens = (
            "finished", "final", "finalizado", "terminado",
            "full time", "match finished", "after extra time",
            "after penalties", "ft",
        )
        cancelled_tokens = (
            "cancelled", "canceled", "cancelado", "abandoned", "suspendido"
        )
        is_finished = any(token in lowered for token in finished_tokens)
        if any(token in lowered for token in cancelled_tokens):
            is_finished = True
        return normalized or None, is_finished

    def construir_desde_flashscore(
        self,
        flashscore_event_id: str,
        ecuabet_event_id: int = None,
        home_team: str = "",
        away_team: str = "",
    ) -> LiveMatch:
        """Construye un snapshot actual/final solo desde Flashscore."""
        flashscore = self.flashscore.obtener_live_match(flashscore_event_id)
        raw_event = flashscore.get("raw_event") or {}
        feed_match = self.flashscore.obtener_partido_por_id(flashscore_event_id)
        if feed_match:
            raw_event = {**raw_event, "feed_status": feed_match.get("status")}
        participants = raw_event.get("eventParticipants", []) or []
        home = next(
            (p for p in participants if ((p.get("type") or {}).get("side") or "").upper() == "HOME"),
            {},
        )
        away = next(
            (p for p in participants if ((p.get("type") or {}).get("side") or "").upper() == "AWAY"),
            {},
        )
        home_name = self._participant_name(home) or home_team
        away_name = self._participant_name(away) or away_team
        status, is_finished = self._extract_match_status(raw_event)
        if feed_match and feed_match.get("finished"):
            status = "FINISHED"
            is_finished = True

        # Para liquidar un experimento terminado, el marcador del feed
        # diario de Flashscore tiene prioridad sobre GraphQL/raw_event:
        # Ecuabet puede haber retirado el evento LIVE o conservar un snapshot
        # anterior (por ejemplo 1-0) mientras el resultado real ya es 2-1.
        if feed_match and feed_match.get("home_score") is not None and feed_match.get("away_score") is not None:
            home_score = feed_match.get("home_score")
            away_score = feed_match.get("away_score")
        else:
            score = raw_event.get("score")
            if isinstance(score, dict):
                home_score = score.get("home")
                if home_score is None:
                    home_score = score.get("currentHome")
                away_score = score.get("away")
                if away_score is None:
                    away_score = score.get("currentAway")
            elif isinstance(score, list):
                home_score = score[0] if len(score) > 0 else None
                away_score = score[1] if len(score) > 1 else None
            else:
                home_score = raw_event.get("homeScore")
                away_score = raw_event.get("awayScore")

        stats = flashscore.get("stats", {})
        match = LiveMatch(
            ecuabet_event_id=ecuabet_event_id,
            flashscore_event_id=flashscore.get("flashscore_event_id"),
            home_team=home_name,
            away_team=away_name,
            start_time=None,
            minute=raw_event.get("minute") or raw_event.get("time"),
            period=raw_event.get("period"),
            match_status=status,
            is_finished=is_finished,
            home_score=home_score,
            away_score=away_score,
            odds=[],
            performance=stats,
            mapping_confidence=1.0,
            data_quality=self._calculate_data_quality(stats),
        )
        if match.is_finished:
            match.opportunities = []
            match.opportunities_v2 = []
        else:
            match.opportunities = LiveOpportunityEngine.evaluate(match)
            match.opportunities_v2 = LiveOpportunityEngineV2.evaluate(match)
        return match

    def _obtener_ecuabet_evento(self, event_id: int) -> Dict[str, Any]:
        payload = self.ecuabet._request(
            "GET",
            "GetLivenow",
            {"eventCount": 0, "sportId": 66},
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
        return round(min(1.0, available / 10.0), 3)
