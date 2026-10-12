"""Cinco casos ficticios para evaluar el detonante de gol en Monitoreo."""
from modelo_patron import ContextoPrevio, EstadoPartido
from monitoreo import monitorear_gol


CONTEXTO = ContextoPrevio(
    local="España",
    visitante="Croacia",
    favorito="España",
    expectativa="España es favorita en este ejemplo sintético.",
)


def e(minuto, local, visitante):
    return EstadoPartido(minuto=minuto, goles_local=local, goles_visitante=visitante)


CASOS = (
    ("1. Croacia marca: España queda 0-1 al 11'", e(10, 0, 0), e(11, 0, 1)),
    ("2. Croacia marca: España queda 1-2 al 61'", e(60, 1, 1), e(61, 1, 2)),
    ("3. Croacia marca: España queda 0-2 al 31'", e(30, 0, 1), e(31, 0, 2)),
    ("4. España empata 1-1 al 20'", e(19, 0, 1), e(20, 1, 1)),
    ("5. España empata 1-1 al 85'", e(84, 0, 1), e(85, 1, 1)),
)


def ejecutar():
    print("MONITOREO — DETONANTE: CUALQUIER GOL NUEVO")
    print("Todos los equipos, minutos y marcadores son ficticios. Sin datos reales ni motores.")
    print("Regla: un gol nuevo activa Acción; Acción evaluará el contexto, estadísticas y minuto.\n")
    resultados = []
    for nombre, anterior, actual in CASOS:
        r = monitorear_gol(CONTEXTO, anterior, actual)
        accion = "SÍ — enviar a Acción" if r.activar_accion else "NO — seguir monitoreando"
        print("-" * 68)
        print(nombre)
        print(f"Marcador {r.marcador_anterior} → {r.marcador_actual} | minuto {r.minuto}")
        print(f"Gol nuevo: {'sí' if r.detonante_detectado else 'no'}")
        print(f"Marcó: {r.equipo_que_marco or 'no determinado'}")
        print(f"Estado: {r.estado_contexto}")
        print(f"¿Activar Acción?: {accion}")
        print(f"Motivo: {r.motivo}\n")
        resultados.append(r)
    return resultados


if __name__ == "__main__":
    ejecutar()
