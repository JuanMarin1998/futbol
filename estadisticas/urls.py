from django.urls import path
from . import views
from . import views_live
from . import views_odds
from . import views_runners

app_name = "estadisticas"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("live/", views_live.partidos_en_vivo, name="partidos_en_vivo"),
    path("live/<int:fixture_id>/", views_live.detalle_partido_en_vivo, name="detalle_partido_en_vivo"),
    path("api/live/", views_live.api_partidos_en_vivo, name="api_live"),
    path("api/live/<int:fixture_id>/", views_live.api_detalle_partido_en_vivo, name="api_live_detail"),
    path("live/experimento/", views_live.experimento_live, name="experimento_live"),
    path("live/patrones/", views_live.laboratorio_patrones, name="laboratorio_patrones"),
    path("live/patron-oportunidades/", views_live.patron_oportunidades, name="patron_oportunidades"),
    path("live/corredores/", views_runners.corredores_apuestas, name="corredores_apuestas"),
    path("api/live/corredores/estado/", views_runners.api_corredores_estado, name="api_corredores_estado"),
    path("api/live/corredores/iniciar/", views_runners.api_corredores_iniciar, name="api_corredores_iniciar"),
    path("api/live/corredores/pausar/", views_runners.api_corredores_pausar, name="api_corredores_pausar"),
    path("api/live/corredores/ciclo/", views_runners.api_corredores_ciclo, name="api_corredores_ciclo"),
    path("api/live/corredores/liquidar/", views_runners.api_corredores_liquidar, name="api_corredores_liquidar"),
    path("api/live/corredores/reiniciar/", views_runners.api_corredores_reiniciar, name="api_corredores_reiniciar"),
    path("api/live/corredores/borrar-apuestas-hoy/", views_runners.api_corredores_borrar_apuestas_hoy, name="api_corredores_borrar_apuestas_hoy"),
    path("api/live/corredores/borrar-todas-apuestas/", views_runners.api_corredores_borrar_todas_apuestas, name="api_corredores_borrar_todas_apuestas"),
    path("api/live/patron-oportunidades/partidos/", views_live.api_patron_oportunidades_partidos, name="api_patron_oportunidades_partidos"),
    path("api/live/patron-oportunidades/historial/", views_live.api_historial_patron_oportunidades, name="api_historial_patron_oportunidades"),
    path("api/live/patron-oportunidades/<int:ecuabet_event_id>/", views_live.api_simular_patron_oportunidades, name="api_simular_patron_oportunidades"),
    path("live/calendario/", views_live.calendario_ecuabet, name="calendario_ecuabet"),
    path("api/live/calendario/", views_live.api_calendario_ecuabet, name="api_calendario_ecuabet"),
    path("live/contexto/", views_live.contexto_ecuabet, name="contexto_ecuabet"),
    path("api/live/contexto/generar/", views_live.api_generar_contexto_ecuabet, name="api_generar_contexto_ecuabet"),
    path("live/ecuabet/", views_live.ecuabet_live, name="ecuabet_live"),
    path("live/ecuabet/<int:ecuabet_event_id>/", views_live.ecuabet_live_detalle, name="ecuabet_live_detalle"),
    path("api/live/ecuabet/", views_live.api_ecuabet_live, name="api_ecuabet_live"),
    path("api/live/ecuabet/<int:ecuabet_event_id>/", views_live.api_ecuabet_live_detalle, name="api_ecuabet_live_detalle"),
    path("api/live/experimento/start/", views_live.api_live_experiment_start_all, name="api_live_experiment_start_all"),
    path("api/live/experimento/stop/", views_live.api_live_experiment_stop_all, name="api_live_experiment_stop_all"),
    path("api/live/experimento/state/", views_live.api_live_experiment_state, name="api_live_experiment_state"),
    path("api/live/experimento/save-daily/", views_live.api_live_experiment_save_daily, name="api_live_experiment_save_daily"),
    path("api/live/experimento/reset-today/", views_live.api_live_experiment_reset_today, name="api_live_experiment_reset_today"),
    path("api/live/experimento/history/", views_live.api_live_experiment_history, name="api_live_experiment_history"),
    path("api/live/ecuabet/<int:ecuabet_event_id>/experimento/start/", views_live.api_live_experiment_start, name="api_live_experiment_start"),
    path("api/live/ecuabet/<int:ecuabet_event_id>/experimento/stop/", views_live.api_live_experiment_stop, name="api_live_experiment_stop"),
    path("api/live/match/<int:ecuabet_event_id>/flashscore/<str:flashscore_event_id>/", views_live.api_live_match_sources, name="api_live_match_sources"),
    path("partido/<int:partido_id>/cuotas/", views_odds.cuotas_partido, name="cuotas_partido"),
    path("api/partido/<int:partido_id>/cuotas/", views_odds.api_cuotas_partido, name="api_cuotas_partido"),
    path("liga/<str:codigo_liga>/partidos/", views.partidos_liga, name="partidos_liga"),
    path("liga/<str:codigo_liga>/tabla/", views.tabla_liga, name="tabla_liga"),
    path("liga/<str:codigo_liga>/goleadores/", views.goleadores_liga, name="goleadores_liga"),
    path("liga/<str:codigo_liga>/enfrentamiento/", views.enfrentamiento, name="enfrentamiento"),
    path("equipo/<int:id_equipo>/", views.equipo_detalle, name="equipo_detalle"),
]