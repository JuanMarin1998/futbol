# Fútbol Stats

Proyecto de análisis estadístico y predicción de fútbol con Django.

## Fuente de datos

La fuente principal de datos futbolísticos es **football-data.org**. El proyecto utiliza el token que ya tienes configurado mediante:

`FOOTBALL_DATA_TOKEN`

Para clima histórico se utiliza **Open-Meteo**, que no requiere API key.

> API-Football ya no forma parte del flujo de sincronización.

## Cómo correrlo en Windows

1. Activa el entorno virtual:

```powershell
venv\Scripts\Activate.ps1
```

2. Instala dependencias:

```powershell
pip install -r requirements.txt
```

3. Comprueba que tu `.env` tenga tu token existente:

```text
FOOTBALL_DATA_TOKEN=tu_token_real
```

No compartas el token ni subas `.env` a GitHub.

4. Aplica migraciones:

```powershell
python manage.py migrate
```

5. Sincroniza una liga:

```powershell
python manage.py sincronizar_api_football --liga PD --temporada 2026 --partidos 20
```

Aunque el nombre histórico del comando conserva `sincronizar_api_football` para no romper tu flujo, **ahora utiliza exclusivamente football-data.org**.

También puedes sincronizar las cinco ligas:

```powershell
python manage.py sincronizar_api_football --partidos 20
```

Códigos:

- `PD` — La Liga
- `PL` — Premier League
- `BL1` — Bundesliga
- `SA` — Serie A
- `FL1` — Ligue 1

6. Enriquecer partidos con clima:

```powershell
python manage.py enriquecer_partidos --partidos 5
```

## Datos disponibles

football-data.org nos permite trabajar principalmente con:

- ligas y competiciones
- equipos
- escudos
- fechas y estados
- jornadas
- árbitros
- resultados
- goles
- goles al descanso
- historial de partidos
- tabla de posiciones
- goleadores
- enfrentamientos directos

Open-Meteo añade:

- temperatura
- sensación térmica
- humedad
- precipitación
- probabilidad de precipitación
- viento
- código meteorológico

Las estadísticas avanzadas de partido que dependían de API-Football no se consultan ahora. Para el modelo predictivo utilizaremos principalmente resultados históricos, goles, rendimiento, localía, forma reciente, tabla, enfrentamientos y clima.

## Próxima fase

Con la base histórica funcionando, el siguiente paso será construir las variables para predicción y después entrenar modelos como:

- Poisson para goles
- Elo para fuerza de equipos
- Regresión logística para 1X2
- modelos de machine learning cuando tengamos suficiente histórico

El entrenamiento debe hacerse con división temporal y validación sobre partidos futuros para evitar fuga de información.
