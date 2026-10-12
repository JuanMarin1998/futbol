"""Prueba en cadena de cinco partidos ficticios: Contexto -> Monitoreo -> Acción.

No consulta APIs, no usa motores de apuestas y no genera recomendaciones.
Ejecutar desde la raíz del repositorio:
    python experimentos/patron_oportunidades/simular_cadena_5_partidos.py
"""
from __future__ import annotations

from contexto_prepartido import PartidoReciente, PerfilEquipo, construir_contexto
from modelo_patron import ContextoPrevio, EstadoPartido, analizar_patron
from monitoreo import monitorear_gol


def estado(minuto, gl, gv, *, posesion, tl, tv, ptl, ptv, al, av):
    return EstadoPartido(
        minuto=minuto,
        goles_local=gl,
        goles_visitante=gv,
        posesion_local=posesion,
        tiros_local=tl,
        tiros_visitante=tv,
        tiros_puerta_local=ptl,
        tiros_puerta_visitante=ptv,
        ataques_peligrosos_local=al,
        ataques_peligrosos_visitante=av,
        mercados_disponibles=(),
        cuotas={},
    )


def contexto(local, visitante, favorito, expectativa):
    return ContextoPrevio(
        local=local,
        visitante=visitante,
        favorito=favorito,
        expectativa=expectativa,
        escenarios_esperados=(
            f"{favorito} genera más peligro",
            f"{favorito} conserva opciones de cumplir la expectativa inicial",
        ),
    )


# Cada caso simula una observación anterior sin gol y luego exactamente un gol.
# Todos los nombres, minutos, marcadores y datos estadísticos son de ejemplo.
CASOS = (
    {
        "contexto": contexto("España", "Croacia", "España", "España llega como favorita ficticia."),
        "antes": estado(10, 0, 0, posesion=61, tl=5, tv=2, ptl=2, ptv=0, al=16, av=7),
        "despues": estado(11, 0, 1, posesion=62, tl=6, tv=3, ptl=3, ptv=1, al=19, av=9),
        "nota": "Croacia marca; España queda por detrás, pero sigue generando peligro.",
    },
    {
        "contexto": contexto("Argentina", "Uruguay", "Argentina", "Argentina llega como favorita ficticia."),
        "antes": estado(24, 0, 0, posesion=56, tl=4, tv=4, ptl=1, ptv=1, al=12, av=12),
        "despues": estado(25, 1, 0, posesion=57, tl=6, tv=4, ptl=2, ptv=1, al=16, av=12),
        "nota": "Argentina marca y pasa a ganar.",
    },
    {
        "contexto": contexto("Brasil", "Colombia", "Brasil", "Brasil llega como favorito ficticio."),
        "antes": estado(37, 0, 0, posesion=58, tl=7, tv=5, ptl=2, ptv=2, al=20, av=17),
        "despues": estado(38, 0, 1, posesion=54, tl=7, tv=7, ptl=2, ptv=3, al=21, av=22),
        "nota": "Colombia marca y los datos ficticios empiezan a favorecer al rival.",
    },
    {
        "contexto": contexto("Francia", "Alemania", "Francia", "Francia llega como favorita ficticia."),
        "antes": estado(63, 0, 1, posesion=55, tl=9, tv=7, ptl=3, ptv=2, al=25, av=20),
        "despues": estado(64, 1, 1, posesion=56, tl=10, tv=7, ptl=4, ptv=2, al=28, av=20),
        "nota": "Francia empata; Acción debe valorar el minuto y el contexto, no descartar nada por el empate.",
    },
    {
        "contexto": contexto("Portugal", "Italia", "Portugal", "Portugal llega como favorito ficticio."),
        "antes": estado(83, 0, 1, posesion=60, tl=11, tv=8, ptl=4, ptv=3, al=31, av=25),
        "despues": estado(84, 1, 1, posesion=61, tl=12, tv=8, ptl=5, ptv=3, al=34, av=25),
        "nota": "Portugal empata en los minutos finales; el tiempo restante importa para Acción.",
    },
)


def ejecutar():
    print("=" * 84)
    print("LABORATORIO EN CADENA — 5 PARTIDOS FICTICIOS")
    print("Sin APIs, sin datos reales, sin motores y sin apuestas.")
    print("Cadena de esta prueba: CONTEXTO -> MONITOREO -> DETONANTE -> INGRESO A ACCIÓN")
    print("Probabilidad, Cálculo y Reacción quedan fuera de esta prueba por ahora.")
    print("=" * 84)

    activados = 0
    for i, caso in enumerate(CASOS, start=1):
        ctx = caso["contexto"]
        antes = caso["antes"]
        despues = caso["despues"]
        nombre = f"{ctx.local} vs {ctx.visitante}"

        print(f"\n\n{'#' * 84}")
        print(f"PARTIDO {i}/5: {nombre}")
        print(f"{'#' * 84}")

        print("\n[1. CONTEXTO — ANTES DEL PARTIDO]")
        print(f"Favorito de referencia: {ctx.favorito}")
        print(f"Expectativa: {ctx.expectativa}")

        print("\n[2. MONITOREO — OBSERVACIÓN ANTERIOR]")
        print(f"Estado: MONITOREANDO | minuto {antes.minuto} | marcador {antes.goles_local}-{antes.goles_visitante}")
        print("Detonante: ninguno; todavía no hay gol nuevo entre observaciones.")
        print("Acción: esperando el siguiente snapshot.")

        print("\n[3. SIMULACIÓN DE EVENTO]")
        print(f"Evento ficticio: {caso['nota']}")
        print(f"Nuevo snapshot: minuto {despues.minuto} | marcador {despues.goles_local}-{despues.goles_visitante}")

        print("\n[4. MONITOREO — COMPROBACIÓN DEL DETONANTE]")
        det = monitorear_gol(ctx, antes, despues)
        print(f"Partido: {det.partido}")
        print(f"Detonante detectado: {'SÍ — GOL NUEVO' if det.detonante_detectado else 'NO'}")
        print(f"Equipo que marcó: {det.equipo_que_marco or 'no determinado'}")
        print(f"Marcador: {det.marcador_anterior} -> {det.marcador_actual} | minuto {det.minuto}")
        print(f"Estado informativo: {det.estado_contexto}")
        print(f"Motivo: {det.motivo}")

        print("\n[5. TRANSICIÓN]")
        if not det.activar_accion:
            print("INGRESO A ACCIÓN: NO. Monitoreo continúa y el caso requiere revisión.")
            continue

        activados += 1
        print("INGRESO A ACCIÓN: SÍ — se entrega el partido a la etapa Acción.")

        print("\n[6. ACCIÓN — EVALUAR CONTEXTO + MINUTO + ESTADÍSTICAS LIVE]")
        analisis = analizar_patron(ctx, despues, estado_anterior=antes)
        print(f"Partido recibido: {analisis.partido}")
        print(f"Minuto y marcador evaluados: {despues.minuto}' | {despues.goles_local}-{despues.goles_visitante}")
        print(f"Lectura de las señales: {analisis.interpretacion_conjunta}")
        print("Expectativas cuestionadas: " + (
            ", ".join(analisis.expectativas_cuestionadas) or "ninguna con la evidencia disponible"
        ))
        print("Datos que requieren atención: " + (
            ", ".join(analisis.datos_faltantes) or "ninguno detectado por esta validación"
        ))
        print("Resultado de Acción: evaluación realizada; no decide apuesta ni calcula una recomendación.")

    print("\n\n" + "=" * 84)
    print("RESUMEN DE LA PRUEBA")
    print(f"Partidos simulados: {len(CASOS)}")
    print(f"Goles nuevos detectados: {activados}")
    print(f"Ingresos a Acción: {activados}")
    print(f"Casos que no ingresaron a Acción: {len(CASOS) - activados}")
    print("Siguiente etapa: validar esta cadena antes de conectar Probabilidad y Cálculo.")
    print("=" * 84)
    return activados


if __name__ == "__main__":
    ejecutar()
