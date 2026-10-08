from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("estadisticas", "0005_live_experiment"),
    ]

    operations = [
        migrations.CreateModel(
            name="LiveExperimentDailyArchive",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("experiment_date", models.DateField(unique=True)),
                ("saved_at", models.DateTimeField(auto_now=True)),
                ("experiment_count", models.PositiveIntegerField(default=0)),
                ("decision_count", models.PositiveIntegerField(default=0)),
                ("motors_summary", models.JSONField(blank=True, default=dict)),
                ("experiments_data", models.JSONField(blank=True, default=list)),
            ],
            options={
                "verbose_name": "Archivo diario de experimento LIVE",
                "verbose_name_plural": "Archivos diarios de experimento LIVE",
                "ordering": ["-experiment_date"],
            },
        ),
    ]
