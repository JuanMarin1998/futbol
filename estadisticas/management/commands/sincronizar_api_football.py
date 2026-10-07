from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from estadisticas.api_client import (
    LIGAS_PRINCIPALES,
    FootballDataError,
    obtener_equipos,
    obtener_partidos,
    obtener_tabla_posiciones,
    obtener_goleadores,
)
from estadisticas.models import (
    Liga,
    Equipo,
    Jugador,
    Estadio,
    Partido,
    TablaPosicion,
    GoleadorTemporada,
)


class Command(BaseCommand):
    help = "Descarga y guarda en la base de datos los datos disponibles de football-data.org."

    def add_arguments(self, parser):
        parser.add_argument("--liga", choices=list(LIGAS_PRINCIPALES))
        parser.add_argument(
            "--temporada",
            type=int,
            default=datetime.now().year,
            help="Año de inicio de la temporada. Ej.: 2026 para 2026/27.",
        )
        parser.add_argument(
            "--partidos",
            type=int,
            default=0,
            help="Cantidad máxima de partidos. 0 = todos los partidos devueltos por la API.",
        )
        parser.add_argument("--desde")
        parser.add_argument("--hasta")

    def guardar_jugador(self, datos, equipo):
        posicion_api = (datos.get("position") or "").lower()
        posicion = {
            "goalkeeper": "POR",
            "defender": "DEF",
            "midfielder": "MED",
            "attacker": "DEL",
            "forward": "DEL",
        }.get(posicion_api, "")

        fecha_nacimiento = None
        fecha_raw = datos.get("dateOfBirth")
        if fecha_raw:
            fecha_nacimiento = fecha_raw[:10]

        jugador, _ = Jugador.objects.update_or_create(
            id_externo=datos.get("id"),
            defaults={
                "nombre": datos.get("name", ""),
                "equipo": equipo,
                "posicion": posicion,
                "posicion_detalle": datos.get("position") or "",
                "fecha_nacimiento": fecha_nacimiento,
                "nacionalidad": datos.get("nationality") or "",
                "dorsal": datos.get("shirtNumber"),
                "foto_url": "",
                "lesionado": False,
                "api_football_id": None,
            },
        )
        return jugador

    def handle(self, *args, **options):
        codigos = [options["liga"]] if options["liga"] else list(LIGAS_PRINCIPALES)

        for codigo in codigos:
            nombre_liga = LIGAS_PRINCIPALES[codigo]
            self.stdout.write(self.style.NOTICE(f"Sincronizando {nombre_liga}..."))

            try:
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

                # 1) Equipos
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
                            "pais": item.get("area", {}).get("name") or liga.pais,
                            "estadio": "",
                            "estadio_obj": None,
                            "api_football_id": None,
                        },
                    )
                    equipos[item.get("id")] = equipo

                # 2) Partidos de la temporada/rango indicado.
                partidos_raw = obtener_partidos(
                    codigo,
                    fecha_desde=options.get("desde"),
                    fecha_hasta=options.get("hasta"),
                    temporada=options.get("temporada"),
                )
                partidos_raw = sorted(partidos_raw, key=lambda x: x.get("utcDate", ""))
                if options["partidos"] > 0:
                    partidos_raw = partidos_raw[-options["partidos"]:]

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
                            "arbitro": (item.get("referees") or [{}])[0].get("name", ""),
                            "ronda": item.get("stage", "") or "",
                            "api_football_id": None,
                            "estadio": None,
                        },
                    )
                    guardados += 1

                # 3) Tabla de posiciones.
                tabla = obtener_tabla_posiciones(codigo)
                for fila in tabla:
                    team_id = (fila.get("team") or {}).get("id")
                    equipo = equipos.get(team_id)
                    if not equipo:
                        continue

                    TablaPosicion.objects.update_or_create(
                        liga=liga,
                        temporada=options["temporada"],
                        equipo=equipo,
                        defaults={
                            "posicion": fila.get("position") or 0,
                            "partidos_jugados": fila.get("playedGames") or 0,
                            "victorias": fila.get("won") or 0,
                            "empates": fila.get("draw") or 0,
                            "derrotas": fila.get("lost") or 0,
                            "goles_favor": fila.get("goalsFor") or 0,
                            "goles_contra": fila.get("goalsAgainst") or 0,
                            "diferencia_goles": fila.get("goalDifference") or 0,
                            "puntos": fila.get("points") or 0,
                            "forma": fila.get("form") or "",
                        },
                    )

                # 4) Goleadores.
                goleadores = obtener_goleadores(codigo, limite=100)
                for indice, fila in enumerate(goleadores, start=1):
                    player_data = fila.get("player") or {}
                    team_data = fila.get("team") or {}
                    team_id = team_data.get("id")
                    equipo = equipos.get(team_id)
                    player_id = player_data.get("id")

                    if not equipo or not player_id:
                        continue

                    jugador, _ = Jugador.objects.update_or_create(
                        id_externo=player_id,
                        defaults={
                            "nombre": player_data.get("name", ""),
                            "equipo": equipo,
                            "posicion": "",
                            "posicion_detalle": "",
                            "fecha_nacimiento": (player_data.get("dateOfBirth") or "")[:10] or None,
                            "nacionalidad": player_data.get("nationality") or "",
                            "dorsal": None,
                            "foto_url": "",
                            "lesionado": False,
                            "api_football_id": None,
                        },
                    )

                    GoleadorTemporada.objects.update_or_create(
                        liga=liga,
                        temporada=options["temporada"],
                        jugador=jugador,
                        equipo=equipo,
                        defaults={
                            "posicion": indice,
                            "goles": fila.get("goals") or 0,
                            "asistencias": fila.get("assists"),
                            "penaltis": fila.get("penalties"),
                            "partidos_jugados": fila.get("playedMatches"),
                        },
                    )

                # Las plantillas NO se descargan aquí.
                # Obtener el detalle de cada equipo requiere una petición por equipo
                # y puede agotar rápidamente el límite de football-data.org.
                # Se descargan por separado con el comando cargar_plantillas.

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {len(equipos)} equipos, {guardados} partidos, "
                        f"{len(tabla)} posiciones y {len(goleadores)} goleadores guardados."
                    )
                )

            except FootballDataError as exc:
                self.stderr.write(self.style.ERROR(f"  Error: {exc}"))

        self.stdout.write(self.style.SUCCESS("Sincronización terminada."))
