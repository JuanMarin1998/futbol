"""Prototipo aislado del Patrón de Oportunidades; no apuesta ni conecta con LIVE."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


MERCADOS_BASE = (
    "resultado_1x2",
    "doble_oportunidad",
    "proximo_gol",
    "total_goles",
    "ambos_marcan",
)


@dataclass(frozen=True)
class ContextoPrevio:
    local: str
    visitante: str
    favorito: str | None = None
    expectativa: str = ""
    escenarios_esperados: tuple[str, ...] = ()


@dataclass(frozen=True)
class EstadoPartido:
    minuto: int
    goles_local: int
    goles_visitante: int
    posesion_local: float | None = None
    tiros_local: int | None = None
    tiros_visitante: int | None = None
    tiros_puerta_local: int | None = None
    tiros_puerta_visitante: int | None = None
    ataques_peligrosos_local: int | None = None
    ataques_peligrosos_visitante: int | None = None
    rojas_local: int = 0
    rojas_visitante: int = 0
    mercados_disponibles: tuple[str, ...] = MERCADOS_BASE
    cuotas: dict[str, float] = field(default_factory=dict)


@dataclass
class ResultadoPatron:
    partido: str
    etapa: str
    contexto_inicial: str
    escenarios_esperados: list[str]
    detonantes: list[str]
    contexto_actual: str
    datos_faltantes: list[str]
    escenarios: list[dict[str, Any]]
    puede_pasar_a_calculo: bool
    puede_evaluar_valor: bool
    decision_apuesta: str = "NO_EVALUADA: la decide Reacción"
    probabilidades: str = "NO_CALCULADAS: corresponden a los motores"


def analizar_patron(
    contexto: ContextoPrevio,
    estado: EstadoPartido,
    estado_anterior: EstadoPartido | None = None,
) -> ResultadoPatron:
    """Analiza la foto actual y, si existe, la compara con la foto anterior."""
    partido = f"{contexto.local} vs {contexto.visitante}"
    marcador = f"{estado.goles_local}-{estado.goles_visitante}"
    detonantes: list[str] = []
    faltantes: list[str] = []

    if not 0 <= estado.minuto <= 130:
        faltantes.append("Minuto fuera del rango permitido (0-130)")
    if estado.goles_local < 0 or estado.goles_visitante < 0:
        faltantes.append("Marcador inválido: los goles no pueden ser negativos")
    if not contexto.local.strip() or not contexto.visitante.strip():
        faltantes.append("Nombre de uno o ambos equipos")
    if not contexto.expectativa.strip():
        faltantes.append("Expectativa previa del partido")

    favorito_local = contexto.favorito == contexto.local
    favorito_visitante = contexto.favorito == contexto.visitante
    favorito_perdiendo = (
        favorito_local and estado.goles_local < estado.goles_visitante
    ) or (
        favorito_visitante and estado.goles_visitante < estado.goles_local
    )

    if estado_anterior is not None:
        goles_antes = estado_anterior.goles_local + estado_anterior.goles_visitante
        goles_ahora = estado.goles_local + estado.goles_visitante
        if goles_ahora > goles_antes:
            detonantes.append(
                f"CAMBIO DE MARCADOR: pasó de "
                f"{estado_anterior.goles_local}-{estado_anterior.goles_visitante} "
                f"al {marcador}; revisar qué implica el gol para el contexto."
            )
        if estado.rojas_local > estado_anterior.rojas_local:
            detonantes.append(f"Nueva tarjeta roja para {contexto.local}.")
        if estado.rojas_visitante > estado_anterior.rojas_visitante:
            detonantes.append(f"Nueva tarjeta roja para {contexto.visitante}.")
        if (
            estado.tiros_puerta_local is not None
            and estado_anterior.tiros_puerta_local is not None
            and estado.tiros_puerta_local - estado_anterior.tiros_puerta_local >= 2
        ):
            detonantes.append(f"{contexto.local} sumó al menos dos tiros a puerta desde la última observación.")
        if (
            estado.tiros_puerta_visitante is not None
            and estado_anterior.tiros_puerta_visitante is not None
            and estado.tiros_puerta_visitante - estado_anterior.tiros_puerta_visitante >= 2
        ):
            detonantes.append(f"{contexto.visitante} sumó al menos dos tiros a puerta desde la última observación.")

    if favorito_perdiendo:
        detonantes.append("El favorito está perdiendo: revisar la expectativa, sin invalidarla automáticamente.")

    if estado.rojas_local and (estado_anterior is None or estado.rojas_local == estado_anterior.rojas_local):
        detonantes.append(f"{contexto.local} tiene {estado.rojas_local} tarjeta(s) roja(s).")
    if estado.rojas_visitante and (estado_anterior is None or estado.rojas_visitante == estado_anterior.rojas_visitante):
        detonantes.append(f"{contexto.visitante} tiene {estado.rojas_visitante} tarjeta(s) roja(s).")

    if estado.tiros_puerta_local is None or estado.tiros_puerta_visitante is None:
        faltantes.append("Tiros a puerta de ambos equipos")
    elif abs(estado.tiros_puerta_local - estado.tiros_puerta_visitante) >= 3:
        dominante = contexto.local if estado.tiros_puerta_local > estado.tiros_puerta_visitante else contexto.visitante
        detonantes.append(f"Diferencia relevante de tiros a puerta a favor de {dominante}.")

    if estado.tiros_local is None or estado.tiros_visitante is None:
        faltantes.append("Tiros totales de ambos equipos")
    elif abs(estado.tiros_local - estado.tiros_visitante) >= 6:
        dominante = contexto.local if estado.tiros_local > estado.tiros_visitante else contexto.visitante
        detonantes.append(f"Volumen de tiros claramente desigual a favor de {dominante}.")

    if estado.posesion_local is None:
        faltantes.append("Posesión")
    if estado.ataques_peligrosos_local is None or estado.ataques_peligrosos_visitante is None:
        faltantes.append("Ataques peligrosos de ambos equipos")
    if not estado.mercados_disponibles:
        faltantes.append("Mercados disponibles")

    if favorito_perdiendo and estado.minuto <= 30:
        actual = (
            f"El favorito va por detrás {marcador} al minuto {estado.minuto}. "
            "Es una contradicción con la expectativa inicial que requiere revisión; "
            "no demuestra por sí sola que el favorito no pueda recuperarse."
        )
    elif detonantes:
        actual = (
            f"Marcador {marcador}, minuto {estado.minuto}. Hay cambios o señales "
            "que deben contrastarse con la expectativa y con la evolución reciente."
        )
    else:
        actual = (
            f"Marcador {marcador}, minuto {estado.minuto}. Con los datos disponibles "
            "no aparece una contradicción fuerte; esto no prueba que el partido esté controlado."
        )

    escenarios = []
    for mercado in estado.mercados_disponibles:
        cuota = estado.cuotas.get(mercado)
        escenarios.append({
            "mercado": mercado,
            "cuota_disponible": cuota,
            "probabilidad": None,
            "estado": "PENDIENTE_DE_CALCULO_POR_MOTOR" if cuota is not None else "SIN_CUOTA_DISPONIBLE",
        })

    datos_minimos = (
        estado.tiros_puerta_local is not None
        and estado.tiros_puerta_visitante is not None
        and 0 <= estado.minuto <= 130
        and estado.goles_local >= 0
        and estado.goles_visitante >= 0
        and bool(estado.mercados_disponibles)
        and bool(contexto.expectativa.strip())
    )
    puede_calcular = datos_minimos
    puede_valorar = puede_calcular and any(
        isinstance(estado.cuotas.get(mercado), (int, float))
        and estado.cuotas[mercado] > 1
        for mercado in estado.mercados_disponibles
    )
    if not puede_calcular:
        faltantes.append("Requisitos mínimos para cálculo: minuto/marcador válidos, tiros a puerta de ambos equipos y mercados")
    if puede_calcular and not puede_valorar:
        faltantes.append("Cuotas válidas para evaluar valor de mercado")

    return ResultadoPatron(
        partido=partido,
        etapa="ESCENARIOS_GENERADOS" if puede_calcular else "DATOS_INSUFICIENTES",
        contexto_inicial=contexto.expectativa or "Expectativa previa no especificada.",
        escenarios_esperados=list(contexto.escenarios_esperados),
        detonantes=list(dict.fromkeys(detonantes)),
        contexto_actual=actual,
        datos_faltantes=sorted(set(faltantes)),
        escenarios=escenarios,
        puede_pasar_a_calculo=puede_calcular,
        puede_evaluar_valor=puede_valorar,
    )


def resultado_a_dict(resultado: ResultadoPatron) -> dict[str, Any]:
    return asdict(resultado)
