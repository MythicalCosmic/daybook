"""Companies made before default job titles existed and still without any get the usual
pharmacy set (apps.members.positions), in their own language. Companies with positions keep
theirs untouched."""

from django.db import migrations

# A copy of apps.members.positions.DEFAULT_POSITIONS as it was when this migration was written.
DEFAULT_POSITIONS = (
    ("Top manager", "Bosh menejer", "Топ-менеджер"),
    ("Manager", "Menejer", "Менеджер"),
    ("Department head", "Bo‘lim boshlig‘i", "Руководитель отдела"),
    ("Head of pharmacy", "Dorixona mudiri", "Заведующий аптекой"),
    ("Senior pharmacist", "Provizor", "Провизор"),
    ("Pharmacist", "Farmatsevt", "Фармацевт"),
    ("Cashier", "Kassir", "Кассир"),
    ("Stock manager", "Ombor mudiri", "Заведующий складом"),
    ("Stock worker", "Ombor xodimi", "Работник склада"),
    ("Courier", "Kuryer", "Курьер"),
    ("Accountant", "Buxgalter", "Бухгалтер"),
    ("Cleaner", "Farrosh", "Уборщик"),
)
LANGUAGES = ("en", "uz", "ru")


def add_positions(apps, schema_editor):
    Company = apps.get_model("companies", "Company")
    Position = apps.get_model("members", "Position")
    for company in Company.objects.exclude(pk__in=Position.objects.values("company_id")):
        column = (
            LANGUAGES.index(company.default_language)
            if company.default_language in LANGUAGES
            else 1
        )
        Position.objects.bulk_create(
            Position(company=company, name=names[column], order=index)
            for index, names in enumerate(DEFAULT_POSITIONS)
        )


class Migration(migrations.Migration):
    dependencies = [("members", "0011_join_link_deleted")]

    operations = [migrations.RunPython(add_positions, migrations.RunPython.noop)]
