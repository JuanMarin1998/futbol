from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("estadisticas", "0004_ecuabet_1x2"),
    ]

    operations = [
        migrations.CreateModel(
            name="LiveExperiment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ecuabet_event_id", models.BigIntegerField(db_index=True)),
                ("flashscore_event_id", models.CharField(blank=True, max_length=80)),
                ("home_team", models.CharField(max_length=150)),
                ("away_team", models.CharField(max_length=150)),
                ("status", models.CharField(choices=[("RUNNING", "Ejecutando"), ("STOPPED", "Detenido"), ("FINISHED", "Finalizado")], default="RUNNING", max_length=12)),
                ("initial_lives", models.DecimalField(decimal_places=4, default=100, max_digits=12)),
                ("v1_lives", models.DecimalField(decimal_places=4, default=100, max_digits=12)),
                ("v2_lives", models.DecimalField(decimal_places=4, default=100, max_digits=12)),
                ("v1_max_lives", models.DecimalField(decimal_places=4, default=100, max_digits=12)),
                ("v2_max_lives", models.DecimalField(decimal_places=4, default=100, max_digits=12)),
                ("v1_min_lives", models.DecimalField(decimal_places=4, default=100, max_digits=12)),
                ("v2_min_lives", models.DecimalField(decimal_places=4, default=100, max_digits=12)),
                ("v1_wins", models.PositiveIntegerField(default=0)),
                ("v1_losses", models.PositiveIntegerField(default=0)),
                ("v2_wins", models.PositiveIntegerField(default=0)),
                ("v2_losses", models.PositiveIntegerField(default=0)),
                ("last_minute", models.CharField(blank=True, max_length=30)),
                ("last_period", models.CharField(blank=True, max_length=60)),
                ("last_home_score", models.IntegerField(blank=True, null=True)),
                ("last_away_score", models.IntegerField(blank=True, null=True)),
                ("final_home_score", models.IntegerField(blank=True, null=True)),
                ("final_away_score", models.IntegerField(blank=True, null=True)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("stopped_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Experimento LIVE",
                "verbose_name_plural": "Experimentos LIVE",
                "ordering": ["-started_at"],
                "indexes": [
                    models.Index(fields=["ecuabet_event_id", "status"], name="idx_live_exp_event_status"),
                ],
            },
        ),
        migrations.CreateModel(
            name="LiveExperimentEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("motor", models.CharField(choices=[("V1", "Motor V1"), ("V2", "Motor V2")], max_length=2)),
                ("opportunity_key", models.CharField(max_length=255)),
                ("market", models.CharField(blank=True, max_length=150)),
                ("selection", models.CharField(max_length=150)),
                ("line", models.CharField(blank=True, max_length=80)),
                ("price", models.DecimalField(decimal_places=4, max_digits=10)),
                ("model_probability", models.FloatField()),
                ("implied_probability", models.FloatField()),
                ("edge", models.FloatField()),
                ("level", models.PositiveSmallIntegerField()),
                ("level_name", models.CharField(max_length=40)),
                ("stake", models.DecimalField(decimal_places=4, max_digits=12)),
                ("potential_profit", models.DecimalField(decimal_places=4, max_digits=12)),
                ("reason", models.TextField()),
                ("supporting_factors", models.JSONField(blank=True, default=list)),
                ("contradicting_factors", models.JSONField(blank=True, default=list)),
                ("opportunity_snapshot", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("OPEN", "Abierta"), ("WON", "Ganada"), ("LOST", "Perdida"), ("CANCELLED", "Cancelada")], default="OPEN", max_length=12)),
                ("pnl", models.DecimalField(decimal_places=4, default=0, max_digits=12)),
                ("placed_minute", models.CharField(blank=True, max_length=30)),
                ("placed_home_score", models.IntegerField(blank=True, null=True)),
                ("placed_away_score", models.IntegerField(blank=True, null=True)),
                ("placed_at", models.DateTimeField(auto_now_add=True)),
                ("settled_at", models.DateTimeField(blank=True, null=True)),
                ("experiment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entries", to="estadisticas.liveexperiment")),
            ],
            options={
                "verbose_name": "Entrada de experimento",
                "verbose_name_plural": "Entradas de experimento",
                "ordering": ["-placed_at"],
                "indexes": [
                    models.Index(fields=["experiment", "motor", "status"], name="idx_live_exp_entry_motor"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=["experiment", "motor", "opportunity_key"], name="uniq_live_exp_motor_opportunity"),
                ],
            },
        ),
        migrations.CreateModel(
            name="LiveExperimentSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("motor", models.CharField(choices=[("V1", "Motor V1"), ("V2", "Motor V2")], max_length=2)),
                ("minute", models.CharField(blank=True, max_length=30)),
                ("period", models.CharField(blank=True, max_length=60)),
                ("home_score", models.IntegerField(blank=True, null=True)),
                ("away_score", models.IntegerField(blank=True, null=True)),
                ("lives_before", models.DecimalField(decimal_places=4, max_digits=12)),
                ("lives_after", models.DecimalField(decimal_places=4, max_digits=12)),
                ("selected_opportunity", models.JSONField(blank=True, null=True)),
                ("all_opportunities", models.JSONField(blank=True, default=list)),
                ("decision_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("experiment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="snapshots", to="estadisticas.liveexperiment")),
            ],
            options={
                "verbose_name": "Snapshot de experimento",
                "verbose_name_plural": "Snapshots de experimento",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["experiment", "motor", "-created_at"], name="idx_live_exp_snap_motor"),
                ],
            },
        ),
    ]
