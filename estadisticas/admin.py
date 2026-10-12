from django.contrib import admin
from .models import Liga, Equipo, Jugador, Partido, Cuota1X2Snapshot, BettingRunner, BettingRunnerBet, BettingRunnerEvaluation


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


@admin.register(BettingRunner)
class BettingRunnerAdmin(admin.ModelAdmin):
    list_display = ["name", "strategy", "initial_lives", "active", "created_at"]
    list_filter = ["strategy", "active"]
    search_fields = ["name", "key"]


@admin.register(BettingRunnerBet)
class BettingRunnerBetAdmin(admin.ModelAdmin):
    list_display = ["runner", "home_team", "away_team", "market", "price", "stake", "status", "pnl", "placed_at"]
    list_filter = ["runner", "status", "placed_at"]
    search_fields = ["home_team", "away_team", "market"]
    readonly_fields = ["opportunity_snapshot", "placed_at", "settled_at"]


@admin.register(BettingRunnerEvaluation)
class BettingRunnerEvaluationAdmin(admin.ModelAdmin):
    list_display = ["runner", "home_team", "away_team", "action", "selected_market", "evaluated_at"]
    list_filter = ["runner", "action", "evaluated_at"]
    search_fields = ["home_team", "away_team", "reason"]
    readonly_fields = ["snapshot", "evaluated_at"]
