import unittest

from simular_partido_completo import preparar_contexto, snapshot
from modelo_patron import analizar_patron


class FlujoIntegralSinteticoTests(unittest.TestCase):
    def test_contexto_previo_se_conserva_durante_live(self):
        previo, informe = preparar_contexto()
        self.assertEqual(informe.estado, "CONTEXTO_PRELIMINAR")
        self.assertEqual(previo.favorito, "España")
        self.assertIn("forma ficticia", previo.expectativa)

        inicial = snapshot(15, goles_local=0, goles_visitante=0, tiros_local=6,
            tiros_visitante=2, puerta_local=3, puerta_visitante=0, ataques_local=18,
            ataques_visitante=7, posesion_local=61)
        posterior = snapshot(28, goles_local=0, goles_visitante=1, tiros_local=10,
            tiros_visitante=4, puerta_local=5, puerta_visitante=1, ataques_local=29,
            ataques_visitante=12, posesion_local=63)
        r = analizar_patron(previo, posterior, estado_anterior=inicial,
            probabilidades_motor={"resultado_1x2": 0.48, "total_goles": 0.57, "proximo_gol": 0.44})
        self.assertEqual(r.contexto_inicial, previo.expectativa)
        self.assertIn("gol no demuestra por sí solo", r.interpretacion_conjunta.lower())
        self.assertTrue(r.puede_pasar_a_calculo)
        self.assertTrue(r.puede_evaluar_valor)

    def test_reaccion_no_se_convierte_en_apuesta_automatica(self):
        previo, _ = preparar_contexto()
        actual = snapshot(15, goles_local=0, goles_visitante=0, tiros_local=6,
            tiros_visitante=2, puerta_local=3, puerta_visitante=0, ataques_local=18,
            ataques_visitante=7, posesion_local=61)
        r = analizar_patron(previo, actual,
            probabilidades_motor={"resultado_1x2": 0.48, "total_goles": 0.57, "proximo_gol": 0.44})
        self.assertTrue(r.puede_evaluar_valor)
        self.assertIn("Reacción aún debe aplicar sus reglas", r.motivo_bloqueo_valor)

    def test_datos_ficticios_sin_probabilidad_no_calculan_valor(self):
        previo, _ = preparar_contexto()
        actual = snapshot(15, goles_local=0, goles_visitante=0, tiros_local=6,
            tiros_visitante=2, puerta_local=3, puerta_visitante=0, ataques_local=18,
            ataques_visitante=7, posesion_local=61)
        r = analizar_patron(previo, actual)
        self.assertFalse(r.puede_evaluar_valor)
        self.assertTrue(all(x["valor_esperado_estimado"] is None for x in r.escenarios))


if __name__ == "__main__":
    unittest.main()
