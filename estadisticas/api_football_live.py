"""Cliente para datos de fútbol en vivo con API-Sports / API-Football v3."""

import os
import requests


class APIFootballLiveClient:
    BASE_URL = "https://v3.football.api-sports.io"

    def __init__(self, api_key=None, timeout=10):
        self.api_key = api_key or os.getenv("API_FOOTBALL_KEY", "")
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("Falta API_FOOTBALL_KEY. Configúralo en .env.")

    def obtener_en_vivo(self):
        response = requests.get(
            f"{self.BASE_URL}/fixtures",
            params={"live": "all"},
            headers={"x-apisports-key": self.api_key},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()