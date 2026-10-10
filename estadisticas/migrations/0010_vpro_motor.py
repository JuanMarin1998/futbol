from django.db import migrations, models


MOTOR_CHOICES = [
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
    ("VPRO", "V.Pro · Favorito estadístico"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("estadisticas", "0009_live_experiment_spy"),
        ("estadisticas", "0009_live_experiment_ultra_motors"),
    ]

    operations = [
        migrations.AddField(
            model_name="liveexperiment",
            name="vpro_reference_odds",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name="liveexperimententry",
            name="motor",
            field=models.CharField(choices=MOTOR_CHOICES, max_length=4),
        ),
        migrations.AlterField(
            model_name="liveexperimentsnapshot",
            name="motor",
            field=models.CharField(choices=MOTOR_CHOICES, max_length=4),
        ),
    ]
