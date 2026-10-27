from django.db import migrations


def create_defaults(apps, schema_editor):
    from core.models import DEFAULT_SETTINGS

    Setting = apps.get_model("core", "ApplicationSetting")
    for key, (label, value, vtype, description) in DEFAULT_SETTINGS.items():
        Setting.objects.get_or_create(
            key=key, defaults={"label": label, "value": value, "value_type": vtype, "description": description}
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(create_defaults, migrations.RunPython.noop)]
