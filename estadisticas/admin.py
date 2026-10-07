from django.contrib import admin
from .models import Liga, Equipo, Jugador, Partido


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
