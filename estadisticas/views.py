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
            "seccion": "partidos",
        },
    )


def equipo_detalle(request, id_equipo):
    """Muestra el detalle de un equipo: plantilla de jugadores y estadísticas recientes."""
    error = None
    equipo = None
    estadisticas = None
    partidos_recientes = []

    try:
        equipo = api_client.obtener_equipo(id_equipo)
        partidos_recientes = api_client.obtener_partidos_equipo(id_equipo, limite=10)
        estadisticas = api_client.calcular_estadisticas_equipo(id_equipo, partidos_recientes)
    except FootballDataError as e:
        error = str(e)

    # Agrupamos la plantilla por posición para que se vea más ordenada
    plantilla_por_posicion = {}
    if equipo:
        for jugador in equipo.get("squad", []):
            posicion = jugador.get("position") or "Sin posición"
            plantilla_por_posicion.setdefault(posicion, []).append(jugador)

    return render(
        request,
        "estadisticas/equipo.html",
        {
            "equipo": equipo,
            "estadisticas": estadisticas,
            "partidos_recientes": partidos_recientes,
            "plantilla_por_posicion": plantilla_por_posicion,
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
            "seccion": "tabla",
        },
    )


def goleadores_liga(request, codigo_liga):
    """Muestra el ranking de goleadores de una liga."""
    nombre_liga = LIGAS_PRINCIPALES.get(codigo_liga, codigo_liga)
    error = None
    goleadores = []

    try:
        goleadores = api_client.obtener_goleadores(codigo_liga, limite=20)
    except FootballDataError as e:
        error = str(e)

    return render(
        request,
        "estadisticas/goleadores.html",
        {
            "codigo_liga": codigo_liga,
            "nombre_liga": nombre_liga,
            "goleadores": goleadores,
            "error": error,
            "ligas": LIGAS_PRINCIPALES,
            "seccion": "goleadores",
        },
    )


def enfrentamiento(request, codigo_liga):
    """
    Formulario + resultado de head-to-head: el usuario elige dos equipos de la liga
    y se muestra el historial real de enfrentamientos directos entre ambos.
    """
    nombre_liga = LIGAS_PRINCIPALES.get(codigo_liga, codigo_liga)
    error = None
    equipos = []
    resultado = None

    id_equipo_a = request.GET.get("equipo_a")
    id_equipo_b = request.GET.get("equipo_b")

    try:
        equipos = api_client.obtener_equipos(codigo_liga)
    except FootballDataError as e:
        error = str(e)

    if not error and id_equipo_a and id_equipo_b and id_equipo_a != id_equipo_b:
        try:
            id_a, id_b = int(id_equipo_a), int(id_equipo_b)

            # Buscamos entre los partidos de ambos equipos (pasados y futuros,
            # sin restringir a la liga actual) alguno jugado entre ellos.
            partidos_a = api_client.obtener_partidos_equipo(id_a, limite=50, estado=None)
            partido_encontrado = api_client.buscar_proximo_o_ultimo_enfrentamiento(id_a, id_b, partidos_a)

            if not partido_encontrado:
                error = "No se encontró ningún partido entre estos dos equipos en el historial disponible por la API."
            else:
                resultado = api_client.obtener_head2head(partido_encontrado["id"], limite=10)
        except FootballDataError as e:
            error = str(e)

    return render(
        request,
        "estadisticas/enfrentamiento.html",
        {
            "codigo_liga": codigo_liga,
            "nombre_liga": nombre_liga,
            "equipos": equipos,
            "resultado": resultado,
            "id_equipo_a": id_equipo_a,
            "id_equipo_b": id_equipo_b,
            "error": error,
            "ligas": LIGAS_PRINCIPALES,
            "seccion": "enfrentamiento",
        },
    )
