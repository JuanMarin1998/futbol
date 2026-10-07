import os
import re
import unicodedata

import requests


class EcuabetAPIError(RuntimeError):
    pass


class EcuabetClient:
    # Caché por proceso para no redescubrir la competición en cada polling.
    # Las cuotas sí se consultan en cada petición.
    _EVENT_CACHE = {}
    _EVENT_CACHE_TTL = 600

    BASE_URL = os.getenv("ECUABET_WIDGET_BASE_URL", "https://sb2frontend-altenar2.biahosted.com/api/widget")
    DEFAULT_PARAMS = {
        "culture": os.getenv("ECUABET_CULTURE", "es-ES"),
        "timezoneOffset": int(os.getenv("ECUABET_TIMEZONE_OFFSET", "300")),
        "integration": os.getenv("ECUABET_INTEGRATION", "ecuabet"),
        "deviceType": int(os.getenv("ECUABET_DEVICE_TYPE", "1")),
        "numFormat": os.getenv("ECUABET_NUM_FORMAT", "en-GB"),
        "countryCode": os.getenv("ECUABET_COUNTRY_CODE", "EC"),
    }

    def __init__(self, timeout=10, session=None):
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        self.timeout = timeout

    @staticmethod
    def _normalize(value):
        value = unicodedata.normalize("NFKD", str(value or ""))
        value = "".join(c for c in value if not unicodedata.combining(c))
        return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())

    @classmethod
    def _tokens(cls, name):
        ignored = {"fc", "cf", "sc", "club", "de", "del", "la", "los", "las"}
        return {x for x in cls._normalize(name).split() if len(x) > 2 and x not in ignored}

    def _request(self, method, path, params=None, json=None):
        method = method.upper()
        query = dict(self.DEFAULT_PARAMS) if method == "GET" else {}
        if params:
            query.update(params)
        response = self.session.request(
            method,
            f"{self.BASE_URL.rstrip('/')}/{path.lstrip('/')}",
            params=query,
            json=json,
            timeout=self.timeout,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            raise EcuabetAPIError(f"Ecuabet HTTP {response.status_code}: {payload}")
        return payload

    @staticmethod
    def _walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from EcuabetClient._walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from EcuabetClient._walk(child)

    def _candidate_championships(self, sport_id=66, league_name=""):
        """Obtiene solo los campeonatos relevantes sin recorrer toda la oferta."""
        try:
            payload = self._request("GET", "GetEvents", {
                "eventCount": 0,
                "sportId": sport_id or 66,
                "champIds": 0,
            })
        except EcuabetAPIError:
            return []

        available = payload.get("availableChamps", []) if isinstance(payload, dict) else []
        if not isinstance(available, list):
            return []

        target = self._tokens(league_name)
        candidates = []

        for item in available:
            if not isinstance(item, dict):
                continue

            champ_id = (
                item.get("id")
                or item.get("champId")
                or item.get("LI")
                or item.get("I")
            )
            name = str(
                item.get("name")
                or item.get("champName")
                or item.get("L")
                or item.get("LE")
                or ""
            )

            if champ_id is None:
                continue
            try:
                champ_id = int(champ_id)
            except (TypeError, ValueError):
                continue

            score = len(target & self._tokens(name)) if target else 0
            candidates.append((score, champ_id, name))

        # Algunos nombres de liga de API-Football son distintos a Ecuabet.
        aliases = {
            "bundesliga": ("bundesliga", "germany", "alemania"),
            "premier league": ("premier", "england", "inglaterra"),
            "la liga": ("laliga", "la liga", "spain", "espana"),
            "serie a": ("serie a", "italy", "italia"),
            "ligue 1": ("ligue 1", "france", "francia"),
            "eredivisie": ("eredivisie", "netherlands", "paises bajos", "holland"),
            "primeira liga": ("primeira", "portugal"),
            "champions league": ("champions", "uefa"),
            "europa league": ("europa league", "uefa"),
        }

        normalized_league = self._normalize(league_name)
        alias_tokens = set(aliases.get(normalized_league, ()))
        if alias_tokens:
            alias_tokens = self._tokens(" ".join(alias_tokens))

        if alias_tokens:
            adjusted = []
            for score, champ_id, name in candidates:
                score = max(score, len(alias_tokens & self._tokens(name)))
                adjusted.append((score, champ_id, name))
            candidates = adjusted

        candidates.sort(key=lambda x: x[0], reverse=True)
        # No necesitamos consultar cientos de campeonatos: solo los mejores
        # candidatos para la liga solicitada.
        return candidates[:5]

    def buscar_evento(self, local, visitante, sport_id=66, champ_id=0, league_name=""):
        """Busca un partido sin bloquear recorriendo todos los campeonatos."""
        home_target, away_target = self._tokens(local), self._tokens(visitante)
        if not home_target or not away_target:
            raise EcuabetAPIError(f"Nombres de equipos inválidos: {local} vs {visitante}")

        import time
        cache_key = (
            self._normalize(local),
            self._normalize(visitante),
            self._normalize(league_name),
        )
        cached = self._EVENT_CACHE.get(cache_key)
        if cached and time.time() - cached["cached_at"] < self._EVENT_CACHE_TTL:
            return dict(cached["data"])

        # 1) Primero probamos la consulta general. Es barata y muchas veces
        # ya contiene el evento solicitado.
        try:
            payload = self._request("GET", "GetEvents", {
                "eventCount": 0,
                "sportId": sport_id or 66,
                "champIds": 0,
            })
        except EcuabetAPIError:
            payload = {}

        def find_in_payload(data, current_champ=0):
            for item in data.get("events", []) if isinstance(data, dict) else []:
                event_id = item.get("id") or item.get("eventId")
                event_name = str(item.get("name", ""))
                if not event_id or not event_name:
                    continue

                parts = re.split(
                    r"\s+vs\.?\s+|\s+-\s+",
                    event_name,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )
                if len(parts) != 2:
                    continue

                direct = (
                    len(home_target & self._tokens(parts[0]))
                    and len(away_target & self._tokens(parts[1]))
                )
                reverse = (
                    len(home_target & self._tokens(parts[1]))
                    and len(away_target & self._tokens(parts[0]))
                )
                if not direct and not reverse:
                    continue

                score = (
                    len(home_target & self._tokens(parts[0]))
                    + len(away_target & self._tokens(parts[1]))
                    if direct
                    else len(home_target & self._tokens(parts[1]))
                    + len(away_target & self._tokens(parts[0]))
                    - 0.5
                )
                return {
                    "event_id": int(event_id),
                    "name": event_name,
                    "match_score": score,
                    "sport_id": item.get("sportId") or sport_id or 66,
                    "champ_id": item.get("champId") or current_champ or 0,
                }
            return None

        found = find_in_payload(payload)
        if found:
            self._EVENT_CACHE[cache_key] = {"cached_at": time.time(), "data": found}
            return found

        # 2) Solo si no apareció, descubrimos los campeonatos disponibles y
        # consultamos los que coinciden con la liga del partido.
        champ_ids = []
        if int(champ_id or 0):
            champ_ids.append(int(champ_id))

        for _, discovered_id, _ in self._candidate_championships(
            sport_id=sport_id or 66,
            league_name=league_name,
        ):
            if discovered_id not in champ_ids:
                champ_ids.append(discovered_id)

        for current_champ_id in champ_ids:
            try:
                data = self._request("GET", "GetEvents", {
                    "eventCount": 0,
                    "sportId": sport_id or 66,
                    "champIds": current_champ_id,
                })
            except EcuabetAPIError:
                continue

            found = find_in_payload(data, current_champ_id)
            if found:
                self._EVENT_CACHE[cache_key] = {
                    "cached_at": time.time(),
                    "data": found,
                }
                return found

        raise EcuabetAPIError(f"No se encontró en Ecuabet: {local} vs {visitante}")

    def obtener_detalle_evento(self, event_id):
        return self._request("GET", "GetEventDetails", {
            "eventId": str(event_id), "showNonBoosts": "false"
        })

    def obtener_1x2(self, event_id):
        detalle = self.obtener_detalle_evento(event_id)
        markets = []
        for item in self._walk(detalle):
            if isinstance(item.get("markets"), list):
                markets.extend(item["markets"])
        market = next((m for m in markets if m.get("typeId") == 1), None)
        if not market:
            raise EcuabetAPIError(f"No se encontró mercado 1X2 para {event_id}")

        odd_ids = []
        for value in market.get("desktopOddIds", []):
            odd_ids.extend(value if isinstance(value, list) else [value])

        odds_by_id = {}
        for item in self._walk(detalle):
            if isinstance(item.get("odds"), list):
                for odd in item["odds"]:
                    if isinstance(odd, dict) and odd.get("id") is not None:
                        odds_by_id[int(odd["id"])] = odd

        selections = []
        for odd_id in odd_ids:
            odd = odds_by_id.get(int(odd_id))
            if odd:
                selections.append({
                    "odd_id": int(odd_id),
                    "name": odd.get("name", ""),
                    "price": odd.get("price"),
                    "competitor_id": odd.get("competitorId"),
                    "type_id": odd.get("typeId"),
                })
        if not selections:
            raise EcuabetAPIError(f"El mercado 1X2 {event_id} no contiene cuotas")
        return {"market_id": market.get("id"), "market_type_id": market.get("typeId"), "selections": selections}

    def obtener_cuotas_1x2(self, event_id, sport_id=0, champ_id=0):
        """
        Obtiene las cuotas 1X2 directamente desde GetEvents.

        Ecuabet relaciona:
            evento -> marketIds -> markets -> oddIds -> odds

        Se conservan sport_id/champ_id porque un evento puede no aparecer
        en una consulta GetEvents genérica con champIds=0.
        """
        detalle = self.obtener_mercados_evento(
            event_id,
            sport_id=sport_id,
            champ_id=champ_id,
        )
        market = next(
            (m for m in detalle["markets"] if int(m.get("market_type_id") or 0) == 1),
            None,
        )
        if not market:
            raise EcuabetAPIError(f"No se encontró mercado 1X2 para {event_id}")

        selections = []
        for selection in market.get("selections", []):
            selections.append({
                **selection,
                "price": selection.get("price"),
                "is_live": False,
                "live_time": None,
                "period": None,
                "score": None,
                "last_update": None,
            })

        if not selections:
            raise EcuabetAPIError(f"El mercado 1X2 {event_id} no contiene cuotas")

        return {
            "event_id": int(event_id),
            "market_id": market["market_id"],
            "selections": selections,
        }

    def obtener_mercados_evento(self, event_id, sport_id=0, champ_id=0):
        """Obtiene el evento y relaciona markets -> oddIds -> odds."""
        payload = self._request("GET", "GetEvents", {
            "eventCount": 0,
            "sportId": sport_id,
            "champIds": champ_id,
        })

        event = next((e for e in payload.get("events", []) if int(e.get("id", -1)) == int(event_id)), None)

        # Si el evento ya está guardado en la BD pero no conocemos su
        # campeonato, repetir la consulta con Bundesliga (champId 2950).
        if not event and int(champ_id or 0) != 2950:
            payload = self._request("GET", "GetEvents", {
                "eventCount": 0,
                "sportId": 0,
                "champIds": 2950,
            })
            event = next(
                (e for e in payload.get("events", [])
                 if int(e.get("id", -1)) == int(event_id)),
                None,
            )

        if not event:
            raise EcuabetAPIError(f"No se encontró el evento {event_id}")

        odds_by_id = {int(o["id"]): o for o in payload.get("odds", []) if o.get("id") is not None}
        markets_by_id = {int(m["id"]): m for m in payload.get("markets", []) if m.get("id") is not None}

        markets = []
        for market_id in event.get("marketIds", []):
            market = markets_by_id.get(int(market_id))
            if not market:
                continue
            selections = []
            for odd_id in market.get("oddIds", []):
                odd = odds_by_id.get(int(odd_id))
                if not odd:
                    continue
                selections.append({
                    "odd_id": int(odd_id),
                    "type_id": odd.get("typeId"),
                    "name": odd.get("name", ""),
                    "price": odd.get("price"),
                    "competitor_id": odd.get("competitorId"),
                })
            markets.append({
                "market_id": int(market["id"]),
                "market_type_id": market.get("typeId"),
                "name": market.get("name", ""),
                "line": market.get("sv") or market.get("sn"),
                "selections": selections,
            })

        return {
            "event_id": int(event["id"]),
            "name": event.get("name", ""),
            "start_date": event.get("startDate"),
            "sport_id": event.get("sportId"),
            "cat_id": event.get("catId"),
            "champ_id": event.get("champId"),
            "markets": markets,
        }
