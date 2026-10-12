from typing import Any, Dict
import logging

from ..ecuabet_client import EcuabetClient
from ..flashscore_client import FlashscoreClient
from .match_mapper import MatchMapper, MatchMappingError
from .models import LiveMatch
from .flashscore_context import FlashscoreContextProvider
from .opportunity_engine import LiveOpportunityEngine
from .opportunity_engine_v2 import LiveOpportunityEngineV2
from .opportunity_engine_v11 import LiveOpportunityEngineV11
from .opportunity_engine_v12 import LiveOpportunityEngineV12
from .opportunity_engine_v21 import LiveOpportunityEngineV21
from .opportunity_engine_v22 import LiveOpportunityEngineV22
from .opportunity_engine_v3 import LiveOpportunityEngineV3
from .opportunity_engine_v2_ultra import LiveOpportunityEngineV2Ultra
from .opportunity_engine_v11_ultra import LiveOpportunityEngineV11Ultra
from .opportunity_engine_vpro import LiveOpportunityEngineVPro
from .opportunity_engine_vpro11 import LiveOpportunityEngineVPro11
from ..models import LiveExperiment
from .pattern_lab import record_match_snapshot

logger = logging.getLogger(__name__)


class LiveMatchCollector:
    """Une un evento LIVE de Ecuabet con datos LIVE de Flashscore."""

    def __init__(self, ecuabet_client=None, flashscore_client=None, mapper=None, context_provider=None):
        self.ecuabet = ecuabet_client or EcuabetClient()
        self.flashscore = flashscore_client or FlashscoreClient()
        self.mapper = mapper or MatchMapper()
        self.context_provider = context_provider or FlashscoreContextProvider()

    def construir(self, ecuabet_event_id: int, flashscore_event_id: str) -> LiveMatch:
        ecuabet = self._obtener_ecuabet_evento(ecuabet_event_id)
        return self._construir_desde_evento(ecuabet, flashscore_event_id, 1.0)

    def construir_automatico(self, ecuabet_event_id: int) -> LiveMatch:
        """Encuentra automáticamente el ID Flashscore y construye el LiveMatch."""
        ecuabet = self._obtener_ecuabet_evento(ecuabet_event_id)
        mapping = self.mapper.mapear(ecuabet, self.flashscore)

        if not mapping.get("matched"):
            # Respaldo seguro: si Flashscore no tiene una coincidencia fiable,
            # seguimos con el snapshot propio de Ecuabet. Nunca usamos el
            # candidato aproximado, porque podría pertenecer a otro partido.
            logger.warning(
                "Sin vínculo Flashscore fiable para Ecuabet %s; usando respaldo Ecuabet. "
                "Confianza=%s motivo=%s",
                ecuabet_event_id,
                mapping.get("confidence", 0.0),
                mapping.get("reason", "sin coincidencia"),
            )
            return self._construir_solo_ecuabet(ecuabet)

        return self._construir_desde_evento(
            ecuabet,
            mapping["flashscore_event_id"],
            mapping["confidence"],
        )

    @staticmethod
    def _parse_ecuabet_score(event: Dict[str, Any]):
        """Extrae el marcador de Ecuabet si el payload realmente lo incluye."""
        score = event.get("score") or event.get("currentScore") or event.get("scores")
        home = away = None
        if isinstance(score, dict):
            home = score.get("home", score.get("homeScore", score.get("currentHome")))
            away = score.get("away", score.get("awayScore", score.get("currentAway")))
        elif isinstance(score, (list, tuple)):
            home = score[0] if len(score) > 0 else None
            away = score[1] if len(score) > 1 else None
        if home is None:
            home = event.get("homeScore", event.get("currentHomeScore", event.get("scoreHome")))
        if away is None:
            away = event.get("awayScore", event.get("currentAwayScore", event.get("scoreAway")))

        def number(value):
            if isinstance(value, dict):
                value = value.get("current") or value.get("value") or value.get("score")
            try:
                parsed = int(value)
                return parsed if parsed >= 0 else None
            except (TypeError, ValueError):
                return None

        return number(home), number(away)

    def _construir_solo_ecuabet(self, ecuabet: Dict[str, Any]) -> LiveMatch:
        """Crea un snapshot sin inventar datos Flashscore ni estadísticas."""
        competitors = ecuabet.get("competitors") or []
        home_name = (competitors[0].get("name", "") if len(competitors) > 0 else "")
        away_name = (competitors[1].get("name", "") if len(competitors) > 1 else "")
        if not home_name or not away_name:
            split_home, split_away = self._split_ecuabet_name(ecuabet)
            home_name = home_name or split_home
            away_name = away_name or split_away

        home_score, away_score = self._parse_ecuabet_score(ecuabet)
        stats = {
            "home": {},
            "away": {},
            "raw_types": [],
            "source": "ecuabet_fallback",
            "warning": (
                "Flashscore no proporcionó una coincidencia fiable. "
                "Se usan marcador/minuto/cuotas de Ecuabet; estadísticas Flashscore no disponibles."
            ),
        }
        match = LiveMatch(
            ecuabet_event_id=int(ecuabet.get("id")),
            flashscore_event_id=None,
            home_team=home_name,
            away_team=away_name,
            league=(ecuabet.get("champ") or {}).get("name", ""),
            country=(ecuabet.get("category") or {}).get("name", ""),
            start_time=ecuabet.get("startDate"),
            minute=ecuabet.get("liveTime") or ecuabet.get("minute"),
            period=ecuabet.get("ls") or ecuabet.get("period"),
            match_status="LIVE",
            is_finished=False,
            home_score=home_score,
            away_score=away_score,
            odds=self._flatten_odds(ecuabet.get("markets", [])),
            performance=stats,
            mapping_confidence=0.0,
            data_quality=0.0,
        )

        # Los motores pueden evaluar los datos disponibles, pero el snapshot
        # queda marcado como respaldo y sin estadísticas externas.
        match.opportunities = LiveOpportunityEngine.evaluate(match)
        match.opportunities_v2 = LiveOpportunityEngineV2.evaluate(match)
        match.opportunities_v11 = LiveOpportunityEngineV11.evaluate(match)
        match.opportunities_v12 = LiveOpportunityEngineV12.evaluate(match)
        match.opportunities_v21 = LiveOpportunityEngineV21.evaluate(match)
        match.opportunities_v22 = LiveOpportunityEngineV22.evaluate(match)
        match.opportunities_v3 = LiveOpportunityEngineV3.evaluate(match)
        match.opportunities_v2_ultra = LiveOpportunityEngineV2Ultra.evaluate(match)
        match.opportunities_v11_ultra = LiveOpportunityEngineV11Ultra.evaluate(match)
        match.opportunities_vpro = LiveOpportunityEngineVPro.evaluate(match)
        match.opportunities_vpro11 = LiveOpportunityEngineVPro11.evaluate(match)
        try:
            record_match_snapshot(match)
        except Exception:
            logger.exception(
                "No se pudo guardar snapshot de respaldo Ecuabet para evento %s",
                match.ecuabet_event_id,
            )
        return match

    def construir_desde_evento(self, ecuabet_event: Dict[str, Any], flashscore_event_id: str, mapping_confidence: float = 1.0) -> LiveMatch:
        """Construye un snapshot usando un evento Ecuabet ya descargado."""
        if not ecuabet_event:
            raise ValueError("ecuabet_event es obligatorio.")
        if not flashscore_event_id:
            raise ValueError("flashscore_event_id es obligatorio.")
        return self._construir_desde_evento(
            ecuabet_event,
            str(flashscore_event_id),
            float(mapping_confidence or 1.0),
        )

    @staticmethod
    def enriquecer_evento_desde_payload(event: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        """Completa un evento GetLivenow usando el mismo payload ya descargado."""
        event = dict(event or {})
        markets = {
            int(item["id"]): item
            for item in payload.get("markets", []) or []
            if item.get("id") is not None
        }
        odds = {
            int(item["id"]): item
            for item in payload.get("odds", []) or []
            if item.get("id") is not None
        }
        competitors = {
            int(item["id"]): item
            for item in payload.get("competitors", []) or []
            if item.get("id") is not None
        }
        champs = {
            int(item["id"]): item
            for item in payload.get("champs", []) or []
            if item.get("id") is not None
        }
        categories = {
            int(item["id"]): item
            for item in payload.get("categories", []) or []
            if item.get("id") is not None
        }

        enriched_markets = []
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
            enriched_markets.append({
                "id": market.get("id"),
                "type_id": market.get("typeId"),
                "name": market.get("name", ""),
                "line": market.get("sv") or market.get("sn"),
                "selections": selections,
            })

        event["markets"] = enriched_markets
        event["competitors"] = [
            competitors.get(int(cid), {"id": cid})
            for cid in event.get("competitorIds", []) or []
        ]
        event["champ"] = champs.get(int(event.get("champId", -1)), {})
        event["category"] = categories.get(int(event.get("catId", -1)), {})
        return event

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

        stats = flashscore.get("stats", {})
        raw_event = flashscore.get("raw_event") or {}

        # Flashscore es la fuente prioritaria del marcador/minuto LIVE; Ecuabet
        # puede retrasar el reloj varios minutos. Si falta un dato, usamos Ecuabet.
        ecuabet_score = ecuabet.get("score") or [None, None]
        if not isinstance(ecuabet_score, list):
            ecuabet_score = []
        raw_score = raw_event.get("score")
        fs_home = fs_away = None
        if isinstance(raw_score, dict):
            fs_home = raw_score.get("home", raw_score.get("currentHome"))
            fs_away = raw_score.get("away", raw_score.get("currentAway"))
        elif isinstance(raw_score, list):
            fs_home = raw_score[0] if len(raw_score) > 0 else None
            fs_away = raw_score[1] if len(raw_score) > 1 else None
        if fs_home is None:
            fs_home = raw_event.get("homeScore")
        if fs_away is None:
            fs_away = raw_event.get("awayScore")
        score = [
            fs_home if fs_home is not None else (ecuabet_score[0] if len(ecuabet_score) > 0 else None),
            fs_away if fs_away is not None else (ecuabet_score[1] if len(ecuabet_score) > 1 else None),
        ]
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
            minute=raw_event.get("minute") or raw_event.get("time") or ecuabet.get("liveTime"),
            period=ecuabet.get("ls"),
            home_score=score[0] if len(score) > 0 else None,
            away_score=score[1] if len(score) > 1 else None,
            odds=self._flatten_odds(ecuabet.get("markets", [])),
            performance=stats,
            mapping_confidence=mapping_confidence,
            data_quality=self._calculate_data_quality(stats),
        )
        # Contexto ampliado optativo. Solo se consulta cuando se configura un
        # proveedor compatible; sus errores nunca interrumpen el motor LIVE.
        # No cambia las fórmulas originales de V1, V2 ni V.Pro.
        if self.context_provider.base_url and match.flashscore_event_id:
            try:
                match.pre_match_context = self.context_provider.obtener_contexto(
                    match.flashscore_event_id,
                    home_team_id=home.get("id"),
                    away_team_id=away.get("id"),
                )
            except Exception as exc:
                match.pre_match_context = {
                    "provider": "flashscore_context_api",
                    "lineups": {"status": "unavailable", "data": {}, "error": str(exc)},
                    "history": {"status": "unavailable", "data": {}, "error": str(exc)},
                    "fixtures": {"status": "unavailable", "data": {}, "error": str(exc)},
                }

        # Si el proveedor confirma FINAL, los motores dejan de generar
        # oportunidades nuevas. El experimento solo debe liquidar las abiertas.
        if match.is_finished:
            match.opportunities = []
            match.opportunities_v2 = []
            match.opportunities_v11 = []
            match.opportunities_v12 = []
            match.opportunities_v21 = []
            match.opportunities_v22 = []
            match.opportunities_v3 = []
            match.opportunities_v2_ultra = []
            match.opportunities_v11_ultra = []
            match.opportunities_vpro = []
            match.opportunities_vpro11 = []
        else:
            experiment = LiveExperiment.objects.filter(ecuabet_event_id=match.ecuabet_event_id, status="RUNNING").first()
            if experiment and experiment.vpro_reference_odds:
                match.vpro_reference_odds = experiment.vpro_reference_odds
            match.opportunities = LiveOpportunityEngine.evaluate(match)
            match.opportunities_v2 = LiveOpportunityEngineV2.evaluate(match)
            match.opportunities_v11 = LiveOpportunityEngineV11.evaluate(match)
            match.opportunities_v12 = LiveOpportunityEngineV12.evaluate(match)
            match.opportunities_v21 = LiveOpportunityEngineV21.evaluate(match)
            match.opportunities_v22 = LiveOpportunityEngineV22.evaluate(match)
            match.opportunities_v3 = LiveOpportunityEngineV3.evaluate(match)
            match.opportunities_v2_ultra = LiveOpportunityEngineV2Ultra.evaluate(match)
            match.opportunities_v11_ultra = LiveOpportunityEngineV11Ultra.evaluate(match)
            match.opportunities_vpro = LiveOpportunityEngineVPro.evaluate(match)
            match.opportunities_vpro11 = LiveOpportunityEngineVPro11.evaluate(match)

        # Persistencia independiente: no genera apuestas ni modifica capitales.
        try:
            record_match_snapshot(match)
        except Exception:
            logger.exception("No se pudo guardar snapshot del laboratorio de patrones para evento %s", match.ecuabet_event_id)
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
        """Construye un snapshot actual/final priorizando el feed diario de Flashscore.

        El feed diario es la fuente de verdad para determinar FINAL: AB=3.
        No dependemos de GraphQL LIVE para liquidar un partido que Ecuabet ya
        retiró de GetLivenow, porque en ese momento GraphQL puede dejar de
        encontrar el evento.
        """
        if not flashscore_event_id:
            raise ValueError("flashscore_event_id es obligatorio para confirmar el final.")

        # PRIMERO: feed diario. Es válido aunque el partido ya haya terminado.
        feed_match = self.flashscore.obtener_partido_por_id(flashscore_event_id)

        if feed_match and feed_match.get("finished"):
            home_score = feed_match.get("home_score")
            away_score = feed_match.get("away_score")
            status = "FINISHED" if home_score is not None and away_score is not None else "FINISHED_PENDING_SCORE"

            # Para liquidar exigimos estado final + marcador final verificable.
            match = LiveMatch(
                ecuabet_event_id=ecuabet_event_id,
                flashscore_event_id=str(flashscore_event_id),
                home_team=feed_match.get("home_team") or home_team,
                away_team=feed_match.get("away_team") or away_team,
                start_time=feed_match.get("start_time"),
                minute=feed_match.get("minute"),
                period=feed_match.get("period"),
                match_status=status,
                is_finished=status == "FINISHED",
                home_score=home_score,
                away_score=away_score,
                odds=[],
                performance={"home": {}, "away": {}, "raw_types": []},
                mapping_confidence=1.0,
                data_quality=0.0,
            )
            match.opportunities = []
            match.opportunities_v2 = []
            match.opportunities_v11 = []
            match.opportunities_v22 = []
            match.opportunities_vpro = []
            match.opportunities_vpro11 = []
            return match

        # Si AB no es 3, el partido puede seguir LIVE. Intentamos GraphQL para
        # mantener el snapshot actual y las estadísticas del motor.
        flashscore = self.flashscore.obtener_live_match(flashscore_event_id)
        raw_event = flashscore.get("raw_event") or {}
        participants = raw_event.get("eventParticipants", []) or []
        home = next(
            (p for p in participants if ((p.get("type") or {}).get("side") or "").upper() == "HOME"),
            {},
        )
        away = next(
            (p for p in participants if ((p.get("type") or {}).get("side") or "").upper() == "AWAY"),
            {},
        )

        home_name = self._participant_name(home) or (feed_match or {}).get("home_team") or home_team
        away_name = self._participant_name(away) or (feed_match or {}).get("away_team") or away_team

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
            flashscore_event_id=flashscore.get("flashscore_event_id") or str(flashscore_event_id),
            home_team=home_name,
            away_team=away_name,
            start_time=(feed_match or {}).get("start_time"),
            minute=raw_event.get("minute") or raw_event.get("time") or (feed_match or {}).get("minute"),
            period=raw_event.get("period") or (feed_match or {}).get("period"),
            match_status="LIVE",
            is_finished=False,
            home_score=home_score,
            away_score=away_score,
            odds=[],
            performance=stats,
            mapping_confidence=1.0,
            data_quality=self._calculate_data_quality(stats),
        )
        match.opportunities = LiveOpportunityEngine.evaluate(match)
        match.opportunities_v2 = LiveOpportunityEngineV2.evaluate(match)
        match.opportunities_v11 = LiveOpportunityEngineV11.evaluate(match)
        match.opportunities_v12 = LiveOpportunityEngineV12.evaluate(match)
        match.opportunities_v22 = LiveOpportunityEngineV22.evaluate(match)
        match.opportunities_v21 = LiveOpportunityEngineV21.evaluate(match)
        match.opportunities_v3 = LiveOpportunityEngineV3.evaluate(match)
        match.opportunities_v2_ultra = LiveOpportunityEngineV2Ultra.evaluate(match)
        match.opportunities_v11_ultra = LiveOpportunityEngineV11Ultra.evaluate(match)
        match.opportunities_vpro = LiveOpportunityEngineVPro.evaluate(match)
        match.opportunities_vpro11 = LiveOpportunityEngineVPro11.evaluate(match)
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
