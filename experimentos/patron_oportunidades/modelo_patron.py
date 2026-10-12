"""Laboratorio aislado del Patrón de Oportunidades; no conecta con LIVE."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

MERCADOS_BASE = ("resultado_1x2", "doble_oportunidad", "proximo_gol", "total_goles", "ambos_marcan")

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
    expectativas_vigentes: list[str]
    expectativas_cuestionadas: list[str]
    expectativas_sin_evidencia_suficiente: list[str]
    comparacion_temporal: list[dict[str, Any]]
    interpretacion_conjunta: str
    detonantes: list[str]
    escenarios_a_reevaluar: list[dict[str, str]]
    contexto_actual: str
    datos_faltantes: list[str]
    escenarios: list[dict[str, Any]]
    puede_pasar_a_calculo: bool
    puede_evaluar_valor: bool
    motivo_bloqueo_valor: str
    decision_apuesta: str = "NO_EVALUADA: la decide Reacción"
    probabilidades: str = "NO_CALCULADAS: corresponden a los motores"

def _comparar(nombre, actual, anterior, unidad=""):
    if actual is None or anterior is None:
        return {"indicador": nombre, "anterior": anterior, "actual": actual, "diferencia": None,
                "tendencia": "SIN_DATOS_COMPARABLES", "descripcion": "Falta el dato actual o anterior."}
    delta = actual - anterior
    tendencia = "AUMENTO" if delta > 0 else "DISMINUCION" if delta < 0 else "ESTABLE"
    descripcion = f"Aumentó {delta:g}{unidad}." if delta > 0 else f"Disminuyó {abs(delta):g}{unidad}." if delta < 0 else "Se mantuvo estable."
    return {"indicador": nombre, "anterior": anterior, "actual": actual, "diferencia": delta,
            "tendencia": tendencia, "descripcion": descripcion}

def analizar_patron(contexto: ContextoPrevio, estado: EstadoPartido,
                    estado_anterior: EstadoPartido | None = None,
                    historial: Sequence[EstadoPartido] | None = None,
                    probabilidades_motor: dict[str, float] | None = None) -> ResultadoPatron:
    """Compara snapshots, contrasta expectativas y prepara escenarios sin decidir apuestas."""
    partido = f"{contexto.local} vs {contexto.visitante}"
    marcador = f"{estado.goles_local}-{estado.goles_visitante}"
    faltantes, detonantes, comparacion, reevaluar = [], [], [], []
    if not 0 <= estado.minuto <= 130: faltantes.append("Minuto fuera del rango permitido (0-130)")
    if estado.goles_local < 0 or estado.goles_visitante < 0: faltantes.append("Marcador inválido")
    if not contexto.local.strip() or not contexto.visitante.strip(): faltantes.append("Nombre de uno o ambos equipos")
    if not contexto.expectativa.strip(): faltantes.append("Expectativa previa del partido")

    favorito = contexto.favorito if contexto.favorito in (contexto.local, contexto.visitante) else None
    fav_local = favorito == contexto.local
    favorito_perdiendo = (fav_local and estado.goles_local < estado.goles_visitante) or (
        favorito == contexto.visitante and estado.goles_visitante < estado.goles_local)
    snapshots = list(historial or [])
    if estado_anterior is not None and (not snapshots or snapshots[-1] != estado_anterior):
        snapshots.append(estado_anterior)
    anterior = snapshots[-1] if snapshots else None
    if anterior is not None:
        if estado.minuto <= anterior.minuto:
            faltantes.append("Orden temporal inválido: el snapshot actual debe ser posterior al anterior")
        if (estado.goles_local, estado.goles_visitante) != (anterior.goles_local, anterior.goles_visitante):
            detonantes.append(f"CAMBIO DE MARCADOR: {anterior.goles_local}-{anterior.goles_visitante} → {marcador}; revisar sin asumir cambio de dominio.")
            reevaluar += [
                {"mercado": "resultado_1x2", "motivo": "El marcador cambió; reevaluar victoria, empate y derrota."},
                {"mercado": "total_goles", "motivo": "El gol modifica el total y el tiempo restante."}]
        campos = [
            ("Posesión local", "posesion_local", " puntos porcentuales"),
            (f"Tiros de {contexto.local}", "tiros_local", ""),
            (f"Tiros de {contexto.visitante}", "tiros_visitante", ""),
            (f"Tiros a puerta de {contexto.local}", "tiros_puerta_local", ""),
            (f"Tiros a puerta de {contexto.visitante}", "tiros_puerta_visitante", ""),
            (f"Ataques peligrosos de {contexto.local}", "ataques_peligrosos_local", ""),
            (f"Ataques peligrosos de {contexto.visitante}", "ataques_peligrosos_visitante", "")]
        comparacion = [_comparar(nombre, getattr(estado, campo), getattr(anterior, campo), unidad)
                       for nombre, campo, unidad in campos]
        for equipo, campo, campo_prev in (
            (contexto.local, "rojas_local", "rojas_local"),
            (contexto.visitante, "rojas_visitante", "rojas_visitante")):
            if getattr(estado, campo) > getattr(anterior, campo_prev):
                detonantes.append(f"Nueva tarjeta roja para {equipo}.")
                reevaluar.append({"mercado": "resultado_1x2", "motivo": f"La expulsión de {equipo} altera el equilibrio numérico."})
        for equipo, actual, previo in (
            (contexto.local, estado.tiros_puerta_local, anterior.tiros_puerta_local),
            (contexto.visitante, estado.tiros_puerta_visitante, anterior.tiros_puerta_visitante)):
            if actual is not None and previo is not None and actual - previo >= 2:
                detonantes.append(f"{equipo} sumó al menos dos tiros a puerta desde la observación anterior.")
                reevaluar.append({"mercado": "proximo_gol", "motivo": f"Aumentaron los tiros a puerta recientes de {equipo}; comprobar continuidad y calidad."})
    if favorito_perdiendo:
        detonantes.append("El favorito está perdiendo: revisar la expectativa, sin invalidarla automáticamente.")
        reevaluar.append({"mercado": "resultado_1x2", "motivo": "El favorito va por detrás; reevaluar victoria y empate."})
    if estado.rojas_local and (anterior is None or estado.rojas_local == anterior.rojas_local):
        detonantes.append(f"{contexto.local} tiene {estado.rojas_local} tarjeta(s) roja(s).")
    if estado.rojas_visitante and (anterior is None or estado.rojas_visitante == anterior.rojas_visitante):
        detonantes.append(f"{contexto.visitante} tiene {estado.rojas_visitante} tarjeta(s) roja(s).")

    if estado.tiros_puerta_local is None or estado.tiros_puerta_visitante is None:
        faltantes.append("Tiros a puerta de ambos equipos")
    if estado.tiros_local is None or estado.tiros_visitante is None: faltantes.append("Tiros totales de ambos equipos")
    if estado.posesion_local is None: faltantes.append("Posesión local")
    if estado.ataques_peligrosos_local is None or estado.ataques_peligrosos_visitante is None:
        faltantes.append("Ataques peligrosos de ambos equipos")
    if not estado.mercados_disponibles: faltantes.append("Mercados realmente disponibles")

    fav_sot = estado.tiros_puerta_local if fav_local else estado.tiros_puerta_visitante
    rival_sot = estado.tiros_puerta_visitante if fav_local else estado.tiros_puerta_local
    dom_fav = fav_sot is not None and rival_sot is not None and fav_sot >= rival_sot + 2
    dom_rival = fav_sot is not None and rival_sot is not None and rival_sot >= fav_sot + 2
    tendencia_rival = False
    if len(snapshots) >= 2 and favorito:
        s1, s2 = snapshots[-2], snapshots[-1]
        f1 = s1.tiros_puerta_local if fav_local else s1.tiros_puerta_visitante
        r1 = s1.tiros_puerta_visitante if fav_local else s1.tiros_puerta_local
        f2 = s2.tiros_puerta_local if fav_local else s2.tiros_puerta_visitante
        r2 = s2.tiros_puerta_visitante if fav_local else s2.tiros_puerta_local
        tendencia_rival = all(x is not None for x in (f1, r1, f2, r2)) and (r2 - f2) > (r1 - f1) and r2 > f2
    gol_nuevo = anterior is not None and (estado.goles_local + estado.goles_visitante > anterior.goles_local + anterior.goles_visitante)
    roja_fav = (fav_local and estado.rojas_local > 0) or (favorito == contexto.visitante and estado.rojas_visitante > 0)
    if gol_nuevo and dom_fav and not roja_fav:
        interpretacion = "El gol parece aislado respecto a los indicadores actuales: el favorito mantiene ventaja en tiros a puerta; no declarar perdido su dominio."
    elif dom_rival and (tendencia_rival or roja_fav):
        interpretacion = "Hay señales convergentes de posible cambio de control: el rival aventaja al favorito y la tendencia reciente o una expulsión refuerza la señal."
    elif dom_rival:
        interpretacion = "El rival aventaja al favorito en esta observación, pero aún falta evidencia temporal para llamarlo cambio sostenido."
    elif gol_nuevo:
        interpretacion = "Hubo un gol, pero los indicadores no confirman por sí solos un cambio sostenido de dominio."
    elif dom_fav:
        interpretacion = "Los indicadores actuales favorecen al favorito; se necesitan más observaciones para confirmar continuidad."
    else:
        interpretacion = "Las señales son insuficientes o mixtas para establecer un dominio claro; conservar incertidumbre."

    vigentes, cuestionadas, sin_evidencia = [], [], []
    for exp in contexto.escenarios_esperados:
        low = exp.lower()
        if favorito_perdiendo and (("victoria" in low) or ("remontada" in low) or (favorito and favorito.lower() in low)):
            cuestionadas.append(exp)
        elif dom_rival and (("dominio" in low) or ("peligro" in low) or (favorito and favorito.lower() in low)):
            cuestionadas.append(exp)
        elif dom_fav and favorito and favorito.lower() in low:
            vigentes.append(exp)
        else:
            sin_evidencia.append(exp)
    if not contexto.escenarios_esperados:
        sin_evidencia.append("No se definieron escenarios esperados concretos.")

    reevaluar_unicos, vistos = [], set()
    for item in reevaluar:
        key = (item["mercado"], item["motivo"])
        if key not in vistos:
            vistos.add(key)
            reevaluar_unicos.append(item)
    if not reevaluar_unicos:
        reevaluar_unicos.append({"mercado": "ninguno_por_ahora", "motivo": "No hay detonantes suficientes; continuar observando."})

    escenarios = []
    for mercado in estado.mercados_disponibles:
        cuota = estado.cuotas.get(mercado)
        p = (probabilidades_motor or {}).get(mercado)
        p_ok = isinstance(p, (int, float)) and 0 <= p <= 1
        cuota_ok = isinstance(cuota, (int, float)) and cuota > 1
        valor = p * cuota - 1 if p_ok and cuota_ok else None
        estado_m = ("SIN_CUOTA_VALIDA" if not cuota_ok else
                    "CUOTA_DISPONIBLE_FALTA_PROBABILIDAD_FIABLE" if not p_ok else
                    "VALOR_CALCULABLE_NO_ES_RECOMENDACION")
        escenarios.append({"mercado": mercado, "cuota_disponible": cuota,
                           "probabilidad_motor": p if p_ok else None,
                           "valor_esperado_estimado": round(valor, 4) if valor is not None else None,
                           "estado": estado_m})
    minimos = (0 <= estado.minuto <= 130 and estado.goles_local >= 0 and estado.goles_visitante >= 0
               and estado.tiros_puerta_local is not None and estado.tiros_puerta_visitante is not None
               and bool(estado.mercados_disponibles) and bool(contexto.expectativa.strip())
               and (anterior is None or estado.minuto > anterior.minuto))
    puede_valorar = minimos and any(
        isinstance(estado.cuotas.get(m), (int, float)) and estado.cuotas[m] > 1
        and isinstance((probabilidades_motor or {}).get(m), (int, float))
        and 0 <= (probabilidades_motor or {})[m] <= 1 for m in estado.mercados_disponibles)
    if not minimos:
        faltantes.append("Requisitos mínimos para cálculo: minuto/marcador válidos, tiros a puerta, expectativa, mercados y orden temporal")
    if not puede_valorar:
        faltantes.append("Falta probabilidad fiable de motor y cuota válida para el mismo mercado")
    return ResultadoPatron(
        partido=partido, etapa="ESCENARIOS_GENERADOS" if minimos else "DATOS_INSUFICIENTES",
        contexto_inicial=contexto.expectativa or "Expectativa previa no especificada.",
        escenarios_esperados=list(contexto.escenarios_esperados),
        expectativas_vigentes=vigentes, expectativas_cuestionadas=cuestionadas,
        expectativas_sin_evidencia_suficiente=sin_evidencia,
        comparacion_temporal=comparacion, interpretacion_conjunta=interpretacion,
        detonantes=list(dict.fromkeys(detonantes)), escenarios_a_reevaluar=reevaluar_unicos,
        contexto_actual=f"Marcador {marcador}, minuto {estado.minuto}. {interpretacion}",
        datos_faltantes=sorted(set(faltantes)), escenarios=escenarios,
        puede_pasar_a_calculo=minimos, puede_evaluar_valor=puede_valorar,
        motivo_bloqueo_valor=("Falta una probabilidad válida del motor para el mismo mercado y una cuota válida."
                              if not puede_valorar else
                              "Valor esperado calculable; Reacción aún debe aplicar sus reglas, sin apuesta automática.")
    )

def resultado_a_dict(resultado: ResultadoPatron) -> dict[str, Any]:
    return asdict(resultado)
