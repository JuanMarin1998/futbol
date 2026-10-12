"""Prueba integral aislada: Contexto -> Monitoreo -> Acción -> Probabilidad -> Cálculo -> Reacción.

Usa únicamente los cinco escenarios ficticios de simular_cadena_5_partidos.py.
No consulta APIs, no usa motores de predicción y no genera apuestas.
La cadena llega siempre a Reacción; las etapas intermedias indican explícitamente
si pueden operar o quedan bloqueadas por falta de evidencia.
Ejecutar desde la raíz del repositorio:
    python experimentos/patron_oportunidades/simular_cadena_completa.py
"""
from __future__ import annotations

from simular_cadena_5_partidos import CASOS
from monitoreo import monitorear_gol
from modelo_patron import analizar_patron


def evaluar_probabilidad(analisis):
    """No fabrica probabilidades: exige una fuente/modelo validado que aún no se conecta."""
    if analisis.anomalias_datos:
        return {
            "estado": "BLOQUEADA_POR_ANOMALIAS",
            "probabilidades": None,
            "motivo": "Hay anomalías en los datos; primero deben resolverse.",
        }
    return {
        "estado": "NO_DISPONIBLE_SIN_MODELO_VALIDADO",
        "probabilidades": None,
        "motivo": (
            "La etapa recibió el análisis contextual, pero todavía no tiene conectado "
            "un modelo de probabilidad validado. No se inventa un porcentaje."
        ),
    }


def evaluar_calculo(probabilidad, estado):
    """Solo calcula valor esperado si existen probabilidad y cuota válidas del mismo mercado."""
    probs = probabilidad["probabilidades"]
    if not probs:
        return {
            "estado": "BLOQUEADO_SIN_PROBABILIDAD",
            "valores": [],
            "motivo": "No hay probabilidades válidas para comparar con cuotas.",
        }

    valores = []
    for mercado, p in probs.items():
        cuota = estado.cuotas.get(mercado)
        if (isinstance(p, (int, float)) and 0 <= p <= 1
                and isinstance(cuota, (int, float)) and cuota > 1):
            valores.append({
                "mercado": mercado,
                "probabilidad": p,
                "cuota": cuota,
                "valor_esperado": round(p * cuota - 1, 4),
            })
    if not valores:
        return {
            "estado": "BLOQUEADO_SIN_CUOTA_COMPATIBLE",
            "valores": [],
            "motivo": "No hay cuota válida para el mismo mercado que una probabilidad válida.",
        }
    return {
        "estado": "CALCULO_PRELIMINAR_DISPONIBLE",
        "valores": valores,
        "motivo": "Cálculo matemático preliminar; no es una recomendación ni una apuesta.",
    }


def evaluar_reaccion(analisis, probabilidad, calculo):
    """La reacción cierra la cadena, incluso si alguna etapa anterior queda bloqueada."""
    if analisis.anomalias_datos:
        return "DETENER_Y_VERIFICAR_DATOS"
    if probabilidad["probabilidades"] is None:
        return "SEGUIR_OBSERVANDO — falta un modelo de probabilidad validado"
    if calculo["estado"] != "CALCULO_PRELIMINAR_DISPONIBLE":
        return "SOLICITAR_MÁS_DATOS — no hay comparación válida con cuotas"
    positivos = [x for x in calculo["valores"] if x["valor_esperado"] > 0]
    if positivos:
        return "SEÑAL_CANDIDATA_PARA_REVISIÓN — no ejecutar apuesta"
    return "DESCARTAR_POR_AHORA — el cálculo no muestra valor esperado positivo"


def ejecutar():
    print("=" * 92)
    print("LABORATORIO — CADENA COMPLETA DE SEIS ETAPAS")
    print("DATOS FICTICIOS. SIN APIs, SIN MOTORES, SIN APUESTAS.")
    print("La salida demuestra el flujo; todavía NO es una prueba con partidos reales.")
    print("=" * 92)

    resumen = {
        "partidos": len(CASOS),
        "detonantes": 0,
        "entradas_accion": 0,
        "llegaron_reaccion": 0,
        "probabilidad_disponible": 0,
        "calculo_disponible": 0,
    }

    for i, caso in enumerate(CASOS, start=1):
        contexto = caso["contexto"]
        anterior = caso["antes"]
        actual = caso["despues"]
        nombre = f"{contexto.local} vs {contexto.visitante}"
        print(f"\n{'-' * 92}\nPARTIDO {i}/{len(CASOS)} — {nombre}\n{'-' * 92}")

        print("[1 CONTEXTO]")
        print(f"Expectativa inicial: {contexto.expectativa}")
        print(f"Favorito de referencia: {contexto.favorito or 'sin favorito claro'}")

        print("\n[2 MONITOREO]")
        print(f"Snapshot anterior: {anterior.minuto}' {anterior.goles_local}-{anterior.goles_visitante}")
        print(f"Snapshot actual:   {actual.minuto}' {actual.goles_local}-{actual.goles_visitante}")
        evento = monitorear_gol(contexto, anterior, actual)
        print(f"Detonante: {evento.estado_contexto} | gol detectado: {'sí' if evento.detonante_detectado else 'no'}")

        print("\n[3 ACCIÓN]")
        if not evento.activar_accion:
            print(f"Evaluación omitida: {evento.motivo}")
            print("[4 PROBABILIDAD] BLOQUEADA: Acción no entregó un evento válido.")
            print("[5 CÁLCULO] BLOQUEADO: no hay entrada válida.")
            print("[6 REACCIÓN] DETENER_Y_VERIFICAR_DATOS")
            resumen["llegaron_reaccion"] += 1
            continue

        resumen["detonantes"] += int(evento.detonante_detectado)
        resumen["entradas_accion"] += 1
        analisis = analizar_patron(contexto, actual, estado_anterior=anterior)
        print(f"Lectura: {analisis.interpretacion_conjunta}")
        print("Expectativas cuestionadas: " + (
            ", ".join(analisis.expectativas_cuestionadas) or "ninguna con evidencia suficiente"
        ))
        print("Anomalías: " + (", ".join(analisis.anomalias_datos) or "ninguna detectada"))

        print("\n[4 PROBABILIDAD]")
        probabilidad = evaluar_probabilidad(analisis)
        print(f"Estado: {probabilidad['estado']}")
        print(f"Motivo: {probabilidad['motivo']}")
        resumen["probabilidad_disponible"] += int(probabilidad["probabilidades"] is not None)

        print("\n[5 CÁLCULO]")
        calculo = evaluar_calculo(probabilidad, actual)
        print(f"Estado: {calculo['estado']}")
        print(f"Motivo: {calculo['motivo']}")
        resumen["calculo_disponible"] += int(calculo["estado"] == "CALCULO_PRELIMINAR_DISPONIBLE")

        print("\n[6 REACCIÓN]")
        print(f"Resultado final: {evaluar_reaccion(analisis, probabilidad, calculo)}")
        resumen["llegaron_reaccion"] += 1

    print(f"\n{'=' * 92}\nRESUMEN FINAL")
    print(f"Partidos procesados: {resumen['partidos']}")
    print(f"Detonantes detectados: {resumen['detonantes']}")
    print(f"Entradas a Acción: {resumen['entradas_accion']}")
    print(f"Partidos que llegaron a Reacción: {resumen['llegaron_reaccion']}")
    print(f"Probabilidades calculadas por un modelo conectado: {resumen['probabilidad_disponible']}")
    print(f"Cálculos con probabilidad y cuota compatibles: {resumen['calculo_disponible']}")
    print("Conclusión: la cadena puede completar el flujo, pero los cálculos quedan bloqueados")
    print("correctamente hasta conectar un modelo validado y cuotas reales compatibles.")
    print("Esta salida no debe confundirse con una validación predictiva ni una prueba LIVE real.")
    print("=" * 92)
    return resumen


if __name__ == "__main__":
    ejecutar()
