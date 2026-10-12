"""Modelo aislado del Patrón de Oportunidades (sin apuestas ni conexión con LIVE).

Flujo:
1. Contexto previo: registra la expectativa del partido.
2. Acción: compara el estado observado con la expectativa y marca detonantes.
3. Probabilidades: enumera los escenarios/mercados disponibles.
4. Cálculo: entrega escenarios a los motores; este módulo NO inventa probabilidades.
5. Reacción: queda fuera del alcance de este prototipo; no recomienda ni registra apuestas.
"""
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
    detonantes: list[str]
    contexto_actual: str
    datos_faltantes: list[str]
    escenarios: list[dict[str, Any]]
    puede_pasar_a_calculo: bool
    decision_apuesta: str = "NO_EVALUADA: la decide una capa posterior"
    probabilidades: str = "NO_CALCULADAS: corresponden a los motores"


def analizar_patron(contexto: ContextoPrevio, estado: EstadoPartido) -> ResultadoPatron:
    """Analiza una instantánea y devuelve contexto, detonantes y escenarios."""
    partido = f"{contexto.local} vs {contexto.visitante}"
    marcador = f"{estado.goles_local}-{estado.goles_visitante}"
    detonantes: list[str] = []
    faltantes: list[str] = []

    favorito_local = contexto.favorito == contexto.local
    favorito_visitante = contexto.favorito == contexto.visitante
    favorito_perdiendo = (
        favorito_local and estado.goles_local < estado.goles_visitante
    ) or (
        favorito_visitante and estado.goles_visitante < estado.goles_local
    )

    if favorito_perdiendo:
        detonantes.append(
            "El favorito está perdiendo: revisar la expectativa, sin invalidarla automáticamente."
        )

    if estado.rojas_local:
        detonantes.append(f"{contexto.local} tiene {estado.rojas_local} tarjeta(s) roja(s).")
    if estado.rojas_visitante:
        detonantes.append(
            f"{contexto.visitante} tiene {estado.rojas_visitante} tarjeta(s) roja(s)."
        )

    if estado.tiros_puerta_local is None or estado.tiros_puerta_visitante is None:
        faltantes.append("Tiros a puerta de ambos equipos")
    elif abs(estado.tiros_puerta_local - estado.tiros_puerta_visitante) >= 3:
        dominante = (
            contexto.local
            if estado.tiros_puerta_local > estado.tiros_puerta_visitante
            else contexto.visitante
        )
        detonantes.append(f"Diferencia relevante de tiros a puerta a favor de {dominante}.")

    if estado.tiros_local is None or estado.tiros_visitante is None:
        faltantes.append("Tiros totales de ambos equipos")
    elif abs(estado.tiros_local - estado.tiros_visitante) >= 6:
        dominante = (
            contexto.local if estado.tiros_local > estado.tiros_visitante
            else contexto.visitante
        )
        detonantes.append(f"Volumen de tiros claramente desigual a favor de {dominante}.")

    if estado.posesion_local is None:
        faltantes.append("Posesión")
    if (
        estado.ataques_peligrosos_local is None
        or estado.ataques_peligrosos_visitante is None
    ):
        faltantes.append("Ataques peligrosos de ambos equipos")

    if favorito_perdiendo and estado.minuto <= 30:
        actual = (
            f"El favorito va por detrás {marcador} al minuto {estado.minuto}; "
            "el gol en contra activa revisión, no una apuesta automática."
        )
    elif detonantes:
        actual = (
            f"Marcador {marcador}, minuto {estado.minuto}. "
            "Hay señales que requieren revisar la expectativa inicial."
        )
    else:
        actual = (
            f"Marcador {marcador}, minuto {estado.minuto}. "
            "No se detecta todavía una contradicción fuerte con los datos recibidos."
        )

    escenarios = [
        {
            "mercado": mercado,
            "cuota_disponible": estado.cuotas.get(mercado),
            "probabilidad": None,
            "estado": "PENDIENTE_DE_CALCULO_POR_MOTOR",
        }
        for mercado in estado.mercados_disponibles
    ]

    # El marcador/minuto y al menos un mercado no bastan para estimar:
    # exigimos tiros a puerta comparables de ambos equipos como señal mínima.
    estadistica_minima_disponible = (
        estado.tiros_puerta_local is not None
        and estado.tiros_puerta_visitante is not None
    )
    puede_calcular = (
        0 <= estado.minuto <= 130
        and bool(estado.mercados_disponibles)
        and estadistica_minima_disponible
    )
    if not estadistica_minima_disponible:
        faltantes.append("Datos mínimos para cálculo: tiros a puerta de ambos equipos")

    return ResultadoPatron(
        partido=partido,
        etapa="ESCENARIOS_GENERADOS" if puede_calcular else "DATOS_INSUFICIENTES",
        contexto_inicial=contexto.expectativa or "Expectativa previa no especificada.",
        detonantes=detonantes,
        contexto_actual=actual,
        datos_faltantes=sorted(set(faltantes)),
        escenarios=escenarios,
        puede_pasar_a_calculo=puede_calcular,
    )


def resultado_a_dict(resultado: ResultadoPatron) -> dict[str, Any]:
    """Serialización estable para imprimir, guardar o comparar simulaciones."""
    return asdict(resultado)
