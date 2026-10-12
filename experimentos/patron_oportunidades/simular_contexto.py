"""Informe legible de casos artificiales para el contexto previo."""
from contexto_prepartido import PartidoReciente, PerfilEquipo, construir_contexto


def perfil(nombre, resultados):
    return PerfilEquipo(nombre, tuple(PartidoReciente(gf, gc, condicion) for gf, gc, condicion in resultados))


def mostrar(titulo, local, visitante):
    r = construir_contexto(local, visitante)
    print("\\n" + "=" * 72 + "\\n" + titulo)
    print(f"Partido: {r.partido}")
    print(f"Estado: {r.estado}")
    print(f"Favorito estimado: {r.favorito_estimado or 'NINGUNO: la muestra no justifica elegir uno'}")
    if r.evidencias:
        print("Evidencias:")
        for item in r.evidencias:
            print(f"  - {item}")
    print("Expectativas iniciales:")
    for item in r.expectativas:
        print(f"  - {item}")
    print("Qué observar durante el partido:")
    for item in r.señales_a_observar:
        print(f"  - {item}")
    print("Limitaciones:")
    for item in r.limitaciones:
        print(f"  - {item}")


def main():
    mostrar(
        "CASO 1. Un equipo llega con mejor forma reciente",
        perfil("España", [(2, 0, "local"), (3, 1, "visitante"), (1, 0, "local"), (2, 1, "visitante"), (2, 0, "local")]),
        perfil("Croacia", [(0, 1, "visitante"), (1, 1, "local"), (0, 2, "visitante"), (1, 0, "local"), (0, 0, "visitante")]),
    )
    mostrar(
        "CASO 2. La forma reciente no separa claramente a los equipos",
        perfil("Equipo A", [(1, 0, "local"), (0, 1, "visitante"), (1, 1, "local")]),
        perfil("Equipo B", [(0, 1, "visitante"), (1, 0, "local"), (1, 1, "visitante")]),
    )
    mostrar(
        "CASO 3. Historial insuficiente",
        perfil("Equipo A", [(1, 0, "local"), (0, 0, "visitante")]),
        perfil("Equipo B", [(1, 0, "visitante"), (0, 1, "local"), (2, 0, "visitante")]),
    )


if __name__ == "__main__":
    main()
