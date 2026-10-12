import unittest
from contexto_prepartido import PartidoReciente, PerfilEquipo, construir_contexto


def forma(nombre, resultados):
    return PerfilEquipo(nombre, tuple(PartidoReciente(gf, gc, condicion) for gf, gc, condicion in resultados))


class ContextoPrepartidoTests(unittest.TestCase):
    def test_detecta_mejor_forma_sin_presentarla_como_certeza(self):
        local = forma("España", [(2, 0, "local"), (3, 1, "visitante"), (1, 0, "local"), (2, 1, "visitante"), (2, 0, "local")])
        visitante = forma("Croacia", [(0, 1, "visitante"), (1, 1, "local"), (0, 2, "visitante"), (1, 0, "local"), (0, 0, "visitante")])
        r = construir_contexto(local, visitante)
        self.assertEqual(r.estado, "CONTEXTO_PRELIMINAR")
        self.assertEqual(r.favorito_estimado, "España")
        self.assertTrue(any("puntos por partido" in x for x in r.evidencias))
        self.assertTrue(any("no consulta fuentes externas" in x for x in r.limitaciones))

    def test_forma_parecida_no_fuerza_favorito(self):
        local = forma("Equipo A", [(1, 0, "local"), (0, 1, "visitante"), (1, 1, "local")])
        visitante = forma("Equipo B", [(0, 1, "visitante"), (1, 0, "local"), (1, 1, "visitante")])
        r = construir_contexto(local, visitante)
        self.assertIsNone(r.favorito_estimado)
        self.assertIn("CONTEXTO_PRELIMINAR", r.estado)

    def test_historial_insuficiente_bloquea_contexto(self):
        local = forma("Equipo A", [(1, 0, "local"), (0, 0, "visitante")])
        visitante = forma("Equipo B", [(1, 0, "visitante"), (0, 1, "local"), (2, 0, "visitante")])
        r = construir_contexto(local, visitante)
        self.assertEqual(r.estado, "INCOMPLETO")
        self.assertIsNone(r.favorito_estimado)
        self.assertTrue(any("al menos 3" in x for x in r.limitaciones))

    def test_datos_invalidos_no_generan_favorito(self):
        local = forma("Equipo A", [(-1, 0, "local"), (1, 0, "local"), (0, 0, "visitante")])
        visitante = forma("Equipo B", [(1, 0, "visitante"), (1, 1, "local"), (0, 1, "visitante")])
        r = construir_contexto(local, visitante)
        self.assertEqual(r.estado, "INCOMPLETO")
        self.assertIsNone(r.favorito_estimado)

    def test_usa_hasta_los_cinco_resultados_mas_recientes(self):
        local = forma("Equipo A", [(0, 4, "local"), (2, 0, "local"), (2, 0, "visitante"), (2, 0, "local"), (2, 0, "visitante"), (2, 0, "local")])
        visitante = forma("Equipo B", [(0, 1, "visitante"), (0, 1, "local"), (0, 1, "visitante")])
        r = construir_contexto(local, visitante)
        self.assertIn("últimos 5", r.evidencias[0])
        self.assertEqual(r.favorito_estimado, "Equipo A")


if __name__ == "__main__":
    unittest.main()
