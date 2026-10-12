"""Pruebas de Monitoreo con marcadores totalmente ficticios."""
import unittest

from modelo_patron import ContextoPrevio, EstadoPartido
from monitoreo import monitorear_gol


CONTEXTO = ContextoPrevio(
    local="España",
    visitante="Croacia",
    favorito="España",
    expectativa="España es el favorito en este ejemplo ficticio.",
)


def estado(minuto, local, visitante):
    return EstadoPartido(minuto=minuto, goles_local=local, goles_visitante=visitante)


class PruebasMonitoreo(unittest.TestCase):
    def test_cualquier_gol_nuevo_activa_accion(self):
        casos = [
            (estado(10, 0, 0), estado(11, 0, 1), "GOL_DETECTADO_FAVORITO_PERDIENDO"),
            (estado(20, 0, 1), estado(21, 1, 1), "GOL_DETECTADO_PARTIDO_EMPATADO"),
            (estado(30, 0, 0), estado(31, 1, 0), "GOL_DETECTADO_FAVORITO_NO_PERDIENDO"),
            (estado(40, 1, 1), estado(41, 1, 2), "GOL_DETECTADO_FAVORITO_PERDIENDO"),
        ]
        for anterior, actual, estado_esperado in casos:
            with self.subTest(marcador=f"{actual.goles_local}-{actual.goles_visitante}"):
                r = monitorear_gol(CONTEXTO, anterior, actual)
                self.assertTrue(r.detonante_detectado)
                self.assertTrue(r.activar_accion)
                self.assertEqual(r.estado_contexto, estado_esperado)

    def test_empate_activa_accion_para_evaluar_minuto(self):
        temprano = monitorear_gol(CONTEXTO, estado(19, 0, 1), estado(20, 1, 1))
        tardio = monitorear_gol(CONTEXTO, estado(84, 0, 1), estado(85, 1, 1))
        self.assertTrue(temprano.activar_accion)
        self.assertTrue(tardio.activar_accion)
        self.assertIn("minuto", temprano.motivo)
        self.assertIn("minuto", tardio.motivo)

    def test_marcador_sin_cambio_no_es_detonante(self):
        r = monitorear_gol(CONTEXTO, estado(10, 0, 0), estado(15, 0, 0))
        self.assertFalse(r.detonante_detectado)
        self.assertFalse(r.activar_accion)
        self.assertEqual(r.estado_contexto, "SIN_GOL_NUEVO")

    def test_dos_goles_entre_observaciones_requieren_revision(self):
        r = monitorear_gol(CONTEXTO, estado(10, 0, 0), estado(15, 0, 2))
        self.assertFalse(r.detonante_detectado)
        self.assertFalse(r.activar_accion)
        self.assertEqual(r.estado_contexto, "REVISAR_EVENTOS")

    def test_no_permite_minuto_no_posterior(self):
        r = monitorear_gol(CONTEXTO, estado(20, 0, 0), estado(20, 0, 1))
        self.assertEqual(r.estado_contexto, "DATOS_TEMPORALES_INVALIDOS")
        self.assertFalse(r.activar_accion)

    def test_gol_sin_favorito_claro_tambien_activa_accion(self):
        contexto = ContextoPrevio(local="España", visitante="Croacia", favorito=None)
        r = monitorear_gol(contexto, estado(10, 0, 0), estado(11, 0, 1))
        self.assertTrue(r.detonante_detectado)
        self.assertTrue(r.activar_accion)


if __name__ == "__main__":
    unittest.main()
