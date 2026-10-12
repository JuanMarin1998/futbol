# Laboratorio aislado: Patrón de Oportunidades

Este experimento no se conecta a Django, Ecuabet, V1/V2/VPro ni a la simulación LIVE.

## Archivos
- `modelo_patron.py`: etapas Contexto → Acción → escenarios disponibles.
- `simular_patron.py`: cuatro casos controlados para revisar el comportamiento.

## Ejecutar desde la raíz del repositorio
```powershell
python experimentos/patron_oportunidades/simular_patron.py
```

## Qué debe comprobarse
1. El favorito dominando no produce un detonante de contradicción fuerte.
2. Un gol en contra del favorito genera revisión, no una apuesta automática.
3. Señales adicionales contrarias al contexto se enumeran como detonantes.
4. Cuando faltan estadísticas, el modelo lo declara explícitamente.
5. Se enumeran mercados disponibles, pero las probabilidades quedan vacías para que las calculen los motores.
6. No se recomienda ni se registra ninguna apuesta.

Los casos son ejemplos sintéticos para validar la lógica, no predicciones ni resultados reales. Este prototipo es la primera versión del patrón y debe revisarse antes de conectarlo a datos LIVE.
