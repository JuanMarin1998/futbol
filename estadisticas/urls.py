from django.urls import path
from . import views

app_name = "estadisticas"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("liga/<str:codigo_liga>/partidos/", views.partidos_liga, name="partidos_liga"),
    path("liga/<str:codigo_liga>/tabla/", views.tabla_liga, name="tabla_liga"),
]
