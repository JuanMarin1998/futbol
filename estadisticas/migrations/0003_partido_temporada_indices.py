from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("estadisticas", "0002_tabla_goleadores"),
    ]

    operations = [
        migrations.AddField(
            model_name="partido",
            name="temporada",
            field=models.IntegerField(default=2026),
            preserve_default=False,
        ),
        migrations.AddIndex(
            model_name="partido",
            index=models.Index(
                fields=["liga", "temporada", "estado", "fecha"],
                name="idx_partido_liga_temp_est_fecha",
            ),
        ),
        migrations.AddIndex(
            model_name="partido",
            index=models.Index(
                fields=["equipo_local", "estado", "fecha"],
                name="idx_partido_local_estado_fecha",
            ),
        ),
        migrations.AddIndex(
            model_name="partido",
            index=models.Index(
                fields=["equipo_visitante", "estado", "fecha"],
                name="idx_partido_visit_est_fecha",
            ),
        ),
        migrations.AddIndex(
            model_name="tablaposicion",
            index=models.Index(
                fields=["liga", "temporada", "posicion"],
                name="idx_tabla_liga_temp_pos",
            ),
        ),
        migrations.AddIndex(
            model_name="goleadortemporada",
            index=models.Index(
                fields=["liga", "temporada", "posicion"],
                name="idx_goleador_liga_temp_pos",
            ),
        ),
    ]
