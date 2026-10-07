from django.contrib import admin
from .models import Liga, Equipo, Jugador, Partido, Cuota1X2Snapshot


@admin.register(Liga)
class LigaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "codigo", "pais"]


@admin.register(Equipo)
class EquipoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "liga", "estadio", "fundado"]
    list_filter = ["liga"]
    search_fields = ["nombre"]


@admin.register(Jugador)
class JugadorAdmin(admin.ModelAdmin):
    list_display = ["nombre", "equipo", "posicion", "nacionalidad"]
    list_filter = ["equipo", "posicion"]
    search_fields = ["nombre"]


@admin.register(Partido)
class PartidoAdmin(admin.ModelAdmin):
    list_display = ["equipo_local", "equipo_visitante", "fecha", "resultado", "estado"]
    list_filter = ["liga", "estado"]
    date_hierarchy = "fecha"


@admin.register(Cuota1X2Snapshot)
class Cuota1X2SnapshotAdmin(admin.ModelAdmin):
    list_display = ["partido", "cuota_local", "cuota_empate", "cuota_visitante", "es_live", "minuto", "observado_en"]
    list_filter = ["es_live"]
    date_hierarchy = "observado_en"
