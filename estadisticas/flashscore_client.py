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

    # Catálogo de métricas que Flashscore puede mostrar en Estadísticas/General.
    STAT_CATALOG = [
        ("General", "ball_possession", "Posesión"),
        ("General", "expected_goals", "Expected goals (xG)"),
        ("General", "goal_attempts", "Remates totales"),
        ("General", "shots_on_goal", "Remates a puerta"),
        ("General", "shots_off_goal", "Remates fuera"),
        ("General", "blocked_shots", "Remates bloqueados"),
        ("General", "corner_kicks", "Córneres"),
        ("General", "yellow_cards", "Tarjetas amarillas"),
        ("General", "red_cards", "Tarjetas rojas"),
        ("General", "yellow_red_cards", "Doble amarilla / roja"),
        ("Shots", "expected_goals_on_target", "xG a puerta (xGOT)"),
        ("Shots", "shots_inside_box", "Remates dentro del área"),
        ("Shots", "shots_outside_box", "Remates fuera del área"),
        ("Shots", "hit_woodwork", "Remates al poste"),
        ("Shots", "headed_goals", "Goles de cabeza"),
        ("Attack", "touches_in_opposition_box", "Toques en el área rival"),
        ("Attack", "big_chances", "Grandes ocasiones"),
        ("Attack", "big_chances_scored", "Grandes ocasiones convertidas"),
        ("Attack", "big_chances_missed", "Grandes ocasiones falladas"),
        ("Attack", "corner_kicks", "Córneres"),
        ("Attack", "free_kicks", "Tiros libres"),
        ("Attack", "offsides", "Fueras de juego"),
        ("Attack", "accurate_through_passes", "Pases filtrados precisos"),
        ("Passes", "passes", "Pases"),
        ("Passes", "accurate_passes", "Pases precisos"),
        ("Passes", "long_passes", "Pases largos"),
        ("Passes", "accurate_long_passes", "Pases largos precisos"),
        ("Passes", "final_third_passes", "Pases en último tercio"),
        ("Passes", "accurate_final_third_passes", "Pases precisos en último tercio"),
        ("Passes", "crosses", "Centros"),
        ("Passes", "accurate_crosses", "Centros precisos"),
        ("Passes", "expected_assists", "Asistencias esperadas (xA)"),
        ("Passes", "key_passes", "Pases clave"),
        ("Passes", "throw_ins", "Saques de banda"),
        ("Defense", "fouls", "Faltas"),
        ("Defense", "duels_won", "Duelos ganados"),
        ("Defense", "tackles", "Entradas"),
        ("Defense", "tackles_won", "Entradas ganadas"),
        ("Defense", "interceptions", "Intercepciones"),
        ("Defense", "clearances", "Despejes"),
        ("Defense", "errors_leading_to_shot", "Errores que provocan remate"),
        ("Defense", "errors_leading_to_goal", "Errores que provocan gol"),
        ("Goalkeeping", "goalkeeper_saves", "Paradas del portero"),
        ("Goalkeeping", "expected_goals_on_target_faced", "xGOT recibido"),
        ("Goalkeeping", "goals_conceded", "Goles recibidos"),
        ("Goalkeeping", "goals_prevented", "Goles evitados"),
        ("Goalkeeping", "goal_kicks", "Saques de meta"),
    ]

    @classmethod
    def normalizar_stats(cls, event: Dict[str, Any]) -> Dict[str, Any]:
        """Normaliza estadisticas LIVE tolerando estructuras anidadas."""
        result = {"home": {}, "away": {}, "raw_types": []}

        def add_stat(target, stat, group_name="Estadísticas"):
            if not isinstance(stat, dict):
                return False
            stat_type = stat.get("type") or stat.get("statType") or stat.get("key")
            if not stat_type:
                return False
            raw_value = stat.get("value")
            if raw_value is None:
                raw_value = stat.get("rawValue")
            if raw_value is None:
                raw_value = stat.get("displayValue")
            if isinstance(raw_value, (dict, list)):
                return False
            parsed = cls._parse_numeric(raw_value)
            label = (stat.get("label") or stat.get("name") or
                     stat.get("displayName") or stat_type)
            result[target][stat_type] = {
                "name": stat.get("name", label),
                "label": label,
                "value": parsed,
                "raw_value": raw_value,
                "group": stat.get("group") or group_name,
            }
            if stat_type not in result["raw_types"]:
                result["raw_types"].append(stat_type)
            return True

        def walk_stats(target, node, group_name="Estadísticas", depth=0):
            if depth > 8 or node is None:
                return
            if isinstance(node, list):
                for item in node:
                    walk_stats(target, item, group_name, depth + 1)
                return
            if not isinstance(node, dict):
                return
            if add_stat(target, node, group_name):
                return
            current_group = (node.get("name") or node.get("label") or
                             node.get("displayName") or node.get("group") or group_name)
            for key in ("values", "statistics", "stats", "items", "data"):
                child = node.get(key)
                if child is not None:
                    walk_stats(target, child, current_group, depth + 1)

        participants = event.get("eventParticipants") or []
        if isinstance(participants, dict):
            participants = list(participants.values())

        for participant in participants:
            if not isinstance(participant, dict):
                continue
            ptype = participant.get("type") or {}
            side = str(ptype.get("side") or "").upper() if isinstance(ptype, dict) else ""
            target = "home" if side == "HOME" else "away" if side == "AWAY" else None
            if target:
                walk_stats(target, participant.get("stats"))

        for group, stat_type, label in cls.STAT_CATALOG:
            for target in ("home", "away"):
                if stat_type not in result[target]:
                    result[target][stat_type] = {
                        "name": label, "label": label, "value": None,
                        "raw_value": None, "group": group,
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
