# Laboratorio aislado: Patrón de Oportunidades

Este experimento permanece separado de Django, Ecuabet, V1/V2/VPro y la simulación LIVE. No se conecta ni registra apuestas.

## Ejecutar
Desde la raíz del repositorio:

    python experimentos/patron_oportunidades/simular_contexto.py
    python experimentos/patron_oportunidades/simular_patron.py
    python -m unittest discover -s experimentos/patron_oportunidades -p "test_*.py" -v

## Punto 1: Contexto previo
El módulo `contexto_prepartido.py` resume los últimos cinco resultados disponibles de cada equipo (requiere al menos tres): puntos por partido, goles a favor/en contra y muestra de local/visitante. Expone las evidencias, expectativas iniciales, señales que habrá que observar y limitaciones.

El favorito estimado se basa en una regla explícita y sencilla sobre puntos y diferencia de goles; no es una probabilidad, una conclusión definitiva ni una recomendación de apuesta. Si faltan resultados o hay datos inválidos, no elige favorito.

**Limitación actual:** la información de los ejemplos es artificial y el módulo todavía no consulta automáticamente la base de datos ni fuentes externas. No incorpora aún calidad de rivales, lesiones, alineaciones, descanso, competición o cuotas. El siguiente trabajo es validar la lógica y después definir cómo alimentar el contexto con datos reales verificables.

## Resto del patrón
1. Comparación temporal entre snapshots: posesión, tiros, tiros a puerta y ataques peligrosos, con diferencia numérica y tendencia.
2. Interpretación conjunta: distingue un gol de un posible cambio sostenido de dominio.
3. Contraste de expectativas: señala las que parecen vigentes, cuestionadas o sin evidencia suficiente.
4. Escenarios a reevaluar: cada escenario reabierto incluye el motivo.
5. Separación de cuota y probabilidad: una cuota sola nunca habilita evaluar valor; se necesita una probabilidad válida del motor para el mismo mercado.
6. Validación temporal: detecta marcador o estadísticas acumuladas que retroceden y bloquea el cálculo hasta verificar los datos.

Los datos de las simulaciones son artificiales, no partidos reales ni predicciones. Mantener esta rama aislada hasta revisar y aprobar sus resultados.
