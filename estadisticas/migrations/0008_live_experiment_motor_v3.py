from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("estadisticas", "0007_live_experiment_motor_variants"),
    ]

    operations = [
        migrations.AlterField(
            model_name="liveexperimententry",
            name="motor",
            field=models.CharField(
                choices=[
                    ("V1", "Motor V1"),
                    ("V11", "Motor V1.1"),
                    ("V12", "Motor V1.2"),
                    ("V2", "Motor V2"),
                    ("V21", "Motor V2.1"),
                    ("V22", "Motor V2.2"),
                    ("V3", "Motor V3"),
                ],
                max_length=3,
            ),
        ),
        migrations.AlterField(
            model_name="liveexperimentsnapshot",
            name="motor",
            field=models.CharField(
                choices=[
                    ("V1", "Motor V1"),
                    ("V11", "Motor V1.1"),
                    ("V12", "Motor V1.2"),
                    ("V2", "Motor V2"),
                    ("V21", "Motor V2.1"),
                    ("V22", "Motor V2.2"),
                    ("V3", "Motor V3"),
                ],
                max_length=3,
            ),
        ),
    ]
