from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime
from estadisticas.api_football_client import LIGAS_API_FOOTBALL, APIFootballError, obtener_equipos, obtener_partidos
from estadisticas.models import Liga, Equipo, Estadio, Partido

class Command(BaseCommand):
    help = "Sincroniza ligas, equipos y partidos desde API-Football."

    def add_arguments(self, parser):
        parser.add_argument("--liga", choices=list(LIGAS_API_FOOTBALL))
        parser.add_argument("--temporada", type=int, default=datetime.now().year)
        parser.add_argument("--partidos", type=int, default=20)
        parser.add_argument("--desde")
        parser.add_argument("--hasta")

    def handle(self, *args, **options):
        codigos = [options["liga"]] if options["liga"] else list(LIGAS_API_FOOTBALL)
        for codigo in codigos:
            config = LIGAS_API_FOOTBALL[codigo]
            self.stdout.write(f"Sincronizando {config['nombre']}...")
            try:
                liga, _ = Liga.objects.update_or_create(
                    api_football_id=config["id"],
                    defaults={"codigo": codigo, "nombre": config["nombre"], "pais": config["pais"]},
                )
                equipos_raw = obtener_equipos(codigo, options["temporada"])
                equipos = {}
                for item in equipos_raw:
                    team, venue = item["team"], item.get("venue") or {}
                    estadio = None
                    if venue.get("id") or venue.get("name"):
                        estadio, _ = Estadio.objects.update_or_create(
                            api_football_id=venue.get("id"),
                            defaults={"nombre": venue.get("name") or "Sin estadio", "ciudad": venue.get("city") or "", "capacidad": venue.get("capacity")},
                        )
                    obj, _ = Equipo.objects.update_or_create(
                        api_football_id=team["id"],
                        defaults={"nombre": team["name"], "nombre_corto": team.get("code") or team["name"][:50], "escudo_url": team.get("logo") or "", "liga": liga, "fundado": team.get("founded"), "estadio": venue.get("name") or "", "estadio_obj": estadio, "pais": config["pais"]},
                    )
                    equipos[team["id"]] = obj

                partidos = obtener_partidos(codigo, options["temporada"], options["desde"], options["hasta"])
                partidos = sorted(partidos, key=lambda x: x.get("fixture", {}).get("date", ""))[-options["partidos"]:]
                guardados = 0
                for item in partidos:
                    fixture, teams = item["fixture"], item["teams"]
                    goals, score = item.get("goals") or {}, item.get("score") or {}
                    if teams["home"]["id"] not in equipos or teams["away"]["id"] not in equipos: continue
                    fecha = parse_datetime(fixture["date"])
                    if not fecha: continue
                    status = (fixture.get("status") or {}).get("short", "")
                    estado = "FINALIZADO" if status in {"FT","AET","PEN"} else "EN_JUEGO" if status in {"1H","2H","ET","P","LIVE"} else "CANCELADO" if status in {"CANC","ABD"} else "APLAZADO" if status in {"PST","SUSP"} else "PROGRAMADO"
                    Partido.objects.update_or_create(
                        api_football_id=fixture["id"],
                        defaults={"liga": liga, "equipo_local": equipos[teams["home"]["id"]], "equipo_visitante": equipos[teams["away"]["id"]], "estadio": equipos[teams["home"]["id"]].estadio_obj, "fecha": fecha, "estado": estado, "estado_api": status, "goles_local": goals.get("home"), "goles_visitante": goals.get("away"), "goles_local_descanso": score.get("halftime", {}).get("home"), "goles_visitante_descanso": score.get("halftime", {}).get("away"), "arbitro": fixture.get("referee") or "", "ronda": (item.get("league") or {}).get("round") or ""},
                    )
                    guardados += 1
                self.stdout.write(self.style.SUCCESS(f"  {len(equipos)} equipos y {guardados} partidos guardados."))
            except APIFootballError as exc:
                self.stderr.write(self.style.ERROR(f"  Error: {exc}"))
        self.stdout.write(self.style.SUCCESS("Sincronización terminada."))
