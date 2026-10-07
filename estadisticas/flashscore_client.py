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



        return result

    @staticmethod
    def _slug_stat(label: str) -> str:
        import re
        import unicodedata

        text = unicodedata.normalize("NFKD", str(label or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
        return text or "stat"

    @classmethod
    def _normalizar_stats_feed(cls, raw: str) -> Dict[str, Any]:
        """Parsea df_st_1 conservando TODAS las estadísticas reales del feed."""
        result = {"home": {}, "away": {}, "raw_types": []}

        aliases = {
            "expected goals (xg)": ("expected_goals", "Expected goals (xG)"),
            "goles esperados (xg)": ("expected_goals", "Expected goals (xG)"),
            "ball possession": ("ball_possession", "Posesión"),
            "posesión": ("ball_possession", "Posesión"),
            "posesion": ("ball_possession", "Posesión"),
            "posesión del balón": ("ball_possession", "Posesión"),
            "total shots": ("goal_attempts", "Remates totales"),
            "goal attempts": ("goal_attempts", "Remates totales"),
            "remates totales": ("goal_attempts", "Remates totales"),
            "shots on target": ("shots_on_goal", "Remates a puerta"),
            "shots on goal": ("shots_on_goal", "Remates a puerta"),
            "remates a puerta": ("shots_on_goal", "Remates a puerta"),
            "shots off target": ("shots_off_goal", "Remates fuera"),
            "shots off goal": ("shots_off_goal", "Remates fuera"),
            "remates fuera": ("shots_off_goal", "Remates fuera"),
            "blocked shots": ("blocked_shots", "Remates bloqueados"),
            "remates bloqueados": ("blocked_shots", "Remates bloqueados"),
            "free kicks": ("free_kicks", "Tiros libres"),
            "tiros libres": ("free_kicks", "Tiros libres"),
            "corner kicks": ("corner_kicks", "Córneres"),
            "corner": ("corner_kicks", "Córneres"),
            "córneres": ("corner_kicks", "Córneres"),
            "corners": ("corner_kicks", "Córneres"),
            "offsides": ("offsides", "Fueras de juego"),
            "fueras de juego": ("offsides", "Fueras de juego"),
            "throw-ins": ("throw_ins", "Saques de banda"),
            "throw-in": ("throw_ins", "Saques de banda"),
            "saques de banda": ("throw_ins", "Saques de banda"),
            "goalkeeper saves": ("goalkeeper_saves", "Paradas del portero"),
            "paradas del portero": ("goalkeeper_saves", "Paradas del portero"),
            "red cards": ("red_cards", "Tarjetas rojas"),
            "tarjetas rojas": ("red_cards", "Tarjetas rojas"),
            "yellow cards": ("yellow_cards", "Tarjetas amarillas"),
            "tarjetas amarillas": ("yellow_cards", "Tarjetas amarillas"),
            "fouls": ("fouls", "Faltas"),
            "faltas": ("fouls", "Faltas"),
            "passes": ("passes", "Pases"),
            "pases": ("passes", "Pases"),
            "accurate passes": ("accurate_passes", "Pases precisos"),
            "pases precisos": ("accurate_passes", "Pases precisos"),
            "long passes": ("long_passes", "Pases largos"),
            "pases largos": ("long_passes", "Pases largos"),
            "accurate long passes": ("accurate_long_passes", "Pases largos precisos"),
            "pases largos precisos": ("accurate_long_passes", "Pases largos precisos"),
            "crosses": ("crosses", "Centros"),
            "centros": ("crosses", "Centros"),
            "accurate crosses": ("accurate_crosses", "Centros precisos"),
            "centros precisos": ("accurate_crosses", "Centros precisos"),
            "key passes": ("key_passes", "Pases clave"),
            "pases clave": ("key_passes", "Pases clave"),
            "expected assists (xa)": ("expected_assists", "Asistencias esperadas (xA)"),
            "asistencias esperadas (xa)": ("expected_assists", "Asistencias esperadas (xA)"),
            "big chances": ("big_chances", "Grandes ocasiones"),
            "grandes ocasiones": ("big_chances", "Grandes ocasiones"),
            "big chances missed": ("big_chances_missed", "Grandes ocasiones falladas"),
            "grandes ocasiones falladas": ("big_chances_missed", "Grandes ocasiones falladas"),
            "touches in opposition box": ("touches_in_opposition_box", "Toques en el área rival"),
            "toques en el área rival": ("touches_in_opposition_box", "Toques en el área rival"),
            "shots inside box": ("shots_inside_box", "Remates dentro del área"),
            "remates dentro del área": ("shots_inside_box", "Remates dentro del área"),
            "shots outside box": ("shots_outside_box", "Remates fuera del área"),
            "remates fuera del área": ("shots_outside_box", "Remates fuera del área"),
            "expected goals on target": ("expected_goals_on_target", "xG a puerta (xGOT)"),
        }

        for block in (raw or "").split("~"):
            fields = {}
            for field in block.split("¬"):
                if "÷" not in field:
                    continue
                key, value = field.split("÷", 1)
                fields[key.strip()] = value

            label = (fields.get("SG") or fields.get("SN") or "").strip()
            home_raw, away_raw = fields.get("SH"), fields.get("SI")
            if not label or home_raw is None or away_raw is None:
                continue

            normalized = label.casefold()
            stat_type, display_label = aliases.get(
                normalized,
                (cls._slug_stat(label), label),
            )

            group = fields.get("SF") or "Estadísticas"
            if stat_type in result["home"]:
                stat_type = f"{stat_type}__{cls._slug_stat(group)}"
            for target, raw_value in (("home", home_raw), ("away", away_raw)):
                result[target][stat_type] = {
                    "name": display_label,
                    "label": display_label,
                    "value": cls._parse_numeric(raw_value),
                    "raw_value": raw_value,
                    "group": group,
                }

            if stat_type not in result["raw_types"]:
                result["raw_types"].append(stat_type)

        return result

    def obtener_stats_feed(self, event_id: str) -> Dict[str, Any]:
        url = self.LIVE_FEED_URL.rsplit("/", 2)[0] + f"/df_st_1_{event_id}"
        raw = self._feed_request(url)
        return self._normalizar_stats_feed(raw)

    def obtener_stats(self, event_id: str) -> Dict[str, Any]:
        """Obtiene y normaliza las estadísticas actuales de un partido."""
        event = self.obtener_evento(event_id)
        stats = self.normalizar_stats(event)

        real_count = sum(
            1 for side in ("home", "away")
            for item in (stats.get(side) or {}).values()
            if item.get("raw_value") is not None
        )
        # El GraphQL puede traer solo TOP Stats. Siempre consultamos df_st_1
        # para incorporar también Shots, Attack, Passes, Defense y Goalkeeping.
        try:
            feed_stats = self.obtener_stats_feed(event_id)
            for side in ("home", "away"):
                for stat_type, item in (feed_stats.get(side) or {}).items():
                    stats[side][stat_type] = item
                    if stat_type not in stats["raw_types"]:
                        stats["raw_types"].append(stat_type)
        except Exception:
            # Conservamos lo que haya entregado GraphQL si el feed secundario
            # no está disponible temporalmente.
            pass

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

        real_count = sum(
            1 for side in ("home", "away")
            for item in (stats.get(side) or {}).values()
            if item.get("raw_value") is not None
        )
        # El GraphQL puede traer solo TOP Stats. Siempre consultamos df_st_1
        # para incorporar también Shots, Attack, Passes, Defense y Goalkeeping.
        try:
            feed_stats = self.obtener_stats_feed(event_id)
            for side in ("home", "away"):
                for stat_type, item in (feed_stats.get(side) or {}).items():
                    stats[side][stat_type] = item
                    if stat_type not in stats["raw_types"]:
                        stats["raw_types"].append(stat_type)
        except Exception:
            # Conservamos lo que haya entregado GraphQL si el feed secundario
            # no está disponible temporalmente.
            pass

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
