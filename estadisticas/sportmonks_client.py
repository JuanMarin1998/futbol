"""
Cliente mínimo para Sportmonks Football API v3.

Se utiliza únicamente para consultar datos LIVE.
No escribe en PostgreSQL.
"""

import os

import requests


class SportmonksClient:
    """Cliente para consultas de partidos en tiempo real."""

    BASE_URL = "https://api.sportmonks.com/v3/football"

    def __init__(self, token=None, timeout=15):
        self.token = token or os.getenv("SPORTMONKS_TOKEN", "")
        self.timeout = timeout

        if not self.token:
            raise ValueError(
                "Falta SPORTMONKS_TOKEN. Configúralo en el archivo .env."
            )

    def _get(self, endpoint, params=None):
        params = params or {}
        response = requests.get(
            f"{self.BASE_URL}/{endpoint.lstrip('/')}",
            params=params,
            headers={"Authorization": self.token},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def obtener_en_vivo(self, include="participants;scores;periods;events"):
        """Obtiene todos los partidos actualmente en juego disponibles para el token."""
        return self._get(
            "livescores/inplay",
            {"include": include},
        )

    def obtener_actualizaciones(self, include="participants;scores;periods;events"):
        """Obtiene partidos con cambios recientes."""
        return self._get(
            "livescores/latest",
            {"include": include},
        )
