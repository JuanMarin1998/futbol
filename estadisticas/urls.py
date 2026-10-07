from django.urls import path
from . import views
from . import views_live

app_name = "estadisticas"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("live/", views_live.partidos_en_vivo, name="partidos_en_vivo"),
    path("live/<int:fixture_id>/", views_live.detalle_partido_en_vivo, name="detalle_partido_en_vivo"),
    path("api/live/", views_live.api_partidos_en_vivo, name="api_live"),
    path("api/live/<int:fixture_id>/", views_live.api_detalle_partido_en_vivo, name="api_live_detail"),
    path("liga/<str:codigo_liga>/partidos/", views.partidos_liga, name="partidos_liga"),
    path("liga/<str:codigo_liga>/tabla/", views.tabla_liga, name="tabla_liga"),
    path("liga/<str:codigo_liga>/goleadores/", views.goleadores_liga, name="goleadores_liga"),
    path("liga/<str:codigo_liga>/enfrentamiento/", views.enfrentamiento, name="enfrentamiento"),
    path("equipo/<int:id_equipo>/", views.equipo_detalle, name="equipo_detalle"),
]