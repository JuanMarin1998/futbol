"""Simulación integral ficticia: contexto previo, evolución LIVE y reacción."""
from __future__ import annotations

from contexto_prepartido import PartidoReciente, PerfilEquipo, construir_contexto
from modelo_patron import ContextoPrevio, EstadoPartido, analizar_patron


def crear_perfil(nombre: str, resultados: list[tuple[int, int, str]]) -> PerfilEquipo:
    return PerfilEquipo(
        nombre,
        tuple(PartidoReciente(favor, contra, condicion) for favor, contra, condicion in resultados),
    )


def preparar_contexto() -> tuple[ContextoPrevio, object]:
    """Todos los resultados de este ejemplo son inventados y solo sirven para probar reglas."""
    espana = crear_perfil("España", [
        (2, 0, "local"), (2, 1, "visitante"), (1, 0, "local"),
        (3, 1, "visitante"), (2, 0, "local"),
    ])
    croacia = crear_perfil("Croacia", [
        (0, 1, "visitante"), (1, 1, "local"), (0, 2, "visitante"),
        (1, 0, "local"), (0, 0, "visitante"),
    ])
    informe = construir_contexto(espana, croacia)
    previo = ContextoPrevio(
        local="España",
        visitante="Croacia",
        favorito=informe.favorito_estimado,
        expectativa="La forma ficticia reciente favorece a España; comprobar en el campo si genera más peligro.",
        escenarios_esperados=(
            "España llega con mejor forma reciente",
            "España genera más peligro",
            "Empate posible si Croacia equilibra el partido",
            "Un gol aislado no confirma por sí solo un cambio de dominio",
        ),
    )
    return previo, informe


def snapshot(minuto: int, *, goles_local: int, goles_visitante: int,
             tiros_local: int, tiros_visitante: int, puerta_local: int,
             puerta_visitante: int, ataques_local: int, ataques_visitante: int,
             posesion_local: float, cuota: float = 2.20) -> EstadoPartido:
    return EstadoPartido(
        minuto=minuto, goles_local=goles_local, goles_visitante=goles_visitante,
        posesion_local=posesion_local, tiros_local=tiros_local, tiros_visitante=tiros_visitante,
        tiros_puerta_local=puerta_local, tiros_puerta_visitante=puerta_visitante,
        ataques_peligrosos_local=ataques_local, ataques_peligrosos_visitante=ataques_visitante,
        mercados_disponibles=("resultado_1x2", "total_goles", "proximo_gol"),
        cuotas={"resultado_1x2": cuota, "total_goles": 1.85, "proximo_gol": 2.05},
    )


def ejecutar() -> list:
    previo, informe = preparar_contexto()
    print("=" * 76)
    print("PATRÓN DE OPORTUNIDADES — SIMULACIÓN INTEGRAL CON DATOS FICTICIOS")
    print("AVISO: equipos conocidos, pero todos los resultados, minutos, marcadores, métricas,")
    print("cuotas y probabilidades de este laboratorio son inventados.")
    print("\n1. CONTEXTO ANTES DEL PARTIDO")
    print(f"Partido: {informe.partido}")
    print(f"Estado: {informe.estado}")
    print(f"Mejor forma estimada: {informe.favorito_estimado or 'sin favorito claro'}")
    for evidencia in informe.evidencias:
        print(f"  • {evidencia}")
    print(f"Expectativa que se conserva como referencia: {previo.expectativa}")

    secuencia = [
        ("2. LIVE minuto 15: España controla y aún no hay goles",
         snapshot(15, goles_local=0, goles_visitante=0, tiros_local=6, tiros_visitante=2,
                  puerta_local=3, puerta_visitante=0, ataques_local=18, ataques_visitante=7,
                  posesion_local=61)),
        ("3. LIVE minuto 28: Croacia marca, pero España sigue generando peligro",
         snapshot(28, goles_local=0, goles_visitante=1, tiros_local=10, tiros_visitante=4,
                  puerta_local=5, puerta_visitante=1, ataques_local=29, ataques_visitante=12,
                  posesion_local=63)),
        ("4. LIVE minuto 40: Croacia mejora y los indicadores se contradicen",
         snapshot(40, goles_local=0, goles_visitante=1, tiros_local=11, tiros_visitante=10,
                  puerta_local=5, puerta_visitante=4, ataques_local=31, ataques_visitante=30,
                  posesion_local=51)),
    ]
    anterior = None
    historial = []
    resultados = []
    for titulo, actual in secuencia:
        # Probabilidad inventada solo para comprobar la tubería de cálculo.
        probs_ficticias = {"resultado_1x2": 0.48, "total_goles": 0.57, "proximo_gol": 0.44}
        resultado = analizar_patron(previo, actual, estado_anterior=anterior,
                                    historial=historial, probabilidades_motor=probs_ficticias)
        print("\n" + "=" * 76)
        print(titulo)
        print(f"Marcador: {actual.goles_local}-{actual.goles_visitante} | minuto {actual.minuto}")
        print(f"Lectura conjunta: {resultado.interpretacion_conjunta}")
        print("Expectativas cuestionadas: " +
              (", ".join(resultado.expectativas_cuestionadas) or "ninguna por ahora"))
        print("Mercados a reevaluar: " + ", ".join(x["mercado"] for x in resultado.escenarios_a_reevaluar))
        print(f"Puede evaluar escenarios: {'sí' if resultado.puede_pasar_a_calculo else 'no, faltan datos o hay anomalías'}")
        print("Reacción: NO EMITIR APUESTA AUTOMÁTICA; las probabilidades son ficticias y solo prueban el flujo.")
        for escenario in resultado.escenarios:
            ev = escenario["valor_esperado_estimado"]
            ev_txt = f"{ev:+.1%}" if ev is not None else "no calculable"
            print(f"  • {escenario['mercado']}: cuota ficticia {escenario['cuota_disponible']}, "
                  f"probabilidad ficticia {escenario['probabilidad_motor']}, valor estimado {ev_txt}")
        resultados.append(resultado)
        if anterior is not None:
            historial.append(anterior)
        anterior = actual
    return resultados


if __name__ == "__main__":
    ejecutar()
