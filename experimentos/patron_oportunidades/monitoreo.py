"""Punto 2: Monitoreo. Detecta goles nuevos y activa Acción.
Prototipo aislado: datos explícitos, sin APIs, motores ni apuestas.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from modelo_patron import ContextoPrevio, EstadoPartido


@dataclass(frozen=True)
class ResultadoMonitoreo:
    partido: str
    minuto: int
    marcador_anterior: str
    marcador_actual: str
    detonante_detectado: bool
    equipo_que_marco: str | None
    favorito: str | None
    favorito_va_perdiendo: bool
    estado_contexto: str
    activar_accion: bool
    motivo: str


def monitorear_gol(
    contexto: ContextoPrevio,
    anterior: EstadoPartido,
    actual: EstadoPartido,
) -> ResultadoMonitoreo:
    """Todo gol nuevo activa Acción; Monitoreo no decide si el contexto se cumple."""
    marcador_anterior = f"{anterior.goles_local}-{anterior.goles_visitante}"
    marcador_actual = f"{actual.goles_local}-{actual.goles_visitante}"
    partido = f"{contexto.local} vs {contexto.visitante}"
    favorito = contexto.favorito if contexto.favorito in (contexto.local, contexto.visitante) else None

    def resultado(detonante, equipo, perdiendo, estado, activar, motivo):
        return ResultadoMonitoreo(
            partido, actual.minuto, marcador_anterior, marcador_actual,
            detonante, equipo, favorito, perdiendo, estado, activar, motivo,
        )

    if actual.minuto <= anterior.minuto:
        return resultado(False, None, False, "DATOS_TEMPORALES_INVALIDOS", False,
                         "El minuto actual debe ser posterior al anterior; no se activa Acción.")
    delta_local = actual.goles_local - anterior.goles_local
    delta_visitante = actual.goles_visitante - anterior.goles_visitante
    if delta_local < 0 or delta_visitante < 0:
        return resultado(False, None, False, "MARCADOR_INVALIDO", False,
                         "El marcador retrocede; revisar los datos antes de continuar.")

    total_nuevos = delta_local + delta_visitante
    if total_nuevos == 0:
        return resultado(False, None, False, "SIN_GOL_NUEVO", False,
                         "No hay gol nuevo entre observaciones; Monitoreo sigue esperando.")
    if total_nuevos != 1:
        return resultado(False, None, False, "REVISAR_EVENTOS", False,
                         "Cambió más de un gol entre observaciones; revisar eventos antes de activar Acción.")

    equipo_que_marco = contexto.local if delta_local == 1 else contexto.visitante
    perdiendo = bool(
        favorito == contexto.local and actual.goles_local < actual.goles_visitante
        or favorito == contexto.visitante and actual.goles_visitante < actual.goles_local
    )
    if favorito is None:
        estado = "GOL_DETECTADO_SIN_FAVORITO_CLARO"
        motivo = "Gol nuevo detectado. Se activa Acción para analizar el partido; el contexto no definió favorito."
    elif perdiendo:
        estado = "GOL_DETECTADO_FAVORITO_PERDIENDO"
        motivo = (
            f"Gol de {equipo_que_marco}. {favorito} va perdiendo; se activa Acción para revisar "
            "estadísticas y minuto. Esto no demuestra por sí solo que el contexto haya fallado."
        )
    elif actual.goles_local == actual.goles_visitante:
        estado = "GOL_DETECTADO_PARTIDO_EMPATADO"
        motivo = (
            f"Gol de {equipo_que_marco} y el marcador queda empatado. Se activa Acción para evaluar "
            "el minuto y si el contexto previo todavía puede cumplirse."
        )
    else:
        estado = "GOL_DETECTADO_FAVORITO_NO_PERDIENDO"
        motivo = (
            f"Gol de {equipo_que_marco}. Se activa Acción para actualizar la lectura del contexto "
            "y del tiempo restante, aunque el favorito no vaya perdiendo."
        )

    # La regla central: un único gol nuevo siempre pasa a Acción.
    return resultado(True, equipo_que_marco, perdiendo, estado, True, motivo)


def resultado_a_dict(resultado: ResultadoMonitoreo) -> dict:
    return asdict(resultado)
