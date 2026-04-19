from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0004_task_title_description"),
    ]

    operations = [
        migrations.CreateModel(
            name="EventLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "entity_type",
                    models.CharField(
                        choices=[("Project", "Project"), ("Feature", "Feature"), ("Task", "Task")],
                        max_length=32,
                    ),
                ),
                ("entity_id", models.PositiveBigIntegerField()),
                (
                    "event_type",
                    models.CharField(
                        choices=[("new", "new"), ("modified", "modified"), ("deleted", "deleted")],
                        max_length=32,
                    ),
                ),
                ("event_details", models.JSONField(default=dict)),
            ],
        ),
    ]
