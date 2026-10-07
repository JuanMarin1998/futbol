# Fútbol Stats

Proyecto de análisis estadístico y predicción de fútbol con Django. Integra API-Football como fuente principal de datos futbolísticos, Open-Meteo para clima histórico y football-data.org como fuente secundaria.

## Cómo correrlo en tu PC (Windows)

1. Copia todos estos archivos dentro de tu carpeta `futbol-stats` (donde ya tienes el entorno virtual `venv`).
2. Activa tu entorno virtual:
   ```powershell
   venv\Scripts\Activate.ps1
   ```
3. Instala las dependencias:
   ```powershell
   pip install -r requirements.txt
   ```
4. Crea tu archivo `.env` copiando `.env.example` y configura `API_FOOTBALL_KEY` (y opcionalmente `FOOTBALL_DATA_TOKEN`):
   ```powershell
   copy .env.example .env
   notepad .env
   ```
5. Aplica las migraciones (crea la base de datos):
   ```powershell
   python manage.py migrate
   ```
6. Levanta el servidor:
   ```powershell
   python manage.py runserver
   ```
7. Abre en tu navegador: http://127.0.0.1:8000/

Deberías ver las 5 ligas principales, y al entrar a cada una, partidos reales (próximos y resultados recientes) y la tabla de posiciones.

## Sincronizar datos desde API-Football

Después de configurar `API_FOOTBALL_KEY` y aplicar las migraciones:

```powershell
python manage.py migrate
python manage.py sincronizar_api_football --liga PD --temporada 2026 --partidos 20
```

Códigos disponibles: `PD`, `PL`, `BL1`, `SA`, `FL1`.

Para enriquecer partidos guardados con estadísticas y clima histórico:

```powershell
python manage.py enriquecer_partidos --partidos 5
```

`Open-Meteo` no requiere API key.

## Opcional: cargar equipos a la base de datos

Para guardar los equipos de las 5 ligas en tu base de datos local (útil para las siguientes fases del proyecto):

```powershell
python manage.py cargar_equipos
```

## Estructura del proyecto

```
futbol_stats/       → configuración del proyecto Django
estadisticas/        → la app principal
    models.py         → Liga, Equipo, Jugador, Partido
    api_client.py      → cliente de football-data.org
    views.py           → vistas (inicio, partidos, tabla)
    templates/          → HTML
    management/commands/cargar_equipos.py → script de ingesta
```

## Próximas fases

- Fase 3: cálculos estadísticos (Poisson, Elo, rendimiento normalizado).
- Fase 5: integración con IA (function calling) para consultas en lenguaje natural.
