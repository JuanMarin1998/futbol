from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("estadisticas", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TablaPosicion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("temporada", models.IntegerField()),
                ("posicion", models.IntegerField()),
                ("partidos_jugados", models.IntegerField(default=0)),
                ("victorias", models.IntegerField(default=0)),
                ("empates", models.IntegerField(default=0)),
                ("derrotas", models.IntegerField(default=0)),
                ("goles_favor", models.IntegerField(default=0)),
                ("goles_contra", models.IntegerField(default=0)),
                ("diferencia_goles", models.IntegerField(default=0)),
                ("puntos", models.IntegerField(default=0)),
                ("forma", models.CharField(blank=True, max_length=30)),
                ("equipo", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="posiciones", to="estadisticas.equipo")),
                ("liga", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tablas_posicion", to="estadisticas.liga")),
            ],
            options={
                "verbose_name": "Posición en tabla",
                "verbose_name_plural": "Posiciones en tablas",
                "ordering": ["liga", "temporada", "posicion"],
            },
        ),
        migrations.CreateModel(
            name="GoleadorTemporada",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("temporada", models.IntegerField()),
                ("posicion", models.IntegerField(default=0)),
                ("goles", models.IntegerField(default=0)),
                ("asistencias", models.IntegerField(blank=True, null=True)),
                ("penaltis", models.IntegerField(blank=True, null=True)),
                ("partidos_jugados", models.IntegerField(blank=True, null=True)),
                ("equipo", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="goleadores", to="estadisticas.equipo")),
                ("jugador", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="registros_goleador", to="estadisticas.jugador")),
                ("liga", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="goleadores", to="estadisticas.liga")),
            ],
            options={
                "verbose_name": "Goleador de temporada",
                "verbose_name_plural": "Goleadores de temporadas",
                "ordering": ["liga", "temporada", "posicion"],
            },
        ),
        migrations.AddConstraint(
            model_name="tablaposicion",
            constraint=models.UniqueConstraint(
                fields=("liga", "temporada", "equipo"),
                name="uniq_tabla_liga_temporada_equipo",
            ),
        ),
        migrations.AddConstraint(
            model_name="goleadortemporada",
            constraint=models.UniqueConstraint(
                fields=("liga", "temporada", "jugador", "equipo"),
                name="uniq_goleador_liga_temporada_jugador_equipo",
            ),
        ),
    ]
