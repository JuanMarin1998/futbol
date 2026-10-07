from django.core.management.base import BaseCommand
from estadisticas.api_client import FootballDataError, obtener_equipo
from estadisticas.models import Equipo, Jugador


class Command(BaseCommand):
    help = "Descarga las plantillas de jugadores por separado para evitar saturar el límite de la API."

    def add_arguments(self, parser):
        parser.add_argument("--liga", help="Código de liga, por ejemplo PD.")
        parser.add_argument("--equipo", type=int, help="ID externo de un equipo concreto.")
        parser.add_argument("--espera", type=float, default=1.5, help="Segundos entre peticiones.")

    def guardar_jugador(self, datos, equipo):
        posicion_api = (datos.get("position") or "").lower()
        posicion = {
            "goalkeeper": "POR",
            "defender": "DEF",
            "midfielder": "MED",
            "attacker": "DEL",
            "forward": "DEL",
        }.get(posicion_api, "")

        Jugador.objects.update_or_create(
            id_externo=datos.get("id"),
            defaults={
                "nombre": datos.get("name", ""),
                "equipo": equipo,
                "posicion": posicion,
                "posicion_detalle": datos.get("position") or "",
                "fecha_nacimiento": (datos.get("dateOfBirth") or "")[:10] or None,
                "nacionalidad": datos.get("nationality") or "",
                "dorsal": datos.get("shirtNumber"),
                "foto_url": "",
                "lesionado": False,
                "api_football_id": None,
            },
        )

    def handle(self, *args, **options):
        qs = Equipo.objects.all().order_by("liga_id", "nombre")

        if options.get("liga"):
            qs = qs.filter(liga__codigo=options["liga"])

        if options.get("equipo"):
            qs = qs.filter(id_externo=options["equipo"])

        equipos = list(qs)
        if not equipos:
            self.stdout.write(self.style.WARNING("No se encontraron equipos."))
            return

        guardados = 0

        for indice, equipo in enumerate(equipos, start=1):
            self.stdout.write(f"[{indice}/{len(equipos)}] {equipo.nombre}...")

            try:
                detalle = obtener_equipo(equipo.id_externo)
                plantilla = detalle.get("squad", [])

                for jugador in plantilla:
                    self.guardar_jugador(jugador, equipo)
                    guardados += 1

                self.stdout.write(
                    self.style.SUCCESS(f"  {len(plantilla)} jugadores guardados.")
                )

            except FootballDataError as exc:
                self.stderr.write(self.style.ERROR(f"  Error: {exc}"))
                if "429" in str(exc):
                    self.stderr.write(
                        self.style.WARNING(
                            "Límite de la API alcanzado. Espera el tiempo indicado y vuelve a ejecutar."
                        )
                    )
                    break

            if indice < len(equipos) and options["espera"] > 0:
                import time
                time.sleep(options["espera"])

        self.stdout.write(
            self.style.SUCCESS(f"Proceso terminado. Jugadores guardados/actualizados: {guardados}.")
        )
