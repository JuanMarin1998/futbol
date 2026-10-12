# Laboratorio aislado: Patrón de Oportunidades

Este experimento permanece separado de Django, Ecuabet, V1/V2/VPro y la simulación LIVE. No se conecta ni registra apuestas.

## Ejecutar
Desde la raíz del repositorio:

    python experimentos/patron_oportunidades/simular_patron.py
    python -m unittest discover -s experimentos/patron_oportunidades -p "test_*.py" -v

## Qué implementa
1. Comparación temporal entre snapshots: posesión, tiros, tiros a puerta y ataques peligrosos, con diferencia numérica y tendencia.
2. Interpretación conjunta: distingue un gol de un posible cambio sostenido de dominio. Para hablar de tendencia sostenida se requieren snapshots previos suficientes y señales concordantes.
3. Contraste de expectativas: señala las que parecen vigentes, cuestionadas o sin evidencia suficiente.
4. Escenarios a reevaluar: cada escenario reabierto incluye el motivo.
5. Separación de cuota y probabilidad: una cuota sola nunca habilita evaluar valor. Se necesita probabilidad válida del motor para el mismo mercado. El valor esperado preliminar se calcula como p * cuota - 1 y no es recomendación.
6. Casos sintéticos para gol aislado, pérdida de dominio sin gol, señales contradictorias, datos incompletos y cuota sin probabilidad.

Los datos son artificiales, no partidos reales ni predicciones. Mantener esta rama aislada hasta revisar y aprobar sus resultados.
