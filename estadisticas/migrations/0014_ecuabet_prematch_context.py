# Persistencia de las fichas previas de Ecuabet.
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("estadisticas", "0013_laboratorio_patrones")]

    operations = [
        migrations.CreateModel(
            name="EcuabetPreMatchContext",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ecuabet_event_id", models.BigIntegerField(unique=True)),
                ("match_name", models.CharField(max_length=250)),
                ("home_team", models.CharField(blank=True, max_length=180)),
                ("away_team", models.CharField(blank=True, max_length=180)),
                ("championship", models.CharField(blank=True, max_length=180)),
                ("match_date", models.DateField(db_index=True)),
                ("kickoff", models.DateTimeField(blank=True, null=True)),
                ("home_odds", models.FloatField(blank=True, null=True)),
                ("draw_odds", models.FloatField(blank=True, null=True)),
                ("away_odds", models.FloatField(blank=True, null=True)),
                ("favorite", models.CharField(blank=True, max_length=180)),
                ("status", models.CharField(blank=True, max_length=100)),
                ("explanation", models.TextField(blank=True)),
                ("source", models.CharField(default="Ecuabet · mercado 1X2", max_length=100)),
                ("captured_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("raw_context", models.JSONField(blank=True, default=dict)),
            ],
            options={"ordering": ["match_date", "kickoff", "match_name"]},
        ),
        migrations.AddIndex(
            model_name="ecuabetprematchcontext",
            index=models.Index(fields=["match_date", "kickoff"], name="ecuabet_ctx_date_kick"),
        ),
    ]
