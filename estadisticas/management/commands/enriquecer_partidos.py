from datetime import datetime
from django.core.management.base import BaseCommand
from estadisticas.api_football_client import obtener_estadisticas_partido, APIFootballError
from estadisticas.weather_client import obtener_clima_historico, buscar_coordenadas, OpenMeteoError
from estadisticas.models import Partido, EstadisticaPartido, ClimaPartido


def num(value):
    if value is None:
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def integer(value):
    value = num(value)
    return int(value) if value is not None else None


def stat(block, name):
    for item in block:
        if item.get("type") == name:
            return item.get("value")
    return None


class Command(BaseCommand):
    help = "Enriquece partidos guardados con estadísticas de API-Football y clima de Open-Meteo."

    def add_arguments(self, parser):
        parser.add_argument("--partidos", type=int, default=5, help="Cantidad máxima de partidos a procesar.")
        parser.add_argument("--sin-clima", action="store_true", help="No consultar Open-Meteo.")

    def handle(self, *args, **options):
        partidos = Partido.objects.filter(api_football_id__isnull=False).order_by("-fecha")[:options["partidos"]]

        for partido in partidos:
            try:
                data = obtener_estadisticas_partido(partido.api_football_id)
                if len(data) >= 2:
                    home, away = data[0].get("statistics", []), data[1].get("statistics", [])
                    EstadisticaPartido.objects.update_or_create(
                        partido=partido,
                        defaults={
                            "posesion_local": num(stat(home, "Ball Possession")),
                            "posesion_visitante": num(stat(away, "Ball Possession")),
                            "tiros_local": integer(stat(home, "Total Shots")),
                            "tiros_visitante": integer(stat(away, "Total Shots")),
                            "tiros_puerta_local": integer(stat(home, "Shots on Goal")),
                            "tiros_puerta_visitante": integer(stat(away, "Shots on Goal")),
                            "tiros_fuera_local": integer(stat(home, "Shots off Goal")),
                            "tiros_fuera_visitante": integer(stat(away, "Shots off Goal")),
                            "corners_local": integer(stat(home, "Corner Kicks")),
                            "corners_visitante": integer(stat(away, "Corner Kicks")),
                            "faltas_local": integer(stat(home, "Fouls")),
                            "faltas_visitante": integer(stat(away, "Fouls")),
                            "tarjetas_amarillas_local": integer(stat(home, "Yellow Cards")),
                            "tarjetas_amarillas_visitante": integer(stat(away, "Yellow Cards")),
                            "tarjetas_rojas_local": integer(stat(home, "Red Cards")),
                            "tarjetas_rojas_visitante": integer(stat(away, "Red Cards")),
                            "pases_local": integer(stat(home, "Total passes")),
                            "pases_visitante": integer(stat(away, "Total passes")),
                            "precision_pases_local": num(stat(home, "Passes %")),
                            "precision_pases_visitante": num(stat(away, "Passes %")),
                            "ataques_local": integer(stat(home, "Attacks")),
                            "ataques_visitante": integer(stat(away, "Attacks")),
                            "ataques_peligrosos_local": integer(stat(home, "Dangerous Attacks")),
                            "ataques_peligrosos_visitante": integer(stat(away, "Dangerous Attacks")),
                            "fuera_de_juego_local": integer(stat(home, "Offsides")),
                            "fuera_de_juego_visitante": integer(stat(away, "Offsides")),
                            "datos_raw": {"api_football": data},
                        },
                    )
                    self.stdout.write(self.style.SUCCESS(f"Estadísticas guardadas: {partido}"))
            except APIFootballError as exc:
                self.stderr.write(self.style.WARNING(f"Estadísticas omitidas para {partido}: {exc}"))

            if options["sin_clima"]:
                continue

            estadio = partido.estadio
            if not estadio:
                continue

            try:
                if estadio.latitud is None or estadio.longitud is None:
                    geo = buscar_coordenadas(estadio.ciudad or estadio.nombre, estadio.pais)
                    if geo:
                        estadio.latitud = geo.get("latitude")
                        estadio.longitud = geo.get("longitude")
                        estadio.save(update_fields=["latitud", "longitud"])

                if estadio.latitud is None or estadio.longitud is None:
                    continue

                fecha = partido.fecha.astimezone().strftime("%Y-%m-%d")
                hora = partido.fecha.astimezone().strftime("%H:%M")
                clima = obtener_clima_historico(estadio.latitud, estadio.longitud, fecha, hora)
                if clima:
                    ClimaPartido.objects.update_or_create(
                        partido=partido,
                        defaults={
                            "temperatura": clima.get("temperature_2m"),
                            "sensacion_termica": clima.get("apparent_temperature"),
                            "humedad": clima.get("relative_humidity_2m"),
                            "precipitacion": clima.get("precipitation"),
                            "probabilidad_precipitacion": clima.get("precipitation_probability"),
                            "viento_kmh": clima.get("wind_speed_10m"),
                            "codigo_clima": clima.get("weather_code"),
                            "datos_raw": clima,
                        },
                    )
                    self.stdout.write(self.style.SUCCESS(f"Clima guardado: {partido}"))
            except OpenMeteoError as exc:
                self.stderr.write(self.style.WARNING(f"Clima omitido para {partido}: {exc}"))
