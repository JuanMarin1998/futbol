from django.db import models


class Liga(models.Model):
    """Una competición/liga (ej: La Liga, Premier League)."""

    codigo = models.CharField(max_length=10, unique=True)  # ej: PD, PL, BL1, SA, FL1
    nombre = models.CharField(max_length=100)
    pais = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = "Liga"
        verbose_name_plural = "Ligas"

    def __str__(self):
        return self.nombre


class Equipo(models.Model):
    """Un equipo de fútbol."""

    id_externo = models.IntegerField(unique=True, null=True, blank=True)  # id en football-data.org
    nombre = models.CharField(max_length=150)
    nombre_corto = models.CharField(max_length=50, blank=True)
    escudo_url = models.URLField(blank=True)
    liga = models.ForeignKey(Liga, on_delete=models.CASCADE, related_name="equipos")
    fundado = models.IntegerField(null=True, blank=True)
    estadio = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name = "Equipo"
        verbose_name_plural = "Equipos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Jugador(models.Model):
    """Un jugador de fútbol."""

    POSICIONES = [
        ("POR", "Portero"),
        ("DEF", "Defensa"),
        ("MED", "Mediocampista"),
        ("DEL", "Delantero"),
    ]

    id_externo = models.IntegerField(unique=True, null=True, blank=True)
    nombre = models.CharField(max_length=150)
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name="jugadores")
    posicion = models.CharField(max_length=3, choices=POSICIONES, blank=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    nacionalidad = models.CharField(max_length=100, blank=True)
    dorsal = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Jugador"
        verbose_name_plural = "Jugadores"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Partido(models.Model):
    """Un partido entre dos equipos."""

    ESTADOS = [
        ("PROGRAMADO", "Programado"),
        ("EN_JUEGO", "En juego"),
        ("FINALIZADO", "Finalizado"),
        ("APLAZADO", "Aplazado"),
        ("CANCELADO", "Cancelado"),
    ]

    id_externo = models.IntegerField(unique=True, null=True, blank=True)
    liga = models.ForeignKey(Liga, on_delete=models.CASCADE, related_name="partidos")
    equipo_local = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name="partidos_local")
    equipo_visitante = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name="partidos_visitante")
    fecha = models.DateTimeField()
    estado = models.CharField(max_length=20, choices=ESTADOS, default="PROGRAMADO")
    goles_local = models.IntegerField(null=True, blank=True)
    goles_visitante = models.IntegerField(null=True, blank=True)
    jornada = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Partido"
        verbose_name_plural = "Partidos"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.equipo_local} vs {self.equipo_visitante} ({self.fecha.strftime('%Y-%m-%d')})"

    @property
    def resultado(self):
        if self.goles_local is None or self.goles_visitante is None:
            return "vs"
        return f"{self.goles_local} - {self.goles_visitante}"
