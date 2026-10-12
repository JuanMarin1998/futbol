# Laboratorio aislado: Patrón de Oportunidades

Este experimento no se conecta a Django, Ecuabet, V1/V2/VPro ni a la simulación LIVE.

## Archivos
- `modelo_patron.py`: registra contexto previo, compara señales y puede comparar una instantánea actual con una anterior.
- `simular_patron.py`: cuatro casos sintéticos para probar la lógica.

## Ejecutar desde la raíz del repositorio
```powershell
python experimentos/patron_oportunidades/simular_patron.py
```

## Qué observar
1. Si el favorito mantiene el dominio, no debe activarse una contradicción fuerte sin señales que la respalden.
2. Un gol que cambia el marcador debe activar revisión, no una apuesta automática.
3. El modelo compara señales disponibles y muestra el contexto inicial y los escenarios esperados.
4. Los mercados sin cuota quedan identificados como `SIN_CUOTA_DISPONIBLE`.
5. Si faltan tiros a puerta de ambos equipos, no se permite pasar a cálculo.
6. Calcular probabilidades y evaluar valor son cosas distintas: tener una cuota no significa que exista una apuesta de valor.
7. No se recomienda ni se registra ninguna apuesta.

Los casos son ejemplos sintéticos, no partidos reales ni predicciones. Esta rama es un laboratorio aislado y no debe integrarse a LIVE hasta validar sus salidas.
