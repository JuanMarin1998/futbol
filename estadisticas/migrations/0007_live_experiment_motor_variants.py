from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("estadisticas", "0006_live_experiment_daily_archive"),
    ]

    operations = [
        migrations.AlterField(
            model_name="liveexperimententry",
            name="motor",
            field=models.CharField(
                choices=[
                    ("V1", "Motor V1"),
                    ("V11", "Motor V1.1"),
                    ("V2", "Motor V2"),
                    ("V22", "Motor V2.2"),
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
                    ("V2", "Motor V2"),
                    ("V22", "Motor V2.2"),
                ],
                max_length=3,
            ),
        ),
    ]
