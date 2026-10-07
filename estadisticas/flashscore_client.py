import os
from typing import Any, Dict, List, Optional

import requests


class FlashscoreAPIError(RuntimeError):
    """Error al consultar los datos internos de Flashscore."""


class FlashscoreClient:
    """
    Cliente mínimo para consultar estadísticas LIVE de un evento Flashscore.

    Flashscore no expone este endpoint como una API pública/estable. El cliente
    deja configurables host, project_id, hash y headers para poder adaptarlo
    si cambian sus parámetros.
    """

    BASE_URL = os.getenv(
        "FLASHSCORE_GRAPHQL_URL",
        "https://13.ds.lsapp.eu/pq_graphql",
    )
    PROJECT_ID = os.getenv("FLASHSCORE_PROJECT_ID", "13")
    QUERY_HASH = os.getenv("FLASHSCORE_QUERY_HASH", "dsos2")
    GEO_IP_CODE = os.getenv("FLASHSCORE_GEO_IP_CODE", "")
    GEO_IP_SUBDIVISION_CODE = os.getenv("FLASHSCORE_GEO_IP_SUBDIVISION_CODE", "")
    TIMEOUT = int(os.getenv("FLASHSCORE_TIMEOUT", "8"))
    LIVE_FEED_URL = os.getenv(
        "FLASHSCORE_LIVE_FEED_URL",
        "https://local-global.flashscore.ninja/13/x/feed/f_1_0_3_es_1",
    )


    def __init__(self, timeout: Optional[int] = None, session=None):
        self.session = session or requests.Session()
        self.timeout = timeout or self.TIMEOUT
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": os.getenv(
                    "FLASHSCORE_USER_AGENT",
                    "Mozilla/5.0",
                ),
                "Referer": os.getenv(
                    "FLASHSCORE_REFERER",
                    "https://www.flashscore.com/",
                ),
                "x-fsign": os.getenv("FLASHSCORE_FSIGN", "SW9D1eZo"),
            }
        )

    def _request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        response = self.session.get(
            self.BASE_URL,
            params=params,
            timeout=self.timeout,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise FlashscoreAPIError(
                f"Flashscore devolvió una respuesta no JSON (HTTP {response.status_code})"
            ) from exc

        if response.status_code >= 400:
            raise FlashscoreAPIError(
                f"Flashscore HTTP {response.status_code}: {payload}"
            )

        if payload.get("errors"):
            raise FlashscoreAPIError(
                f"Flashscore GraphQL errors: {payload['errors']}"
            )

        return payload


    def _feed_request(self, url: Optional[str] = None) -> str:
        response = self.session.get(url or self.LIVE_FEED_URL, timeout=self.timeout)
        if response.status_code >= 400:
            raise FlashscoreAPIError(
                f"Flashscore feed HTTP {response.status_code}: {response.text[:300]}"
            )
        return response.text

    @staticmethod
    def _parse_feed_records(raw: str) -> List[Dict[str, str]]:
        records = []
        for block in (raw or "").split("~"):
            item = {}
            for field in block.split("¬"):
                if "÷" not in field:
                    continue
                key, value = field.split("÷", 1)
                key = key.strip("~")
                if key:
                    item[key] = value
            if item:
                records.append(item)
        return records

    def obtener_partidos_live(self) -> List[Dict[str, Any]]:
        """Obtiene partidos LIVE del feed diario de Flashscore."""
        raw = self._feed_request()
        records = self._parse_feed_records(raw)
        result = []
        tournament = ""
        country = ""

        for row in records:
            if row.get("ZA"):
                tournament = row["ZA"]
            if row.get("ZY"):
                country = row["ZY"]
            if not row.get("AA") or row.get("AB") != "2":
                continue

            result.append({
                "event_id": row.get("AA"),
                "start_time": row.get("AD"),
                "home_team": row.get("AE", ""),
                "away_team": row.get("AF", ""),
                "home_score": row.get("AG"),
                "away_score": row.get("AH"),
                "status": row.get("AB"),
                "minute": row.get("BA"),
                "period": row.get("BC"),
                "tournament": tournament,
                "country": country,
                "raw": row,
            })
        return result

    def obtener_evento(self, event_id: str) -> Dict[str, Any]:
        """Obtiene el objeto Event crudo de findEventById."""
        if not event_id:
            raise FlashscoreAPIError("event_id es obligatorio")

        params = {
            "_hash": self.QUERY_HASH,
            "eventId": str(event_id),
            "projectId": self.PROJECT_ID,
        }

        if self.GEO_IP_CODE:
            params["geoIpCode"] = self.GEO_IP_CODE
        if self.GEO_IP_SUBDIVISION_CODE:
            params["geoIpSubdivisionCode"] = self.GEO_IP_SUBDIVISION_CODE

        payload = self._request(params)
        event = (
            payload.get("data", {})
            .get("findEventById")
        )
        if not isinstance(event, dict):
            raise FlashscoreAPIError(
                f"No se encontró findEventById para {event_id}"
            )
        return event

    @staticmethod
    def _parse_numeric(value):
        if value is None:
            return None
        try:
            text = str(value).strip().replace("%", "").replace(",", ".")
            return float(text) if "." in text else int(text)
        except (TypeError, ValueError):
            return None

    @classmethod
    def normalizar_stats(cls, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convierte eventParticipants.stats.values en un diccionario estable.

        No se limita a una lista cerrada: conserva cualquier tipo nuevo que
        Flashscore entregue para que el motor pueda descubrir más métricas.
        """
        result = {
            "home": {},
            "away": {},
            "raw_types": [],
        }

        for participant in event.get("eventParticipants", []) or []:
            side = ((participant.get("type") or {}).get("side") or "").upper()
            target = "home" if side == "HOME" else "away" if side == "AWAY" else None
            if not target:
                continue

            for stats_group in participant.get("stats", []) or []:
                for stat in stats_group.get("values", []) or []:
                    stat_type = stat.get("type")
                    if not stat_type:
                        continue

                    parsed = cls._parse_numeric(stat.get("value"))
                    result[target][stat_type] = {
                        "name": stat.get("name", ""),
                        "label": stat.get("label", ""),
                        "value": parsed,
                        "raw_value": stat.get("value"),
                        "group": stats_group.get("name") or stats_group.get("label") or stats_group.get("type") or "",
                    }
                    if stat_type not in result["raw_types"]:
                        result["raw_types"].append(stat_type)

        return result

    def obtener_stats(self, event_id: str) -> Dict[str, Any]:
        """Obtiene y normaliza las estadísticas actuales de un partido."""
        event = self.obtener_evento(event_id)
        stats = self.normalizar_stats(event)

        return {
            "event_id": event.get("id") or str(event_id),
            "should_update": event.get("shouldUpdate"),
            "stats": stats,
            "event": event,
        }

    def obtener_live_match(self, event_id: str) -> Dict[str, Any]:
        """
        Devuelve una estructura común para unirla después con Ecuabet.

        Todavía no intenta descubrir automáticamente el ID Flashscore desde
        Ecuabet; esa responsabilidad quedará en MatchMapper.
        """
        event = self.obtener_evento(event_id)
        stats = self.normalizar_stats(event)

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

        return {
            "flashscore_event_id": event.get("id") or str(event_id),
            "should_update": event.get("shouldUpdate"),
            "home_participant_id": home.get("id"),
            "away_participant_id": away.get("id"),
            "stats": stats,
            "raw_event": event,
        }
