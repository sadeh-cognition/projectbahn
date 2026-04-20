from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0008_projectllmconfig_encrypted_api_key_featurechatmessage_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            DROP TABLE IF EXISTS projects_featurechatmessage;
            DROP TABLE IF EXISTS projects_featurechatthread;
            DROP TABLE IF EXISTS projects_projectllmconfig;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
