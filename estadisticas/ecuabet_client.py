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

    def _candidate_championships(self, sport_id=0, league_name=""):
        """Descubre campeonatos Ecuabet y prioriza la liga del partido."""
        sport_ids = []
        if int(sport_id or 0):
            sport_ids.append(int(sport_id))
        # En Ecuabet el fútbol que ya comprobamos usa sportId=66.
        if 66 not in sport_ids:
            sport_ids.append(66)

        candidates = []
        seen = set()

        for sid in sport_ids:
            # GetChampsZip es más fiable para descubrir TODOS los campeonatos
            # que GetEvents con champIds=0.
            try:
                payload = self._request("GET", "GetChampsZip", {
                    "sport": sid,
                })
            except EcuabetAPIError:
                payload = {}

            values = []
            if isinstance(payload, dict):
                values = payload.get("Value") or payload.get("value") or payload.get("availableChamps") or []
            if isinstance(values, dict):
                values = [values]

            for item in values if isinstance(values, list) else []:
                if not isinstance(item, dict):
                    continue
                champ_id = item.get("LI") or item.get("id") or item.get("champId")
                name = str(
                    item.get("L")
                    or item.get("LE")
                    or item.get("name")
                    or item.get("champName")
                    or ""
                )
                if champ_id is None:
                    continue
                try:
                    champ_id = int(champ_id)
                except (TypeError, ValueError):
                    continue
                if champ_id in seen:
                    continue
                seen.add(champ_id)
                score = len(self._tokens(league_name) & self._tokens(name)) if league_name else 0
                candidates.append((score, champ_id, name))

            # Algunos despliegues ya incluyen availableChamps en GetEvents.
            try:
                event_payload = self._request("GET", "GetEvents", {
                    "eventCount": 0,
                    "sportId": sid,
                    "champIds": 0,
                })
            except EcuabetAPIError:
                event_payload = {}

            available = event_payload.get("availableChamps", []) if isinstance(event_payload, dict) else []
            if isinstance(available, list):
                for item in available:
                    if not isinstance(item, dict):
                        continue
                    champ_id = item.get("LI") or item.get("id") or item.get("champId")
                    name = str(item.get("L") or item.get("LE") or item.get("name") or item.get("champName") or "")
                    if champ_id is None:
                        continue
                    try:
                        champ_id = int(champ_id)
                    except (TypeError, ValueError):
                        continue
                    if champ_id in seen:
                        continue
                    seen.add(champ_id)
                    score = len(self._tokens(league_name) & self._tokens(name)) if league_name else 0
                    candidates.append((score, champ_id, name))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates

    def buscar_evento(self, local, visitante, sport_id=0, champ_id=0, league_name=""):
        """Busca un partido en cualquier campeonato disponible de Ecuabet."""
        home_target, away_target = self._tokens(local), self._tokens(visitante)
        if not home_target or not away_target:
            raise EcuabetAPIError(f"Nombres de equipos inválidos: {local} vs {visitante}")

        cache_key = (
            self._normalize(local),
            self._normalize(visitante),
            self._normalize(league_name),
        )
        import time
        cached = self._EVENT_CACHE.get(cache_key)
        if cached and time.time() - cached["cached_at"] < self._EVENT_CACHE_TTL:
            return dict(cached["data"])

        champ_ids = []
        if int(champ_id or 0):
            champ_ids.append(int(champ_id))

        discovered = self._candidate_championships(
            sport_id=sport_id,
            league_name=league_name,
        )

        # Si la liga coincide, sus campeonatos van primero. Después se prueban
        # los demás, permitiendo trabajar con cualquier liga de la BD.
        for _, discovered_id, _ in discovered:
            if discovered_id not in champ_ids:
                champ_ids.append(discovered_id)

        if not champ_ids:
            champ_ids.append(0)

        for current_champ_id in champ_ids:
            try:
                payload = self._request("GET", "GetEvents", {
                    "eventCount": 0,
                    "sportId": 66 if not current_champ_id else (sport_id or 66),
                    "champIds": current_champ_id,
                })
            except EcuabetAPIError:
                continue

            candidates = []
            for item in payload.get("events", []) if isinstance(payload, dict) else []:
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

                hs = len(home_target & self._tokens(parts[0]))
                aws = len(away_target & self._tokens(parts[1]))

                if hs and aws:
                    score = hs + aws
                else:
                    hs = len(home_target & self._tokens(parts[1]))
                    aws = len(away_target & self._tokens(parts[0]))
                    if not (hs and aws):
                        continue
                    score = hs + aws - 0.5

                event_champ = int(item.get("champId") or current_champ_id or 0)
                if int(champ_id or 0) == event_champ and event_champ:
                    score += 0.25

                candidates.append((
                    score,
                    int(event_id),
                    event_name,
                    item.get("sportId") or sport_id or 66,
                    event_champ,
                ))

            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                score, event_id, name, found_sport_id, found_champ_id = candidates[0]
                result = {
                    "event_id": event_id,
                    "name": name,
                    "match_score": score,
                    "sport_id": found_sport_id,
                    "champ_id": found_champ_id,
                }
                self._EVENT_CACHE[cache_key] = {
                    "cached_at": time.time(),
                    "data": result,
                }
                return result

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
