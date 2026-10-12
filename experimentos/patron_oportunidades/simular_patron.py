"""Simulaciones manuales del Patrón de Oportunidades. Ejecutar: python experimentos/patron_oportunidades/simular_patron.py"""
import json
from pathlib import Path
import sys

# Permite ejecutar el archivo directamente desde la raíz del repositorio.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from modelo_patron import ContextoPrevio, EstadoPartido, analizar_patron, resultado_a_dict


CASOS = [
    {
        "nombre": "A. Favorito domina según lo esperado",
        "contexto": ContextoPrevio(
            local="España", visitante="Croacia", favorito="España",
            expectativa="España parte como favorita; se espera que genere más peligro.",
            escenarios_esperados=("victoria España", "empate", "más goles en segunda parte"),
        ),
        "estado": EstadoPartido(
            minuto=12, goles_local=0, goles_visitante=0,
            posesion_local=62, tiros_local=6, tiros_visitante=2,
            tiros_puerta_local=2, tiros_puerta_visitante=0,
            ataques_peligrosos_local=18, ataques_peligrosos_visitante=7,
            cuotas={"resultado_1x2": 1.65, "doble_oportunidad": 1.18},
        ),
    },
    {
        "nombre": "B. Gol temprano contra el favorito: revisar, no apostar automáticamente",
        "contexto": ContextoPrevio(
            local="España", visitante="Croacia", favorito="España",
            expectativa="España es favorita antes del partido.",
            escenarios_esperados=("victoria España", "empate", "remontada posible"),
        ),
        "estado": EstadoPartido(
            minuto=15, goles_local=0, goles_visitante=1,
            posesion_local=60, tiros_local=5, tiros_visitante=3,
            tiros_puerta_local=2, tiros_puerta_visitante=1,
            ataques_peligrosos_local=15, ataques_peligrosos_visitante=10,
            cuotas={"resultado_1x2": 2.20, "doble_oportunidad": 1.35},
        ),
    },
    {
        "nombre": "C. El favorito pierde y el rival crea mucho peligro",
        "contexto": ContextoPrevio(
            local="España", visitante="Croacia", favorito="España",
            expectativa="España debería controlar buena parte del partido.",
            escenarios_esperados=("victoria España", "empate"),
        ),
        "estado": EstadoPartido(
            minuto=32, goles_local=0, goles_visitante=1,
            posesion_local=43, tiros_local=2, tiros_visitante=9,
            tiros_puerta_local=0, tiros_puerta_visitante=4,
            ataques_peligrosos_local=8, ataques_peligrosos_visitante=25,
            rojas_local=1,
            cuotas={"resultado_1x2": 3.80, "proximo_gol": 2.10},
        ),
    },
    {
        "nombre": "D. Datos incompletos",
        "contexto": ContextoPrevio(
            local="Equipo A", visitante="Equipo B", favorito="Equipo A",
            expectativa="Equipo A es favorito según el contexto previo.",
        ),
        "estado": EstadoPartido(
            minuto=20, goles_local=0, goles_visitante=0,
            tiros_local=None, tiros_visitante=None,
            tiros_puerta_local=None, tiros_puerta_visitante=None,
            posesion_local=None,
            mercados_disponibles=("resultado_1x2",),
        ),
    },
]


def main():
    for caso in CASOS:
        resultado = analizar_patron(caso["contexto"], caso["estado"])
        print("\n" + "=" * 88)
        print(caso["nombre"])
        print(json.dumps(resultado_a_dict(resultado), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
