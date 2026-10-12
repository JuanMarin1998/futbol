"""Punto 2: Monitoreo. Detecta goles nuevos y decide si activar Acción.
Prototipo aislado: datos de entrada explícitos, sin APIs, motores ni apuestas.
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
    """Un gol nuevo es el único detonante. No decide si el contexto falló."""
    marcador_anterior = f"{anterior.goles_local}-{anterior.goles_visitante}"
    marcador_actual = f"{actual.goles_local}-{actual.goles_visitante}"
    partido = f"{contexto.local} vs {contexto.visitante}"

    if actual.minuto <= anterior.minuto:
        return ResultadoMonitoreo(
            partido, actual.minuto, marcador_anterior, marcador_actual, False,
            None, contexto.favorito, False, "DATOS_TEMPORALES_INVALIDOS", False,
            "El minuto actual debe ser posterior al anterior; no se activa Acción.",
        )

    delta_local = actual.goles_local - anterior.goles_local
    delta_visitante = actual.goles_visitante - anterior.goles_visitante
    if delta_local < 0 or delta_visitante < 0:
        return ResultadoMonitoreo(
            partido, actual.minuto, marcador_anterior, marcador_actual, False,
            None, contexto.favorito, False, "MARCADOR_INVALIDO", False,
            "El marcador retrocede; revisar los datos antes de continuar.",
        )

    total_nuevos = delta_local + delta_visitante
    if total_nuevos == 0:
        return ResultadoMonitoreo(
            partido, actual.minuto, marcador_anterior, marcador_actual, False,
            None, contexto.favorito, False, "SIN_GOL_NUEVO", False,
            "No hay un gol nuevo entre estas dos observaciones. Monitoreo sigue esperando.",
        )
    if total_nuevos != 1:
        return ResultadoMonitoreo(
            partido, actual.minuto, marcador_anterior, marcador_actual, False,
            None, contexto.favorito, False, "REVISAR_EVENTOS", False,
            "El marcador cambió en más de un gol entre observaciones; no se puede identificar con seguridad el evento.",
        )

    equipo_que_marco = contexto.local if delta_local == 1 else contexto.visitante
    favorito = contexto.favorito if contexto.favorito in (contexto.local, contexto.visitante) else None
    favorito_va_perdiendo = bool(
        favorito == contexto.local and actual.goles_local < actual.goles_visitante
        or favorito == contexto.visitante and actual.goles_visitante < actual.goles_local
    )

    if favorito is None:
        estado = "SIN_FAVORITO_CLARO"
        activar = False
        motivo = "Se detectó un gol, pero el contexto no define un favorito; no se activa Acción."
    elif favorito_va_perdiendo:
        estado = "POSIBLE_INCUMPLIMIENTO"
        activar = True
        motivo = (
            f"Gol de {equipo_que_marco}. {favorito} va perdiendo; se activa Acción para revisar "
            "las estadísticas. Esto no demuestra por sí solo que el contexto haya fallado."
        )
    else:
        estado = "SIN_SEÑAL_DE_INCUMPLIMIENTO"
        activar = False
        motivo = (
            f"Gol de {equipo_que_marco}, pero {favorito} no va perdiendo. Se registra el gol "
            "y Monitoreo continúa sin activar Acción."
        )

    return ResultadoMonitoreo(
        partido, actual.minuto, marcador_anterior, marcador_actual, True,
        equipo_que_marco, favorito, favorito_va_perdiendo, estado, activar, motivo,
    )


def resultado_a_dict(resultado: ResultadoMonitoreo) -> dict:
    """Convierte el resultado a un diccionario sencillo para futuras interfaces."""
    return asdict(resultado)
