from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0006_rename_new_event_type_to_created"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectLLMConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(blank=True, max_length=255)),
                ("llm_name", models.CharField(blank=True, max_length=255)),
                ("api_key_hash", models.CharField(blank=True, max_length=255)),
                ("date_created", models.DateTimeField(auto_now_add=True)),
                ("date_updated", models.DateTimeField(auto_now=True)),
                (
                    "project",
                    models.OneToOneField(
                        on_delete=models.deletion.CASCADE,
                        related_name="llm_config",
                        to="projects.project",
                    ),
                ),
            ],
        ),
    ]
