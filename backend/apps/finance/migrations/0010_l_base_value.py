# The base calculation value is 440 000 so'm from 01.09.2026 (Decree UP-115 of 23.06.2026, item
# 3(b); apps.finance.tax_rules.BASE_VALUES). Companies still on the old default (412 000, Decree
# UP-91) move with it; a value someone typed stays.

from decimal import Decimal

from django.db import migrations

import apps.core.money

OLD = Decimal("412000")
NEW = Decimal("440000")


def forwards(apps, schema_editor):
    FinanceSettings = apps.get_model("finance", "FinanceSettings")
    FinanceSettings.objects.filter(base_value=OLD).update(base_value=NEW)


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0009_l_loans_taxes"),
    ]

    operations = [
        migrations.AlterField(
            model_name="financesettings",
            name="base_value",
            field=apps.core.money.MoneyField(
                default=Decimal("440000"),
                help_text="One base calculation value in so'm. Confirm with your accountant.",
            ),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
