# Persistencia independiente para el laboratorio de corredores virtuales.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("estadisticas", "0014_ecuabet_prematch_context")]

    operations = [
        migrations.CreateModel(
            name="BettingRunner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(max_length=40, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("strategy", models.CharField(max_length=40)),
                ("description", models.TextField(blank=True)),
                ("initial_lives", models.DecimalField(decimal_places=4, default=100, max_digits=12)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["id"], "verbose_name": "Corredor virtual", "verbose_name_plural": "Corredores virtuales"},
        ),
        migrations.CreateModel(
            name="BettingRunnerBet",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ecuabet_event_id", models.BigIntegerField(db_index=True)),
                ("home_team", models.CharField(max_length=180)),
                ("away_team", models.CharField(max_length=180)),
                ("market_key", models.CharField(max_length=80)),
                ("market", models.CharField(max_length=180)),
                ("selection", models.CharField(blank=True, max_length=150)),
                ("line", models.CharField(blank=True, max_length=40)),
                ("price", models.DecimalField(decimal_places=4, max_digits=10)),
                ("model_probability", models.FloatField()),
                ("confidence", models.FloatField(default=0)),
                ("edge", models.FloatField(default=0)),
                ("stake", models.DecimalField(decimal_places=4, max_digits=12)),
                ("potential_profit", models.DecimalField(decimal_places=4, max_digits=12)),
                ("status", models.CharField(choices=[("OPEN", "Abierta"), ("WON", "Ganada"), ("LOST", "Perdida"), ("CANCELLED", "Cancelada")], default="OPEN", max_length=12)),
                ("pnl", models.DecimalField(decimal_places=4, default=0, max_digits=12)),
                ("reason", models.TextField()),
                ("opportunity_snapshot", models.JSONField(blank=True, default=dict)),
                ("placed_minute", models.CharField(blank=True, max_length=30)),
                ("placed_home_score", models.IntegerField(blank=True, null=True)),
                ("placed_away_score", models.IntegerField(blank=True, null=True)),
                ("final_home_score", models.IntegerField(blank=True, null=True)),
                ("final_away_score", models.IntegerField(blank=True, null=True)),
                ("placed_at", models.DateTimeField(auto_now_add=True)),
                ("settled_at", models.DateTimeField(blank=True, null=True)),
                ("runner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="bets", to="estadisticas.bettingrunner")),
            ],
            options={"ordering": ["-placed_at"], "verbose_name": "Apuesta de corredor", "verbose_name_plural": "Apuestas de corredores"},
        ),
        migrations.CreateModel(
            name="BettingRunnerEvaluation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ecuabet_event_id", models.BigIntegerField()),
                ("home_team", models.CharField(max_length=180)),
                ("away_team", models.CharField(max_length=180)),
                ("action", models.CharField(default="WAIT", max_length=24)),
                ("reason", models.TextField(blank=True)),
                ("selected_market", models.CharField(blank=True, max_length=180)),
                ("evaluated_minute", models.CharField(blank=True, max_length=30)),
                ("evaluated_home_score", models.IntegerField(blank=True, null=True)),
                ("evaluated_away_score", models.IntegerField(blank=True, null=True)),
                ("snapshot", models.JSONField(blank=True, default=dict)),
                ("evaluated_at", models.DateTimeField(auto_now=True)),
                ("runner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="evaluations", to="estadisticas.bettingrunner")),
            ],
            options={"ordering": ["-evaluated_at"], "verbose_name": "Evaluación de corredor", "verbose_name_plural": "Evaluaciones de corredores"},
        ),
        migrations.AddConstraint(
            model_name="bettingrunnerbet",
            constraint=models.UniqueConstraint(fields=("runner", "ecuabet_event_id"), name="uniq_runner_one_bet_event"),
        ),
        migrations.AddIndex(
            model_name="bettingrunnerbet",
            index=models.Index(fields=["runner", "status", "placed_at"], name="runner_bet_status_date"),
        ),
        migrations.AddIndex(
            model_name="bettingrunnerbet",
            index=models.Index(fields=["ecuabet_event_id", "status"], name="runner_bet_event_status"),
        ),
        migrations.AddConstraint(
            model_name="bettingrunnerevaluation",
            constraint=models.UniqueConstraint(fields=("runner", "ecuabet_event_id"), name="uniq_runner_evaluation_event"),
        ),
        migrations.AddIndex(
            model_name="bettingrunnerevaluation",
            index=models.Index(fields=["runner", "-evaluated_at"], name="runner_eval_recent"),
        ),
    ]
