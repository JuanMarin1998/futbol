# Fútbol Stats

Proyecto de análisis estadístico de fútbol con Django, datos reales de [football-data.org](https://www.football-data.org/).

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
4. Crea tu archivo `.env` copiando `.env.example` y pegando tu token real de football-data.org:
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
