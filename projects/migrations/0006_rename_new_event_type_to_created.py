from __future__ import annotations

from django.db import migrations, models


def rename_new_event_type_to_created(apps, schema_editor) -> None:
    EventLog = apps.get_model("projects", "EventLog")
    EventLog.objects.filter(event_type="new").update(event_type="created")


def rename_created_event_type_to_new(apps, schema_editor) -> None:
    EventLog = apps.get_model("projects", "EventLog")
    EventLog.objects.filter(event_type="created").update(event_type="new")


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0005_eventlog"),
    ]

    operations = [
        migrations.RunPython(
            rename_new_event_type_to_created,
            rename_created_event_type_to_new,
        ),
        migrations.AlterField(
            model_name="eventlog",
            name="event_type",
            field=models.CharField(
                choices=[("created", "created"), ("modified", "modified"), ("deleted", "deleted")],
                max_length=32,
            ),
        ),
    ]
