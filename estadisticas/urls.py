from django.urls import path
from . import views

app_name = "estadisticas"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("liga/<str:codigo_liga>/partidos/", views.partidos_liga, name="partidos_liga"),
    path("liga/<str:codigo_liga>/tabla/", views.tabla_liga, name="tabla_liga"),
    path("liga/<str:codigo_liga>/goleadores/", views.goleadores_liga, name="goleadores_liga"),
    path("liga/<str:codigo_liga>/enfrentamiento/", views.enfrentamiento, name="enfrentamiento"),
    path("equipo/<int:id_equipo>/", views.equipo_detalle, name="equipo_detalle"),
]
