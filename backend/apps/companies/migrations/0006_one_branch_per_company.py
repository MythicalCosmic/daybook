from django.db import migrations


def add_the_first_branch(apps, schema_editor):
    """Every existing company gets one branch, named after it (new companies get theirs from
    companies.services.setup_company)."""
    Company = apps.get_model("companies", "Company")
    Branch = apps.get_model("companies", "Branch")
    Branch.objects.bulk_create(
        Branch(company_id=company.pk, name=company.name[:100])
        for company in Company.objects.filter(branches__isnull=True).order_by("pk")
    )


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0005_company_owner_console_branch"),
    ]

    operations = [
        migrations.RunPython(add_the_first_branch, migrations.RunPython.noop),
    ]
