"""Casos sintéticos ampliados del patrón; no son partidos reales."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from modelo_patron import ContextoPrevio, EstadoPartido, analizar_patron, resultado_a_dict

CTX = ContextoPrevio(
    local="España", visitante="Croacia", favorito="España",
    expectativa="España es favorita y se espera que genere más peligro.",
    escenarios_esperados=("victoria España", "empate", "remontada posible", "España genera más peligro"),
)

def estado(minuto, gl=0, gv=0, *, posesion=58, tl=5, tv=4, tpl=2, tpv=1,
           apl=15, apv=12, rl=0, rv=0, cuotas=None, mercados=None):
    return EstadoPartido(minuto=minuto, goles_local=gl, goles_visitante=gv, posesion_local=posesion,
        tiros_local=tl, tiros_visitante=tv, tiros_puerta_local=tpl, tiros_puerta_visitante=tpv,
        ataques_peligrosos_local=apl, ataques_peligrosos_visitante=apv, rojas_local=rl, rojas_visitante=rv,
        mercados_disponibles=tuple(mercados) if mercados is not None else
            ("resultado_1x2", "doble_oportunidad", "proximo_gol", "total_goles", "ambos_marcan"),
        cuotas=cuotas or {"resultado_1x2": 2.2})

def mostrar(nombre, actual, anterior=None, historial=None, probs=None):
    r = analizar_patron(CTX, actual, anterior, historial, probs)
    print("\n" + "=" * 96 + "\n" + nombre)
    print(json.dumps(resultado_a_dict(r), ensure_ascii=False, indent=2))

def main():
    s8 = estado(8, posesion=60, tl=3, tv=1, tpl=1, tpv=0, apl=10, apv=4)
    s12 = estado(12, posesion=61, tl=5, tv=2, tpl=2, tpv=0, apl=15, apv=6,
                 cuotas={"resultado_1x2": 1.65, "doble_oportunidad": 1.18})
    mostrar("A. Favorito mantiene el dominio", s12, s8)

    s15 = estado(15, gv=1, posesion=64, tl=8, tv=3, tpl=4, tpv=1, apl=23, apv=8,
                 cuotas={"resultado_1x2": 2.20, "doble_oportunidad": 1.35})
    mostrar("B. Favorito recibe un gol, pero sigue dominando", s15, s12)

    s20 = estado(20, tpl=1, tpv=2, tl=5, tv=7, apl=12, apv=17, posesion=52)
    s27 = estado(27, tpl=1, tpv=4, tl=6, tv=12, apl=13, apv=28, posesion=45)
    mostrar("C. Pierde el dominio sin que haya goles", s27, s20, historial=[s12, s20])

    s32 = estado(32, gv=1, tpl=4, tpv=3, tl=8, tv=9, apl=20, apv=21,
                 posesion=51, rl=1, cuotas={"resultado_1x2": 3.8, "proximo_gol": 2.1})
    mostrar("D. Indicadores contradictorios y tarjeta roja", s32, s27, historial=[s12, s20, s27])

    incompleto = EstadoPartido(minuto=20, goles_local=0, goles_visitante=0,
        tiros_puerta_local=None, tiros_puerta_visitante=None, mercados_disponibles=("resultado_1x2",))
    ctx_incompleto = ContextoPrevio(local="Equipo A", visitante="Equipo B", favorito="Equipo A",
        expectativa="Equipo A es favorito según el contexto previo.")
    print("\n" + "=" * 96 + "\nE. Datos incompletos")
    print(json.dumps(resultado_a_dict(analizar_patron(ctx_incompleto, incompleto)), ensure_ascii=False, indent=2))

    solo_cuota = estado(40, gl=1, cuotas={"resultado_1x2": 1.4}, mercados=("resultado_1x2",))
    mostrar("F. Cuota sin probabilidad: no hay valor calculable", solo_cuota, s32)

if __name__ == "__main__":
    main()
