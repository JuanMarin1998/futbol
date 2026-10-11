# Generated for the independent match-behavior laboratory.
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("estadisticas", "0012_vpro11_motor")]

    operations = [
        migrations.CreateModel(
            name="MatchBehaviorSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ecuabet_event_id", models.BigIntegerField(db_index=True)),
                ("flashscore_event_id", models.CharField(blank=True, db_index=True, max_length=100)),
                ("home_team", models.CharField(max_length=180)),
                ("away_team", models.CharField(max_length=180)),
                ("league", models.CharField(blank=True, max_length=180)),
                ("minute", models.CharField(blank=True, max_length=40)),
                ("minute_number", models.IntegerField(blank=True, null=True)),
                ("period", models.CharField(blank=True, max_length=40)),
                ("home_score", models.IntegerField(blank=True, null=True)),
                ("away_score", models.IntegerField(blank=True, null=True)),
                ("status", models.CharField(blank=True, max_length=40)),
                ("performance", models.JSONField(blank=True, default=dict)),
                ("odds", models.JSONField(blank=True, default=list)),
                ("fingerprint", models.CharField(db_index=True, max_length=64)),
                ("observed_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
            ],
            options={"ordering": ["-observed_at"]},
        ),
        migrations.AddIndex(
            model_name="matchbehaviorsnapshot",
            index=models.Index(fields=["ecuabet_event_id", "observed_at"], name="patron_evento_fecha"),
        ),
        migrations.AddIndex(
            model_name="matchbehaviorsnapshot",
            index=models.Index(fields=["home_team", "observed_at"], name="patron_local_fecha"),
        ),
        migrations.AddIndex(
            model_name="matchbehaviorsnapshot",
            index=models.Index(fields=["away_team", "observed_at"], name="patron_visita_fecha"),
        ),
        migrations.CreateModel(
            name="TeamBehaviorProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("team_key", models.CharField(max_length=220, unique=True)),
                ("team_name", models.CharField(max_length=180)),
                ("snapshots_count", models.PositiveIntegerField(default=0)),
                ("matches_observed", models.PositiveIntegerField(default=0)),
                ("last_seen", models.DateTimeField(blank=True, null=True)),
                ("behavior", models.JSONField(blank=True, default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-snapshots_count", "team_name"], "verbose_name": "Perfil de comportamiento de equipo", "verbose_name_plural": "Perfiles de comportamiento de equipos"},
        ),
    ]
