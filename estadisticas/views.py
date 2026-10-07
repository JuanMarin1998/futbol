from django.shortcuts import render
from django.db.models import Q

from .models import (
    Liga,
    Equipo,
    Jugador,
    Partido,
    TablaPosicion,
    GoleadorTemporada,
)


def _ligas_menu():
    """Devuelve las ligas disponibles directamente desde PostgreSQL."""
    return dict(Liga.objects.order_by("nombre").values_list("codigo", "nombre"))


def inicio(request):
    return render(request, "estadisticas/inicio.html", {"ligas": _ligas_menu()})


def _equipo_dict(equipo):
    return {
        "id": equipo.id_externo,
        "name": equipo.nombre,
        "shortName": equipo.nombre_corto,
        "crest": equipo.escudo_url,
        "founded": equipo.fundado,
        "venue": equipo.estadio or (equipo.estadio_obj.nombre if equipo.estadio_obj else ""),
    }


def _partido_dict(partido):
    return {
        "id": partido.id_externo,
        "utcDate": partido.fecha.isoformat(),
        "status": partido.estado_api,
        "homeTeam": {
            "id": partido.equipo_local.id_externo,
            "name": partido.equipo_local.nombre,
        },
        "awayTeam": {
            "id": partido.equipo_visitante.id_externo,
            "name": partido.equipo_visitante.nombre,
        },
        "score": {
            "fullTime": {
                "home": partido.goles_local,
                "away": partido.goles_visitante,
            }
        },
        "competition": {
            "name": partido.liga.nombre,
        },
    }


def partidos_liga(request, codigo_liga):
    ligas_menu = _ligas_menu()
    nombre_liga = ligas_menu.get(codigo_liga, codigo_liga)
    liga = Liga.objects.filter(codigo=codigo_liga).first()
    temporada = request.GET.get("temporada")

    if temporada:
        try:
            temporada = int(temporada)
        except ValueError:
            temporada = None

    if temporada is None:
        ultima = Partido.objects.filter(liga=liga).order_by("-temporada").first() if liga else None
        temporada = ultima.temporada if ultima else None

    temporadas = list(
        Partido.objects.filter(liga=liga)
        .values_list("temporada", flat=True)
        .distinct()
        .order_by("-temporada")
    ) if liga else []

    partidos = {"finalizados": [], "programados": []}
    error = None

    if liga and temporada:
        qs = Partido.objects.filter(
            liga=liga, temporada=temporada
        ).select_related("equipo_local", "equipo_visitante", "liga")

        finalizados = qs.filter(estado="FINALIZADO").order_by("-fecha")[:15]
        programados = qs.filter(
            estado__in=["PROGRAMADO", "EN_JUEGO"]
        ).order_by("fecha")[:10]

        partidos = {
            "finalizados": [_partido_dict(p) for p in finalizados],
            "programados": [_partido_dict(p) for p in programados],
        }
    else:
        error = "No existen datos de esta liga/temporada en la base de datos. Ejecuta la sincronización."

    return render(
        request,
        "estadisticas/partidos.html",
        {
            "codigo_liga": codigo_liga,
            "nombre_liga": nombre_liga,
            "partidos": partidos,
            "temporada": temporada,
            "temporadas": temporadas,
            "error": error,
            "ligas": ligas_menu,
            "seccion": "partidos",
        },
    )


def equipo_detalle(request, id_equipo):
    ligas_menu = _ligas_menu()
    equipo = (
        Equipo.objects.select_related("liga", "estadio_obj")
        .filter(id_externo=id_equipo)
        .first()
    )
    error = None
    estadisticas = None
    partidos_recientes = []
    plantilla_por_posicion = {}

    if not equipo:
        error = "Equipo no encontrado en la base de datos."
    else:
        partidos = Partido.objects.filter(
            Q(equipo_local=equipo) | Q(equipo_visitante=equipo),
            estado="FINALIZADO",
        ).select_related("equipo_local", "equipo_visitante", "liga").order_by("-fecha")

        recientes = list(partidos[:10])
        victorias = empates = derrotas = goles_favor = goles_contra = 0
        racha = []

        for partido in recientes:
            if partido.equipo_local_id == equipo.id:
                gf, gc = partido.goles_local, partido.goles_visitante
            else:
                gf, gc = partido.goles_visitante, partido.goles_local

            if gf is None or gc is None:
                continue

            goles_favor += gf
            goles_contra += gc

            if gf > gc:
                victorias += 1
                racha.append("G")
            elif gf == gc:
                empates += 1
                racha.append("E")
            else:
                derrotas += 1
                racha.append("P")

        jugados = victorias + empates + derrotas
        estadisticas = {
            "jugados": jugados,
            "victorias": victorias,
            "empates": empates,
            "derrotas": derrotas,
            "goles_favor": goles_favor,
            "goles_contra": goles_contra,
            "diferencia_goles": goles_favor - goles_contra,
            "promedio_goles_favor": round(goles_favor / jugados, 2) if jugados else 0,
            "promedio_goles_contra": round(goles_contra / jugados, 2) if jugados else 0,
            "racha": racha,
        }
        partidos_recientes = [_partido_dict(p) for p in recientes]

        jugadores = Jugador.objects.filter(equipo=equipo).order_by("posicion", "nombre")
        nombres_posicion = {
            "POR": "Portero",
            "DEF": "Defensa",
            "MED": "Mediocampista",
            "DEL": "Delantero",
            "": "Sin posición",
        }
        for jugador in jugadores:
            posicion = nombres_posicion.get(jugador.posicion, jugador.posicion or "Sin posición")
            plantilla_por_posicion.setdefault(posicion, []).append({
                "name": jugador.nombre,
                "nationality": jugador.nacionalidad,
                "dateOfBirth": jugador.fecha_nacimiento,
            })

    return render(
        request,
        "estadisticas/equipo.html",
        {
            "equipo": _equipo_dict(equipo) if equipo else None,
            "estadisticas": estadisticas,
            "partidos_recientes": partidos_recientes,
            "plantilla_por_posicion": plantilla_por_posicion,
            "error": error,
            "ligas": ligas_menu,
        },
    )


def tabla_liga(request, codigo_liga):
    ligas_menu = _ligas_menu()
    nombre_liga = ligas_menu.get(codigo_liga, codigo_liga)
    liga = Liga.objects.filter(codigo=codigo_liga).first()
    temporada = request.GET.get("temporada")

    if temporada:
        try:
            temporada = int(temporada)
        except ValueError:
            temporada = None

    if temporada is None:
        ultima = TablaPosicion.objects.filter(liga=liga).order_by("-temporada").first() if liga else None
        temporada = ultima.temporada if ultima else None

    temporadas = list(
        TablaPosicion.objects.filter(liga=liga)
        .values_list("temporada", flat=True)
        .distinct()
        .order_by("-temporada")
    ) if liga else []

    filas = []
    error = None

    if liga and temporada:
        posiciones = TablaPosicion.objects.filter(
            liga=liga, temporada=temporada
        ).select_related("equipo").order_by("posicion")

        for fila in posiciones:
            filas.append({
                "position": fila.posicion,
                "team": {
                    "id": fila.equipo.id_externo,
                    "name": fila.equipo.nombre,
                },
                "playedGames": fila.partidos_jugados,
                "won": fila.victorias,
                "draw": fila.empates,
                "lost": fila.derrotas,
                "goalsFor": fila.goles_favor,
                "goalsAgainst": fila.goles_contra,
                "goalDifference": fila.diferencia_goles,
                "points": fila.puntos,
            })
    else:
        error = "No hay tabla guardada para esta liga. Ejecuta la sincronización."

    return render(
        request,
        "estadisticas/tabla.html",
        {
            "codigo_liga": codigo_liga,
            "nombre_liga": nombre_liga,
            "tabla": filas,
            "temporada": temporada,
            "temporadas": temporadas,
            "error": error,
            "ligas": ligas_menu,
            "seccion": "tabla",
        },
    )


def goleadores_liga(request, codigo_liga):
    ligas_menu = _ligas_menu()
    nombre_liga = ligas_menu.get(codigo_liga, codigo_liga)
    liga = Liga.objects.filter(codigo=codigo_liga).first()
    temporada = request.GET.get("temporada")

    if temporada:
        try:
            temporada = int(temporada)
        except ValueError:
            temporada = None

    if temporada is None:
        ultimo = GoleadorTemporada.objects.filter(liga=liga).order_by("-temporada").first() if liga else None
        temporada = ultimo.temporada if ultimo else None

    temporadas = list(
        GoleadorTemporada.objects.filter(liga=liga)
        .values_list("temporada", flat=True)
        .distinct()
        .order_by("-temporada")
    ) if liga else []

    goleadores = []
    error = None

    if liga and temporada:
        registros = GoleadorTemporada.objects.filter(
            liga=liga, temporada=temporada
        ).select_related("jugador", "equipo").order_by("posicion")

        for g in registros:
            goleadores.append({
                "player": {"name": g.jugador.nombre},
                "team": {
                    "id": g.equipo.id_externo,
                    "name": g.equipo.nombre,
                },
                "goals": g.goles,
                "assists": g.asistencias,
                "penalties": g.penaltis,
                "playedMatches": g.partidos_jugados,
            })
    else:
        error = "No hay goleadores guardados para esta liga. Ejecuta la sincronización."

    return render(
        request,
        "estadisticas/goleadores.html",
        {
            "codigo_liga": codigo_liga,
            "nombre_liga": nombre_liga,
            "goleadores": goleadores,
            "temporada": temporada,
            "temporadas": temporadas,
            "error": error,
            "ligas": ligas_menu,
            "seccion": "goleadores",
        },
    )


def enfrentamiento(request, codigo_liga):
    ligas_menu = _ligas_menu()
    nombre_liga = ligas_menu.get(codigo_liga, codigo_liga)
    liga = Liga.objects.filter(codigo=codigo_liga).first()
    equipos = list(
        Equipo.objects.filter(liga=liga).order_by("nombre")
    ) if liga else []

    id_equipo_a = request.GET.get("equipo_a")
    id_equipo_b = request.GET.get("equipo_b")
    resultado = None
    error = None

    if id_equipo_a and id_equipo_b and id_equipo_a != id_equipo_b:
        try:
            a = Equipo.objects.get(id_externo=int(id_equipo_a))
            b = Equipo.objects.get(id_externo=int(id_equipo_b))

            partidos = Partido.objects.filter(
                Q(equipo_local=a, equipo_visitante=b)
                | Q(equipo_local=b, equipo_visitante=a),
                estado="FINALIZADO",
            ).select_related("equipo_local", "equipo_visitante", "liga").order_by("-fecha")

            victorias_a = victorias_b = empates = goles_totales = 0

            for partido in partidos:
                if partido.goles_local is None or partido.goles_visitante is None:
                    continue

                if partido.equipo_local_id == a.id:
                    ga, gb = partido.goles_local, partido.goles_visitante
                else:
                    ga, gb = partido.goles_visitante, partido.goles_local

                goles_totales += ga + gb
                if ga > gb:
                    victorias_a += 1
                elif ga < gb:
                    victorias_b += 1
                else:
                    empates += 1

            resultado = {
                "aggregates": {
                    "numberOfMatches": len(partidos),
                    "homeTeam": {"name": a.nombre, "wins": victorias_a, "draws": empates},
                    "awayTeam": {"name": b.nombre, "wins": victorias_b},
                    "totalGoals": goles_totales,
                },
                "matches": [_partido_dict(p) for p in partidos],
            }
        except (Equipo.DoesNotExist, ValueError):
            error = "No se encontraron los equipos seleccionados en la base de datos."

    return render(
        request,
        "estadisticas/enfrentamiento.html",
        {
            "codigo_liga": codigo_liga,
            "nombre_liga": nombre_liga,
            "equipos": [_equipo_dict(e) for e in equipos],
            "resultado": resultado,
            "id_equipo_a": id_equipo_a,
            "id_equipo_b": id_equipo_b,
            "error": error,
            "ligas": ligas_menu,
            "seccion": "enfrentamiento",
        },
    )
