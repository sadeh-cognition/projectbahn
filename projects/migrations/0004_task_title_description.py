from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0003_task"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="description",
            field=models.TextField(blank=True, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="task",
            name="title",
            field=models.CharField(default="Untitled task", max_length=255),
            preserve_default=False,
        ),
    ]
