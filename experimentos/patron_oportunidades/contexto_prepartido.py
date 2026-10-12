"""Construcción aislada y explicable del contexto previo; no consulta APIs ni motores."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class PartidoReciente:
    """Resultado de un partido visto desde la perspectiva de un solo equipo."""
    goles_favor: int
    goles_contra: int
    condicion: str  # "local" o "visitante"

    @property
    def puntos(self) -> int:
        if self.goles_favor > self.goles_contra:
            return 3
        if self.goles_favor == self.goles_contra:
            return 1
        return 0


@dataclass(frozen=True)
class PerfilEquipo:
    nombre: str
    ultimos_partidos: tuple[PartidoReciente, ...]


@dataclass(frozen=True)
class InformeContexto:
    partido: str
    estado: str
    favorito_estimado: str | None
    evidencias: tuple[str, ...]
    expectativas: tuple[str, ...]
    señales_a_observar: tuple[str, ...]
    limitaciones: tuple[str, ...]


def _resumir(perfil: PerfilEquipo) -> dict:
    partidos = perfil.ultimos_partidos[-5:]
    puntos = sum(p.puntos for p in partidos)
    gf = sum(p.goles_favor for p in partidos)
    gc = sum(p.goles_contra for p in partidos)
    local = [p for p in partidos if p.condicion == "local"]
    visitante = [p for p in partidos if p.condicion == "visitante"]
    return {
        "n": len(partidos), "puntos": puntos, "ppp": puntos / len(partidos),
        "gf": gf, "gc": gc, "goles_favor_prom": gf / len(partidos),
        "goles_contra_prom": gc / len(partidos), "dif_goles": (gf - gc) / len(partidos),
        "local_n": len(local), "local_puntos": sum(p.puntos for p in local),
        "visitante_n": len(visitante), "visitante_puntos": sum(p.puntos for p in visitante),
        "indice": puntos / len(partidos) + 0.35 * ((gf - gc) / len(partidos)),
    }


def construir_contexto(local: PerfilEquipo, visitante: PerfilEquipo) -> InformeContexto:
    """Resume últimos resultados sin convertir la forma reciente en certeza ni apuesta."""
    limitaciones = []
    if not local.nombre.strip() or not visitante.nombre.strip():
        limitaciones.append("Falta el nombre de uno o ambos equipos.")
    if local.nombre.strip().casefold() == visitante.nombre.strip().casefold():
        limitaciones.append("El equipo local y el visitante no pueden ser el mismo.")
    for perfil in (local, visitante):
        if len(perfil.ultimos_partidos) < 3:
            limitaciones.append(f"{perfil.nombre}: se necesitan al menos 3 resultados recientes; hay {len(perfil.ultimos_partidos)}.")
        if any(p.goles_favor < 0 or p.goles_contra < 0 for p in perfil.ultimos_partidos):
            limitaciones.append(f"{perfil.nombre}: hay goles negativos en el historial.")
        if any(p.condicion not in ("local", "visitante") for p in perfil.ultimos_partidos):
            limitaciones.append(f"{perfil.nombre}: condición de partido inválida; usar 'local' o 'visitante'.")
    if limitaciones:
        return InformeContexto(
            partido=f"{local.nombre} vs {visitante.nombre}", estado="INCOMPLETO",
            favorito_estimado=None, evidencias=(), expectativas=(),
            señales_a_observar=("No fijar una expectativa fuerte hasta completar o corregir los datos.",),
            limitaciones=tuple(dict.fromkeys(limitaciones)))

    l, v = _resumir(local), _resumir(visitante)
    evidencias = (
        f"{local.nombre}: {l['puntos']}/{3*l['n']} puntos en sus últimos {l['n']} partidos; promedio {l['ppp']:.2f} puntos por partido.",
        f"{local.nombre}: {l['goles_favor_prom']:.2f} goles a favor y {l['goles_contra_prom']:.2f} en contra por partido.",
        f"{visitante.nombre}: {v['puntos']}/{3*v['n']} puntos en sus últimos {v['n']} partidos; promedio {v['ppp']:.2f} puntos por partido.",
        f"{visitante.nombre}: {v['goles_favor_prom']:.2f} goles a favor y {v['goles_contra_prom']:.2f} en contra por partido.",
        f"Muestra de local: {local.nombre} tiene {l['local_n']} partidos como local en la muestra; {visitante.nombre} tiene {v['visitante_n']} como visitante.",
    )
    diferencia = l["indice"] - v["indice"]
    if diferencia >= 0.6:
        favorito, mejor = local.nombre, local.nombre
        expectativas = (f"{local.nombre} llega con mejor forma reciente según puntos y diferencia de goles.",
                        f"Comprobar si {local.nombre} logra generar más ocasiones durante el partido.")
    elif diferencia <= -0.6:
        favorito, mejor = visitante.nombre, visitante.nombre
        expectativas = (f"{visitante.nombre} llega con mejor forma reciente según puntos y diferencia de goles.",
                        f"Comprobar si {visitante.nombre} logra generar más ocasiones durante el partido.")
    else:
        favorito, mejor = None, None
        expectativas = ("La forma reciente no establece una ventaja suficientemente clara entre ambos equipos.",
                        "Comparar el peligro generado en el partido antes de favorecer a un equipo.")
    señales = (
        "Tiros a puerta y ocasiones creadas por cada equipo, no solo posesión.",
        "Calidad y disponibilidad de la alineación cuando existan datos confirmados.",
        "Si el rendimiento durante el partido confirma o contradice la forma reciente.",
        "No concluir que una expectativa se cumple usando únicamente el marcador.",
    )
    return InformeContexto(
        partido=f"{local.nombre} vs {visitante.nombre}", estado="CONTEXTO_PRELIMINAR",
        favorito_estimado=favorito, evidencias=evidencias, expectativas=expectativas,
        señales_a_observar=señales,
        limitaciones=("Solo usa los resultados recientes suministrados; no consulta fuentes externas.",
                      "No incluye todavía calidad de rivales, lesiones, alineaciones, descanso, competición ni cuotas.",
                      "El favorito estimado es una referencia explicable, no una probabilidad ni una recomendación de apuesta."))
