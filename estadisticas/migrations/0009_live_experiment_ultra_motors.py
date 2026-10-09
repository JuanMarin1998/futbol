from django.db import migrations, models


ULTRA_MOTOR_CHOICES = [
    ("V1", "Motor V1"),
    ("V11", "Motor V1.1"),
    ("V12", "Motor V1.2"),
    ("V2", "Motor V2"),
    ("V21", "Motor V2.1"),
    ("V22", "Motor V2.2"),
    ("V3", "Motor V3"),
    ("V2U", "Motor V2.Ultra"),
    ("V11U", "Motor V1.1 Ultra"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("estadisticas", "0008_live_experiment_motor_v3"),
    ]

    operations = [
        migrations.AlterField(
            model_name="liveexperimententry",
            name="motor",
            field=models.CharField(choices=ULTRA_MOTOR_CHOICES, max_length=4),
        ),
        migrations.AlterField(
            model_name="liveexperimentsnapshot",
            name="motor",
            field=models.CharField(choices=ULTRA_MOTOR_CHOICES, max_length=4),
        ),
    ]
