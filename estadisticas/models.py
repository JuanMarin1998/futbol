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
    ecuabet_event_id = models.BigIntegerField(unique=True, null=True, blank=True)

    class Meta:
        verbose_name = "Partido"
        verbose_name_plural = "Partidos"
        ordering = ["-fecha"]
        indexes = [
            models.Index(fields=["liga", "temporada", "estado", "fecha"], name="idx_pto_lig_tmp_est_fecha"),
            models.Index(fields=["equipo_local", "estado", "fecha"], name="idx_partido_local_estado_fecha"),
            models.Index(fields=["equipo_visitante", "estado", "fecha"], name="idx_partido_visit_est_fecha"),
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


class Cuota1X2Snapshot(models.Model):
    partido = models.ForeignKey(Partido, on_delete=models.CASCADE, related_name="cuotas_1x2")
    ecuabet_event_id = models.BigIntegerField()
    odd_id_local = models.BigIntegerField(null=True, blank=True)
    odd_id_empate = models.BigIntegerField(null=True, blank=True)
    odd_id_visitante = models.BigIntegerField(null=True, blank=True)
    cuota_local = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    cuota_empate = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    cuota_visitante = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    es_live = models.BooleanField(default=False)
    minuto = models.CharField(max_length=20, blank=True)
    periodo = models.CharField(max_length=50, blank=True)
    marcador_local = models.IntegerField(null=True, blank=True)
    marcador_visitante = models.IntegerField(null=True, blank=True)
    observado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Snapshot de cuota 1X2"
        verbose_name_plural = "Snapshots de cuotas 1X2"
        ordering = ["-observado_en"]
        indexes = [
            models.Index(fields=["partido", "-observado_en"], name="idx_cuota_part_obs"),
            models.Index(fields=["ecuabet_event_id", "-observado_en"], name="idx_cuota_event_obs"),
        ]


class LiveExperiment(models.Model):
    """
    Experimento reproducible de los motores V1/V2 sobre un partido LIVE.
    Las "vidas" son unidades virtuales; no representan dinero real.
    """
    STATUS = [
        ("RUNNING", "Ejecutando"),
        ("STOPPED", "Detenido"),
        ("FINISHED", "Finalizado"),
    ]

    ecuabet_event_id = models.BigIntegerField(db_index=True)
    flashscore_event_id = models.CharField(max_length=80, blank=True)
    home_team = models.CharField(max_length=150)
    away_team = models.CharField(max_length=150)
    vpro_reference_odds = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default="RUNNING")
    initial_lives = models.DecimalField(max_digits=12, decimal_places=4, default=100)
    v1_lives = models.DecimalField(max_digits=12, decimal_places=4, default=100)
    v2_lives = models.DecimalField(max_digits=12, decimal_places=4, default=100)
    v1_max_lives = models.DecimalField(max_digits=12, decimal_places=4, default=100)
    v2_max_lives = models.DecimalField(max_digits=12, decimal_places=4, default=100)
    v1_min_lives = models.DecimalField(max_digits=12, decimal_places=4, default=100)
    v2_min_lives = models.DecimalField(max_digits=12, decimal_places=4, default=100)
    v1_wins = models.PositiveIntegerField(default=0)
    v1_losses = models.PositiveIntegerField(default=0)
    v2_wins = models.PositiveIntegerField(default=0)
    v2_losses = models.PositiveIntegerField(default=0)
    last_minute = models.CharField(max_length=30, blank=True)
    last_period = models.CharField(max_length=60, blank=True)
    last_home_score = models.IntegerField(null=True, blank=True)
    last_away_score = models.IntegerField(null=True, blank=True)
    final_home_score = models.IntegerField(null=True, blank=True)
    final_away_score = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Experimento LIVE"
        verbose_name_plural = "Experimentos LIVE"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["ecuabet_event_id", "status"], name="idx_live_exp_event_status"),
        ]

    @property
    def total_v1_pnl(self):
        return float(self.v1_lives) - float(self.initial_lives)

    @property
    def total_v2_pnl(self):
        return float(self.v2_lives) - float(self.initial_lives)


class LiveExperimentEntry(models.Model):
    """Una decisión tomada por un motor dentro de un experimento."""

    STATUS = [
        ("OPEN", "Abierta"),
        ("WON", "Ganada"),
        ("LOST", "Perdida"),
        ("CANCELLED", "Cancelada"),
    ]
    MOTOR = [
        ("V1", "Motor V1"),
        ("V11", "Motor V1.1"),
        ("V12", "Motor V1.2"),
        ("V2", "Motor V2"),
        ("V21", "Motor V2.1"),
        ("V22", "Motor V2.2"),
        ("V3", "Motor V3"),
        ("V2U", "Motor V2.Ultra"),
        ("V11U", "Motor V1.1 Ultra"),
        ("V4", "Motor V4 · Calibración prudente"),
        ("ESP", "Espía de Apuestas · Consenso estricto"),
    ]

    experiment = models.ForeignKey(
        LiveExperiment,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    motor = models.CharField(max_length=4, choices=MOTOR)
    opportunity_key = models.CharField(max_length=255)
    market = models.CharField(max_length=150, blank=True)
    selection = models.CharField(max_length=150)
    line = models.CharField(max_length=80, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=4)
    model_probability = models.FloatField()
    implied_probability = models.FloatField()
    edge = models.FloatField()
    level = models.PositiveSmallIntegerField()
    level_name = models.CharField(max_length=40)
    stake = models.DecimalField(max_digits=12, decimal_places=4)
    potential_profit = models.DecimalField(max_digits=12, decimal_places=4)
    reason = models.TextField()
    supporting_factors = models.JSONField(default=list, blank=True)
    contradicting_factors = models.JSONField(default=list, blank=True)
    opportunity_snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default="OPEN")
    pnl = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    placed_minute = models.CharField(max_length=30, blank=True)
    placed_home_score = models.IntegerField(null=True, blank=True)
    placed_away_score = models.IntegerField(null=True, blank=True)
    placed_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Entrada de experimento"
        verbose_name_plural = "Entradas de experimento"
        ordering = ["-placed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["experiment", "motor", "opportunity_key"],
                name="uniq_live_exp_motor_opportunity",
            ),
        ]
        indexes = [
            models.Index(fields=["experiment", "motor", "status"], name="idx_live_exp_entry_motor"),
        ]


class LiveExperimentSnapshot(models.Model):
    """Fotografía de cada decisión/análisis LIVE para auditoría del experimento."""

    experiment = models.ForeignKey(
        LiveExperiment,
        on_delete=models.CASCADE,
        related_name="snapshots",
    )
    motor = models.CharField(max_length=4, choices=LiveExperimentEntry.MOTOR)
    minute = models.CharField(max_length=30, blank=True)
    period = models.CharField(max_length=60, blank=True)
    home_score = models.IntegerField(null=True, blank=True)
    away_score = models.IntegerField(null=True, blank=True)
    lives_before = models.DecimalField(max_digits=12, decimal_places=4)
    lives_after = models.DecimalField(max_digits=12, decimal_places=4)
    selected_opportunity = models.JSONField(null=True, blank=True)
    all_opportunities = models.JSONField(default=list, blank=True)
    decision_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Snapshot de experimento"
        verbose_name_plural = "Snapshots de experimento"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["experiment", "motor", "-created_at"], name="idx_live_exp_snap_motor"),
        ]


class LiveExperimentDailyArchive(models.Model):
    """Copia congelada de un día completo del laboratorio LIVE."""

    experiment_date = models.DateField(unique=True)
    saved_at = models.DateTimeField(auto_now=True)
    experiment_count = models.PositiveIntegerField(default=0)
    decision_count = models.PositiveIntegerField(default=0)
    motors_summary = models.JSONField(default=dict, blank=True)
    experiments_data = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Archivo diario de experimento LIVE"
        verbose_name_plural = "Archivos diarios de experimento LIVE"
        ordering = ["-experiment_date"]

