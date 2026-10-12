import unittest
from modelo_patron import ContextoPrevio, EstadoPartido, analizar_patron

CTX = ContextoPrevio(local="España", visitante="Croacia", favorito="España",
    expectativa="España es favorita y se espera que genere más peligro.",
    escenarios_esperados=("victoria España", "España genera más peligro", "remontada posible"))

def snap(minuto, gl=0, gv=0, tpl=3, tpv=1, tl=7, tv=4, rl=0, cuota=2.0):
    return EstadoPartido(minuto=minuto, goles_local=gl, goles_visitante=gv, posesion_local=58,
        tiros_local=tl, tiros_visitante=tv, tiros_puerta_local=tpl, tiros_puerta_visitante=tpv,
        ataques_peligrosos_local=15, ataques_peligrosos_visitante=12, rojas_local=rl,
        mercados_disponibles=("resultado_1x2",), cuotas={"resultado_1x2": cuota})

class PatronOportunidadesTests(unittest.TestCase):
    def test_gol_aislado_no_significa_perdida_de_dominio(self):
        r = analizar_patron(CTX, snap(15, gv=1, tpl=5, tpv=1), snap(10, tpl=2, tpv=0))
        self.assertIn("gol parece aislado", r.interpretacion_conjunta.lower())
        self.assertFalse(r.puede_evaluar_valor)

    def test_cuota_sola_no_habilita_valor(self):
        r = analizar_patron(CTX, snap(20))
        self.assertFalse(r.puede_evaluar_valor)
        self.assertIsNone(r.escenarios[0]["valor_esperado_estimado"])

    def test_probabilidad_motor_habilita_calculo_preliminar(self):
        r = analizar_patron(CTX, snap(20), probabilidades_motor={"resultado_1x2": 0.55})
        self.assertTrue(r.puede_evaluar_valor)
        self.assertAlmostEqual(r.escenarios[0]["valor_esperado_estimado"], 0.1)

    def test_perdida_dominio_sin_gol_y_con_tendencia(self):
        s10, s18, s25 = snap(10, tpl=3, tpv=0), snap(18, tpl=3, tpv=2, tl=6, tv=7), snap(25, tpl=3, tpv=5, tl=7, tv=12)
        r = analizar_patron(CTX, s25, s18, historial=[s10, s18])
        self.assertIn("cambio de control", r.interpretacion_conjunta.lower())

    def test_indicadores_contradictorios_no_afirma_dominio_claro(self):
        anterior = snap(20, gv=1, tpl=4, tpv=1)
        actual = snap(30, gv=1, tpl=4, tpv=3, tl=5, tv=9, rl=1)
        r = analizar_patron(CTX, actual, anterior)
        self.assertIn("insuficientes o mixtas", r.interpretacion_conjunta.lower())

    def test_gol_no_cuestiona_automaticamente_el_dominio(self):
        escenarios = ("victoria España", "empate", "remontada posible", "España genera más peligro")
        contexto = ContextoPrevio(local="España", visitante="Croacia", favorito="España",
            expectativa="España es favorita.", escenarios_esperados=escenarios)
        r = analizar_patron(contexto, snap(15, gv=1, tpl=5, tpv=1), snap(10, tpl=2, tpv=0))
        self.assertIn("España genera más peligro", r.expectativas_vigentes)
        self.assertNotIn("remontada posible", r.expectativas_cuestionadas)

    def test_marcador_que_retrocede_bloquea_calculo(self):
        r = analizar_patron(CTX, snap(40, gl=1, gv=0), snap(30, gl=0, gv=1))
        self.assertFalse(r.puede_pasar_a_calculo)
        self.assertTrue(r.anomalias_datos)
        self.assertTrue(any("Marcador no monotónico" in x for x in r.datos_faltantes))

    def test_faltan_datos_bloquea_calculo(self):
        s = EstadoPartido(minuto=20, goles_local=0, goles_visitante=0,
            tiros_puerta_local=None, tiros_puerta_visitante=None, mercados_disponibles=("resultado_1x2",))
        self.assertFalse(analizar_patron(CTX, s).puede_pasar_a_calculo)

if __name__ == "__main__":
    unittest.main()
