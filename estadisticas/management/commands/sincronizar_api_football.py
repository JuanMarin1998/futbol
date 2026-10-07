from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from estadisticas.api_client import (
    LIGAS_PRINCIPALES,
    FootballDataError,
    obtener_equipos,
    obtener_partidos,
)
from estadisticas.models import Liga, Equipo, Estadio, Partido


class Command(BaseCommand):
    help = "Sincroniza ligas, equipos y partidos desde football-data.org."

    def add_arguments(self, parser):
        parser.add_argument("--liga", choices=list(LIGAS_PRINCIPALES))
        parser.add_argument(
            "--temporada",
            type=int,
            default=datetime.now().year,
            help="Año de inicio de la temporada. Ej.: 2026 para 2026/27.",
        )
        parser.add_argument("--partidos", type=int, default=20)
        parser.add_argument("--desde")
        parser.add_argument("--hasta")

    def handle(self, *args, **options):
        if not options.get("FOOTBALL_DATA_TOKEN", None):
            pass

        codigos = (
            [options["liga"]]
            if options["liga"]
            else list(LIGAS_PRINCIPALES)
        )

        for codigo in codigos:
            nombre_liga = LIGAS_PRINCIPALES[codigo]
            self.stdout.write(f"Sincronizando {nombre_liga}...")

            try:
                # football-data.org usa el código de competición como identificador.
                liga, _ = Liga.objects.update_or_create(
                    codigo=codigo,
                    defaults={
                        "nombre": nombre_liga,
                        "pais": {
                            "PD": "España",
                            "PL": "Inglaterra",
                            "BL1": "Alemania",
                            "SA": "Italia",
                            "FL1": "Francia",
                        }.get(codigo, ""),
                    },
                )

                equipos_raw = obtener_equipos(codigo)
                equipos = {}

                for item in equipos_raw:
                    equipo, _ = Equipo.objects.update_or_create(
                        id_externo=item.get("id"),
                        defaults={
                            "nombre": item.get("name", ""),
                            "nombre_corto": (
                                item.get("shortName")
                                or item.get("tla")
                                or item.get("name", "")[:50]
                            )[:50],
                            "escudo_url": item.get("crest") or "",
                            "liga": liga,
                            "fundado": item.get("founded"),
                            "pais": (
                                item.get("area", {}).get("name")
                                or liga.pais
                            ),
                            "estadio": "",
                            "estadio_obj": None,
                        },
                    )
                    equipos[item.get("id")] = equipo

                partidos_raw = obtener_partidos(
                    codigo,
                    fecha_desde=options.get("desde"),
                    fecha_hasta=options.get("hasta"),
                )

                # Si no se especifica un rango, tomamos los más recientes.
                partidos_raw = sorted(
                    partidos_raw,
                    key=lambda x: x.get("utcDate", ""),
                )[-options["partidos"] :]

                guardados = 0

                for item in partidos_raw:
                    local_id = item.get("homeTeam", {}).get("id")
                    visitante_id = item.get("awayTeam", {}).get("id")

                    if local_id not in equipos or visitante_id not in equipos:
                        continue

                    fecha = parse_datetime(item.get("utcDate", ""))
                    if not fecha:
                        continue

                    score = item.get("score") or {}
                    full_time = score.get("fullTime") or {}
                    half_time = score.get("halfTime") or {}

                    status = item.get("status", "")
                    estado = {
                        "FINISHED": "FINALIZADO",
                        "IN_PLAY": "EN_JUEGO",
                        "PAUSED": "EN_JUEGO",
                        "SCHEDULED": "PROGRAMADO",
                        "TIMED": "PROGRAMADO",
                        "POSTPONED": "APLAZADO",
                        "SUSPENDED": "APLAZADO",
                        "CANCELLED": "CANCELADO",
                    }.get(status, "PROGRAMADO")

                    Partido.objects.update_or_create(
                        id_externo=item.get("id"),
                        defaults={
                            "liga": liga,
                            "equipo_local": equipos[local_id],
                            "equipo_visitante": equipos[visitante_id],
                            "fecha": fecha,
                            "estado": estado,
                            "estado_api": status,
                            "goles_local": full_time.get("home"),
                            "goles_visitante": full_time.get("away"),
                            "goles_local_descanso": half_time.get("home"),
                            "goles_visitante_descanso": half_time.get("away"),
                            "jornada": item.get("matchday"),
                            "arbitro": (
                                (item.get("referees") or [{}])[0].get("name", "")
                            ),
                            "ronda": item.get("stage", "") or "",
                            # Estos campos se conservan por compatibilidad
                            # con la versión anterior, pero ya no se usan.
                            "api_football_id": None,
                            "estadio": None,
                        },
                    )
                    guardados += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {len(equipos)} equipos y {guardados} partidos guardados."
                    )
                )

            except FootballDataError as exc:
                self.stderr.write(self.style.ERROR(f"  Error: {exc}"))

        self.stdout.write(self.style.SUCCESS("Sincronización terminada."))
