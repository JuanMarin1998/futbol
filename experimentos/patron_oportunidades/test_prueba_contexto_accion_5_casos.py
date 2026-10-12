"""Reglas mínimas para la prueba Contexto → Acción con cinco casos ficticios."""
import unittest

from prueba_contexto_accion_5_casos import CASOS, clasificar, CONTEXTO
from modelo_patron import analizar_patron


class PruebaContextoAccionCincoCasos(unittest.TestCase):
    def test_hay_tres_derrotas_un_empate_y_una_victoria(self):
        marcadores = [caso["marcador"] for caso in CASOS]
        derrotas = sum(local < visitante for local, visitante in marcadores)
        empates = sum(local == visitante for local, visitante in marcadores)
        victorias = sum(local > visitante for local, visitante in marcadores)
        self.assertEqual((derrotas, empates, victorias), (3, 1, 1))

    def test_accion_no_decide_solo_por_el_marcador(self):
        lecturas = []
        for caso in CASOS:
            resultado = analizar_patron(
                CONTEXTO,
                caso["actual"],
                estado_anterior=caso["anterior"],
                historial=[caso["anterior"]],
            )
            lecturas.append(clasificar(resultado))
        self.assertEqual(lecturas, [caso["lectura_esperada"] for caso in CASOS])


if __name__ == "__main__":
    unittest.main()
