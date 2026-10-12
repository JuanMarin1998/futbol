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
    def test_tres_goles_dejan_al_favorito_perdiendo_y_activan_accion(self):
        casos = [
            (estado(10, 0, 0), estado(11, 0, 1)),
            (estado(20, 1, 1), estado(21, 1, 2)),
            (estado(30, 0, 1), estado(31, 0, 2)),
        ]
        for anterior, actual in casos:
            with self.subTest(marcador=f"{actual.goles_local}-{actual.goles_visitante}"):
                r = monitorear_gol(CONTEXTO, anterior, actual)
                self.assertTrue(r.detonante_detectado)
                self.assertTrue(r.favorito_va_perdiendo)
                self.assertTrue(r.activar_accion)
                self.assertEqual(r.estado_contexto, "POSIBLE_INCUMPLIMIENTO")

    def test_gol_que_deja_empate_no_activa_accion(self):
        r = monitorear_gol(CONTEXTO, estado(40, 0, 1), estado(41, 1, 1))
        self.assertTrue(r.detonante_detectado)
        self.assertFalse(r.favorito_va_perdiendo)
        self.assertFalse(r.activar_accion)
        self.assertEqual(r.estado_contexto, "SIN_SEÑAL_DE_INCUMPLIMIENTO")

    def test_gol_que_deja_favorito_ganando_no_activa_accion(self):
        r = monitorear_gol(CONTEXTO, estado(50, 0, 0), estado(51, 1, 0))
        self.assertTrue(r.detonante_detectado)
        self.assertFalse(r.activar_accion)

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


if __name__ == "__main__":
    unittest.main()
