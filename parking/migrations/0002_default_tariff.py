from decimal import Decimal

from django.db import migrations


def create_default_tariff(apps, schema_editor):
    tariff_model = apps.get_model("parking", "ParkingTariff")
    if not tariff_model.objects.using(schema_editor.connection.alias).filter(is_active=True).exists():
        tariff_model.objects.using(schema_editor.connection.alias).create(
            name="Базовий тариф",
            hourly_rate=Decimal("50.00"),
            alert_limit=Decimal("500.00"),
            is_active=True,
        )


class Migration(migrations.Migration):
    dependencies = [("parking", "0001_initial")]

    operations = [
        migrations.RunPython(create_default_tariff, migrations.RunPython.noop),
    ]
