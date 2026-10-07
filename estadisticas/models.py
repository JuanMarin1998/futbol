from django.db import models


class Liga(models.Model):
    codigo = models.CharField(max_length=10, unique=True)
    nombre = models.CharField(max_length=100)
    pais = models.CharField(max_length=100, blank=True)
    api_football_id = models.IntegerField(unique=True, null=True, blank=True)
    api_football_logo = models.URLField(blank=True)

    class Meta:
        verbose_name = "Liga"
        verbose_name_plural = "Ligas"

    def __str__(self):
        return self.nombre


class Estadio(models.Model):
    api_football_id = models.IntegerField(unique=True, null=True, blank=True)
    nombre = models.CharField(max_length=200)
    ciudad = models.CharField(max_length=120, blank=True)
    pais = models.CharField(max_length=100, blank=True)
    capacidad = models.IntegerField(null=True, blank=True)
    direccion = models.CharField(max_length=250, blank=True)
    superficie = models.CharField(max_length=100, blank=True)
    latitud = models.FloatField(null=True, blank=True)
    longitud = models.FloatField(null=True, blank=True)

    class Meta:
        verbose_name = "Estadio"
        verbose_name_plural = "Estadios"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Equipo(models.Model):
    id_externo = models.IntegerField(unique=True, null=True, blank=True)
    api_football_id = models.IntegerField(unique=True, null=True, blank=True)
    nombre = models.CharField(max_length=150)
    nombre_corto = models.CharField(max_length=50, blank=True)
    escudo_url = models.URLField(blank=True)
    liga = models.ForeignKey(Liga, on_delete=models.CASCADE, related_name="equipos")
    fundado = models.IntegerField(null=True, blank=True)
    estadio = models.CharField(max_length=150, blank=True)
    estadio_obj = models.ForeignKey(Estadio, on_delete=models.SET_NULL, null=True, blank=True, related_name="equipos")
    pais = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = "Equipo"
        verbose_name_plural = "Equipos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Jugador(models.Model):
    POSICIONES = [
        ("POR", "Portero"),
        ("DEF", "Defensa"),
        ("MED", "Mediocampista"),
        ("DEL", "Delantero"),
    ]
    id_externo = models.IntegerField(unique=True, null=True, blank=True)
    api_football_id = models.IntegerField(unique=True, null=True, blank=True)
    nombre = models.CharField(max_length=150)
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name="jugadores")
    posicion = models.CharField(max_length=3, choices=POSICIONES, blank=True)
    posicion_detalle = models.CharField(max_length=80, blank=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    nacionalidad = models.CharField(max_length=100, blank=True)
    dorsal = models.IntegerField(null=True, blank=True)
    foto_url = models.URLField(blank=True)
    lesionado = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Jugador"
        verbose_name_plural = "Jugadores"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Partido(models.Model):
    ESTADOS = [
        ("PROGRAMADO", "Programado"),
        ("EN_JUEGO", "En juego"),
        ("FINALIZADO", "Finalizado"),
        ("APLAZADO", "Aplazado"),
        ("CANCELADO", "Cancelado"),
    ]
    id_externo = models.IntegerField(unique=True, null=True, blank=True)
    api_football_id = models.IntegerField(unique=True, null=True, blank=True)
    liga = models.ForeignKey(Liga, on_delete=models.CASCADE, related_name="partidos")
    temporada = models.IntegerField()
    equipo_local = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name="partidos_local")
    equipo_visitante = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name="partidos_visitante")
    estadio = models.ForeignKey(Estadio, on_delete=models.SET_NULL, null=True, blank=True, related_name="partidos")
    fecha = models.DateTimeField()
    estado = models.CharField(max_length=20, choices=ESTADOS, default="PROGRAMADO")
    estado_api = models.CharField(max_length=30, blank=True)
    goles_local = models.IntegerField(null=True, blank=True)
    goles_visitante = models.IntegerField(null=True, blank=True)
    goles_local_descanso = models.IntegerField(null=True, blank=True)
    goles_visitante_descanso = models.IntegerField(null=True, blank=True)
    jornada = models.IntegerField(null=True, blank=True)
    arbitro = models.CharField(max_length=150, blank=True)
    ronda = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name = "Partido"
        verbose_name_plural = "Partidos"
        ordering = ["-fecha"]
        indexes = [
            models.Index(fields=["liga", "temporada", "estado", "fecha"], name="idx_partido_liga_temp_estado_fecha"),
            models.Index(fields=["equipo_local", "estado", "fecha"], name="idx_partido_local_estado_fecha"),
            models.Index(fields=["equipo_visitante", "estado", "fecha"], name="idx_partido_visitante_estado_fecha"),
        ]

    def __str__(self):
        return f"{self.equipo_local} vs {self.equipo_visitante} ({self.fecha.strftime('%Y-%m-%d')})"

    @property
    def resultado(self):
        if self.goles_local is None or self.goles_visitante is None:
            return "vs"
        return f"{self.goles_local} - {self.goles_visitante}"


class EstadisticaPartido(models.Model):
    partido = models.OneToOneField(Partido, on_delete=models.CASCADE, related_name="estadisticas")
    posesion_local = models.FloatField(null=True, blank=True)
    posesion_visitante = models.FloatField(null=True, blank=True)
    tiros_local = models.IntegerField(null=True, blank=True)
    tiros_visitante = models.IntegerField(null=True, blank=True)
    tiros_puerta_local = models.IntegerField(null=True, blank=True)
    tiros_puerta_visitante = models.IntegerField(null=True, blank=True)
    tiros_fuera_local = models.IntegerField(null=True, blank=True)
    tiros_fuera_visitante = models.IntegerField(null=True, blank=True)
    corners_local = models.IntegerField(null=True, blank=True)
    corners_visitante = models.IntegerField(null=True, blank=True)
    faltas_local = models.IntegerField(null=True, blank=True)
    faltas_visitante = models.IntegerField(null=True, blank=True)
    tarjetas_amarillas_local = models.IntegerField(null=True, blank=True)
    tarjetas_amarillas_visitante = models.IntegerField(null=True, blank=True)
    tarjetas_rojas_local = models.IntegerField(null=True, blank=True)
    tarjetas_rojas_visitante = models.IntegerField(null=True, blank=True)
    pases_local = models.IntegerField(null=True, blank=True)
    pases_visitante = models.IntegerField(null=True, blank=True)
    precision_pases_local = models.FloatField(null=True, blank=True)
    precision_pases_visitante = models.FloatField(null=True, blank=True)
    ataques_local = models.IntegerField(null=True, blank=True)
    ataques_visitante = models.IntegerField(null=True, blank=True)
    ataques_peligrosos_local = models.IntegerField(null=True, blank=True)
    ataques_peligrosos_visitante = models.IntegerField(null=True, blank=True)
    fuera_de_juego_local = models.IntegerField(null=True, blank=True)
    fuera_de_juego_visitante = models.IntegerField(null=True, blank=True)
    datos_raw = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Estadística de partido"
        verbose_name_plural = "Estadísticas de partidos"


class ClimaPartido(models.Model):
    partido = models.OneToOneField(Partido, on_delete=models.CASCADE, related_name="clima")
    temperatura = models.FloatField(null=True, blank=True)
    sensacion_termica = models.FloatField(null=True, blank=True)
    humedad = models.FloatField(null=True, blank=True)
    precipitacion = models.FloatField(null=True, blank=True)
    probabilidad_precipitacion = models.FloatField(null=True, blank=True)
    viento_kmh = models.FloatField(null=True, blank=True)
    codigo_clima = models.IntegerField(null=True, blank=True)
    descripcion = models.CharField(max_length=120, blank=True)
    fuente = models.CharField(max_length=50, default="open-meteo")
    datos_raw = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Clima del partido"
        verbose_name_plural = "Clima de partidos"


class TablaPosicion(models.Model):
    liga = models.ForeignKey(Liga, on_delete=models.CASCADE, related_name="tablas_posicion")
    temporada = models.IntegerField()
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name="posiciones")
    posicion = models.IntegerField()
    partidos_jugados = models.IntegerField(default=0)
    victorias = models.IntegerField(default=0)
    empates = models.IntegerField(default=0)
    derrotas = models.IntegerField(default=0)
    goles_favor = models.IntegerField(default=0)
    goles_contra = models.IntegerField(default=0)
    diferencia_goles = models.IntegerField(default=0)
    puntos = models.IntegerField(default=0)
    forma = models.CharField(max_length=30, blank=True)

    class Meta:
        verbose_name = "Posición en tabla"
        verbose_name_plural = "Posiciones en tablas"
        ordering = ["liga", "temporada", "posicion"]
        constraints = [
            models.UniqueConstraint(
                fields=["liga", "temporada", "equipo"],
                name="uniq_tabla_liga_temporada_equipo",
            )
        ]
        indexes = [
            models.Index(fields=["liga", "temporada", "posicion"], name="idx_tabla_liga_temp_pos"),
        ]


class GoleadorTemporada(models.Model):
    liga = models.ForeignKey(Liga, on_delete=models.CASCADE, related_name="goleadores")
    temporada = models.IntegerField()
    jugador = models.ForeignKey(Jugador, on_delete=models.CASCADE, related_name="registros_goleador")
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name="goleadores")
    posicion = models.IntegerField(default=0)
    goles = models.IntegerField(default=0)
    asistencias = models.IntegerField(null=True, blank=True)
    penaltis = models.IntegerField(null=True, blank=True)
    partidos_jugados = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Goleador de temporada"
        verbose_name_plural = "Goleadores de temporadas"
        ordering = ["liga", "temporada", "posicion"]
        constraints = [
            models.UniqueConstraint(
                fields=["liga", "temporada", "jugador", "equipo"],
                name="uniq_goleador_liga_temporada_jugador_equipo",
            )
        ]
        indexes = [
            models.Index(fields=["liga", "temporada", "posicion"], name="idx_goleador_liga_temp_pos"),
        ]
