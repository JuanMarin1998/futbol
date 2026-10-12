"""Casos sintéticos del patrón. Ejecutar desde la raíz del repo."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from modelo_patron import ContextoPrevio, EstadoPartido, analizar_patron, resultado_a_dict

def caso(nombre, minuto, goles_local, goles_visitante, tiros_puerta_local, tiros_puerta_visitante, anterior=None, cuotas=None, rojas_local=0):
    contexto = ContextoPrevio(
        local="España", visitante="Croacia", favorito="España",
        expectativa="España es favorita y se espera que genere más peligro.",
        escenarios_esperados=("victoria España", "empate", "remontada posible"),
    )
    actual = EstadoPartido(
        minuto=minuto, goles_local=goles_local, goles_visitante=goles_visitante,
        posesion_local=58, tiros_local=5, tiros_visitante=4,
        tiros_puerta_local=tiros_puerta_local, tiros_puerta_visitante=tiros_puerta_visitante,
        ataques_peligrosos_local=15, ataques_peligrosos_visitante=12,
        rojas_local=rojas_local, cuotas=cuotas or {"resultado_1x2": 2.2},
    )
    resultado = analizar_patron(contexto, actual, anterior)
    print("\n" + "=" * 88 + "\n" + nombre)
    print(json.dumps(resultado_a_dict(resultado), ensure_ascii=False, indent=2))

def main():
    previo = EstadoPartido(
        minuto=8, goles_local=0, goles_visitante=0, posesion_local=60,
        tiros_local=3, tiros_visitante=1, tiros_puerta_local=1,
        tiros_puerta_visitante=0, ataques_peligrosos_local=10,
        ataques_peligrosos_visitante=4,
    )
    caso("A. Favorito mantiene el dominio", 12, 0, 0, 2, 0, previo,
         {"resultado_1x2": 1.65, "doble_oportunidad": 1.18})
    caso("B. Gol contra el favorito: revisar el contexto", 15, 0, 1, 2, 1, previo,
         {"resultado_1x2": 2.20, "doble_oportunidad": 1.35})
    caso("C. Favorito pierde, rival domina y hay roja", 32, 0, 1, 0, 4, previo,
         {"resultado_1x2": 3.80, "proximo_gol": 2.10}, rojas_local=1)
    contexto = ContextoPrevio(local="Equipo A", visitante="Equipo B", favorito="Equipo A",
        expectativa="Equipo A es favorito según el contexto previo.")
    incompleto = EstadoPartido(minuto=20, goles_local=0, goles_visitante=0,
        tiros_puerta_local=None, tiros_puerta_visitante=None,
        mercados_disponibles=("resultado_1x2",))
    resultado = analizar_patron(contexto, incompleto)
    print("\n" + "=" * 88 + "\nD. Datos incompletos")
    print(json.dumps(resultado_a_dict(resultado), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
