"""Cinco casos simples para probar cómo Acción contrasta Contexto con LIVE.
Todos los equipos, marcadores y estadísticas son ficticios. No genera apuestas.
"""
from __future__ import annotations

from modelo_patron import ContextoPrevio, EstadoPartido, analizar_patron


CONTEXTO = ContextoPrevio(
    local="España",
    visitante="Rival",
    favorito="España",
    expectativa="España llega en mejor forma y esperamos que genere más peligro.",
    escenarios_esperados=(
        "España llega con mejor forma previa",
        "España genera más peligro durante el partido",
    ),
)


def estado(minuto, marcador, tiros, puerta, ataques, posesion):
    return EstadoPartido(
        minuto=minuto,
        goles_local=marcador[0],
        goles_visitante=marcador[1],
        posesion_local=posesion,
        tiros_local=tiros[0],
        tiros_visitante=tiros[1],
        tiros_puerta_local=puerta[0],
        tiros_puerta_visitante=puerta[1],
        ataques_peligrosos_local=ataques[0],
        ataques_peligrosos_visitante=ataques[1],
        mercados_disponibles=("resultado_1x2",),
    )


CASOS = (
    {
        "nombre": "Caso 1 — España pierde, pero sigue creando peligro",
        "marcador": (0, 1),
        "anterior": estado(20, (0, 1), (6, 3), (3, 1), (16, 8), 60),
        "actual": estado(30, (0, 1), (11, 5), (5, 1), (27, 12), 62),
        "lectura_esperada": "CONTEXTO RESPALDADO POR AHORA",
    },
    {
        "nombre": "Caso 2 — España pierde y el rival domina las señales",
        "marcador": (0, 1),
        "anterior": estado(20, (0, 1), (5, 6), (2, 3), (12, 16), 48),
        "actual": estado(30, (0, 1), (7, 12), (2, 6), (17, 29), 43),
        "lectura_esperada": "CONTEXTO CUESTIONADO",
    },
    {
        "nombre": "Caso 3 — España pierde, pero los datos no muestran un dominio claro",
        "marcador": (0, 1),
        "anterior": estado(20, (0, 1), (5, 5), (2, 2), (13, 13), 50),
        "actual": estado(30, (0, 1), (8, 8), (3, 3), (20, 20), 51),
        "lectura_esperada": "SIN EVIDENCIA SUFICIENTE",
    },
    {
        "nombre": "Caso 4 — Empate y España mantiene mejores señales",
        "marcador": (1, 1),
        "anterior": estado(20, (1, 1), (6, 3), (3, 1), (17, 9), 59),
        "actual": estado(30, (1, 1), (11, 5), (5, 1), (28, 13), 61),
        "lectura_esperada": "CONTEXTO RESPALDADO POR AHORA",
    },
    {
        "nombre": "Caso 5 — España gana, pero el rival empieza a presionar",
        "marcador": (1, 0),
        "anterior": estado(20, (1, 0), (9, 4), (4, 1), (23, 12), 60),
        "actual": estado(30, (1, 0), (10, 10), (4, 4), (27, 27), 51),
        "lectura_esperada": "CONTEXTO CUESTIONADO",
    },
)


def clasificar(resultado):
    if resultado.expectativas_cuestionadas:
        return "CONTEXTO CUESTIONADO"
    if resultado.expectativas_vigentes:
        return "CONTEXTO RESPALDADO POR AHORA"
    return "SIN EVIDENCIA SUFICIENTE"


def ejecutar():
    print("PRUEBA BÁSICA: CONTEXTO PREVIO → ACCIÓN LIVE")
    print("DATOS FICTICIOS. La Acción compara evidencias; no apuesta ni decide por el marcador solo.\n")
    resultados = []
    for caso in CASOS:
        resultado = analizar_patron(
            CONTEXTO,
            caso["actual"],
            estado_anterior=caso["anterior"],
            historial=[caso["anterior"]],
        )
        lectura = clasificar(resultado)
        marcador = caso["actual"]
        print("-" * 72)
        print(caso["nombre"])
        print(f"Minuto {marcador.minuto} | marcador {marcador.goles_local}-{marcador.goles_visitante}")
        print(f"Acción determina: {lectura}")
        print(f"Motivo: {resultado.interpretacion_conjunta}")
        print("Expectativa cuestionada: " + (
            "; ".join(resultado.expectativas_cuestionadas) or "ninguna"
        ))
        print("Regla: el marcador por sí solo no confirma ni invalida el contexto.")
        resultados.append((caso["nombre"], lectura, resultado))
    return resultados


if __name__ == "__main__":
    ejecutar()
