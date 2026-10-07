from django.db import migrations, models, deletion


class Migration(migrations.Migration):
    dependencies = [("estadisticas", "0003_partido_temporada_indices")]
    operations = [
        migrations.AddField(
            model_name="partido", name="ecuabet_event_id",
            field=models.BigIntegerField(blank=True, null=True, unique=True),
        ),
        migrations.CreateModel(
            name="Cuota1X2Snapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ecuabet_event_id", models.BigIntegerField()),
                ("odd_id_local", models.BigIntegerField(blank=True, null=True)),
                ("odd_id_empate", models.BigIntegerField(blank=True, null=True)),
                ("odd_id_visitante", models.BigIntegerField(blank=True, null=True)),
                ("cuota_local", models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True)),
                ("cuota_empate", models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True)),
                ("cuota_visitante", models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True)),
                ("es_live", models.BooleanField(default=False)),
                ("minuto", models.CharField(blank=True, max_length=20)),
                ("periodo", models.CharField(blank=True, max_length=50)),
                ("marcador_local", models.IntegerField(blank=True, null=True)),
                ("marcador_visitante", models.IntegerField(blank=True, null=True)),
                ("observado_en", models.DateTimeField(auto_now_add=True)),
                ("partido", models.ForeignKey(on_delete=deletion.CASCADE, related_name="cuotas_1x2", to="estadisticas.partido")),
            ],
            options={"verbose_name":"Snapshot de cuota 1X2","verbose_name_plural":"Snapshots de cuotas 1X2","ordering":["-observado_en"]},
        ),
        migrations.AddIndex(model_name="cuota1x2snapshot", index=models.Index(fields=["partido","-observado_en"], name="idx_cuota_part_obs")),
        migrations.AddIndex(model_name="cuota1x2snapshot", index=models.Index(fields=["ecuabet_event_id","-observado_en"], name="idx_cuota_event_obs")),
    ]
