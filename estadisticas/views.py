from django.shortcuts import render
from . import api_client
from .api_client import LIGAS_PRINCIPALES, FootballDataError


def inicio(request):
    """Página principal: selector de ligas."""
    return render(request, "estadisticas/inicio.html", {"ligas": LIGAS_PRINCIPALES})


def partidos_liga(request, codigo_liga):
    """Muestra los partidos recientes y próximos de una liga, con datos reales de la API."""
    nombre_liga = LIGAS_PRINCIPALES.get(codigo_liga, codigo_liga)
    error = None
    partidos = []

    try:
        partidos_raw = api_client.obtener_partidos(codigo_liga)
        # Nos quedamos con los últimos 15 partidos jugados y los próximos 10 programados
        finalizados = [p for p in partidos_raw if p["status"] == "FINISHED"]
        programados = [p for p in partidos_raw if p["status"] == "SCHEDULED"]

        finalizados = sorted(finalizados, key=lambda p: p["utcDate"], reverse=True)[:15]
        programados = sorted(programados, key=lambda p: p["utcDate"])[:10]

        partidos = {
            "finalizados": finalizados,
            "programados": programados,
        }
    except FootballDataError as e:
        error = str(e)

    return render(
        request,
        "estadisticas/partidos.html",
        {
            "codigo_liga": codigo_liga,
            "nombre_liga": nombre_liga,
            "partidos": partidos,
            "error": error,
            "ligas": LIGAS_PRINCIPALES,
        },
    )


def tabla_liga(request, codigo_liga):
    """Muestra la tabla de posiciones de una liga."""
    nombre_liga = LIGAS_PRINCIPALES.get(codigo_liga, codigo_liga)
    error = None
    tabla = []

    try:
        tabla = api_client.obtener_tabla_posiciones(codigo_liga)
    except FootballDataError as e:
        error = str(e)

    return render(
        request,
        "estadisticas/tabla.html",
        {
            "codigo_liga": codigo_liga,
            "nombre_liga": nombre_liga,
            "tabla": tabla,
            "error": error,
            "ligas": LIGAS_PRINCIPALES,
        },
    )
