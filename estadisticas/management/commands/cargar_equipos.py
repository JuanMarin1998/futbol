"""
Comando de gestión: carga los equipos de las 5 ligas principales a la base de datos.

Uso:
    python manage.py cargar_equipos
"""

from django.core.management.base import BaseCommand
from estadisticas import api_client
from estadisticas.api_client import LIGAS_PRINCIPALES, FootballDataError
from estadisticas.models import Liga, Equipo


class Command(BaseCommand):
    help = "Carga los equipos de las 5 ligas principales desde football-data.org"

    def handle(self, *args, **options):
        for codigo, nombre in LIGAS_PRINCIPALES.items():
            self.stdout.write(f"Cargando equipos de {nombre} ({codigo})...")

            liga, _ = Liga.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre})

            try:
                equipos = api_client.obtener_equipos(codigo)
            except FootballDataError as e:
                self.stderr.write(self.style.ERROR(f"  Error: {e}"))
                continue

            for eq in equipos:
                Equipo.objects.update_or_create(
                    id_externo=eq["id"],
                    defaults={
                        "nombre": eq["name"],
                        "nombre_corto": eq.get("shortName", ""),
                        "escudo_url": eq.get("crest", ""),
                        "liga": liga,
                        "fundado": eq.get("founded"),
                        "estadio": eq.get("venue") or "",
                    },
                )

            self.stdout.write(self.style.SUCCESS(f"  {len(equipos)} equipos guardados."))

        self.stdout.write(self.style.SUCCESS("¡Listo!"))
