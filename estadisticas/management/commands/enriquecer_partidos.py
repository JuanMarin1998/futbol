from django.core.management.base import BaseCommand

from estadisticas.models import Partido, ClimaPartido
from estadisticas.weather_client import (
    obtener_clima_historico,
    buscar_coordenadas,
    OpenMeteoError,
)


class Command(BaseCommand):
    help = "Enriquece partidos de football-data.org con clima histórico de Open-Meteo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--partidos",
            type=int,
            default=5,
            help="Cantidad máxima de partidos a procesar.",
        )
        parser.add_argument(
            "--sin-clima",
            action="store_true",
            help="No consultar Open-Meteo.",
        )

    def handle(self, *args, **options):
        partidos = (
            Partido.objects
            .select_related("equipo_local", "equipo_visitante")
            .filter(id_externo__isnull=False)
            .order_by("-fecha")[: options["partidos"]]
        )

        if not partidos:
            self.stdout.write(
                self.style.WARNING(
                    "No hay partidos sincronizados. Ejecuta primero "
                    "sincronizar_api_football."
                )
            )
            return

        if options["sin_clima"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Hay {len(partidos)} partidos disponibles; se omitió el clima."
                )
            )
            return

        for partido in partidos:
            # football-data.org no proporciona coordenadas de estadio en
            # el endpoint básico, por lo que usamos una geocodificación
            # gratuita para intentar obtenerlas.
            nombre_equipo = partido.equipo_local.nombre

            try:
                geo = buscar_coordenadas(nombre_equipo, partido.liga.pais)

                if not geo:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  No se encontraron coordenadas para {nombre_equipo}."
                        )
                    )
                    continue

                latitud = geo.get("latitude")
                longitud = geo.get("longitude")

                if latitud is None or longitud is None:
                    continue

                clima = obtener_clima_historico(
                    latitud,
                    longitud,
                    partido.fecha.strftime("%Y-%m-%d"),
                    partido.fecha.strftime("%H:%M"),
                )

                if clima:
                    ClimaPartido.objects.update_or_create(
                        partido=partido,
                        defaults={
                            "temperatura": clima.get("temperature_2m"),
                            "sensacion_termica": clima.get("apparent_temperature"),
                            "humedad": clima.get("relative_humidity_2m"),
                            "precipitacion": clima.get("precipitation"),
                            "probabilidad_precipitacion": clima.get(
                                "precipitation_probability"
                            ),
                            "viento_kmh": clima.get("wind_speed_10m"),
                            "codigo_clima": clima.get("weather_code"),
                            "datos_raw": clima,
                            "fuente": "open-meteo",
                        },
                    )
                    self.stdout.write(
                        self.style.SUCCESS(f"  Clima guardado: {partido}")
                    )

            except OpenMeteoError as exc:
                self.stderr.write(
                    self.style.WARNING(
                        f"  Clima omitido para {partido}: {exc}"
                    )
                )
