# Contexto ampliado de Flashscore

El laboratorio puede adjuntar a cada LiveMatch un bloque pre_match_context con tres fuentes independientes:

- lineups: alineaciones, formación y ausencias cuando el proveedor las publique.
- history: enfrentamientos directos y forma reciente.
- fixtures: resultados anteriores y próximos partidos por equipo.

## Configuración

Configura FLASHSCORE_CONTEXT_API_URL como URL base de un adaptador HTTP compatible con los endpoints de Flashscore Scraper:

- GET /matches/lineups?match=<flashscore_event_id>
- GET /matches/h2h?match=<flashscore_event_id>
- GET /teams/results?team=<flashscore_team_id>&page=1
- GET /teams/fixtures?team=<flashscore_team_id>&page=1

El adaptador debe aceptar los IDs Flashscore que ya devuelve el evento. Una opción es desplegar un scraper compatible de Flashscore bajo infraestructura propia y restringirlo a uso autorizado. No se establece un proveedor remoto por defecto: Flashscore no garantiza una API pública estable y no queremos enviar tráfico a un host no configurado.

Ejemplo en .env:

    FLASHSCORE_CONTEXT_API_URL=http://127.0.0.1:8090
    FLASHSCORE_CONTEXT_TIMEOUT=6

La integración no bloquea los motores si la fuente falla. Cada sección informa available, empty o unavailable, con error cuando corresponda. La caché local usa 5 minutos para alineaciones, 6 horas para historial y 3 horas para calendario. Como la caché es en memoria del proceso, en despliegues con múltiples workers conviene sustituirla por caché compartida.

## Compatibilidad

El contexto se añade al objeto y a to_dict(), pero no cambia las fórmulas de V1, V2 ni V.Pro. Las versiones nuevas pueden leer match.pre_match_context para experimentos controlados. No se debe tratar una fuente ausente como cero ni como confirmación de que no hay bajas.


## Ver alineaciones en LIVE Ecuabet

La vista `/live/ecuabet/<id>/` incluye una tarjeta **👥 Alineaciones**. La tarjeta muestra titulares, suplentes y formación si el adaptador entrega esos campos. Si no llegan datos, presenta el estado y el error de la fuente; no rellena jugadores ficticios. Si el proveedor responde con un formato diferente, el bloque de diagnóstico muestra una parte del JSON recibido para adaptar el normalizador.

La página Django no puede actuar como proveedor de alineaciones por sí sola. Para obtener datos reales, hay que ejecutar o desplegar un adaptador compatible y apuntar `FLASHSCORE_CONTEXT_API_URL` a su URL base. El scraper de referencia es [omkarcloud/flashscore-scraper](https://github.com/omkarcloud/flashscore-scraper); consulta su README para dependencias, endpoints y condiciones de uso. Si el servicio se ejecuta en la misma PC, usa un puerto distinto del servidor Django (por ejemplo, 8090) y verifica que responda a `/matches/lineups?match=<ID_FLASHScore>`.

Después de configurar el servicio, reinicia Django para que lea las variables del entorno y abre el detalle de un partido. La tarjeta mostrará explícitamente si la fuente está sin configurar, no responde, devuelve datos vacíos o entregó alineaciones reconocibles.
