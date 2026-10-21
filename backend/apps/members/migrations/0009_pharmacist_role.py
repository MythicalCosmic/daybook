"""Every existing company gets the Pharmacist role that `DEFAULT_ROLES` gives new ones
(docs/PLAN-OWNER.md §14.3): a pharmacy's qualified staff sell at the counter and run its till.

Made only where no role has that name yet, so an owner's own "Pharmacist" stays as it is.
Nothing else changes and nothing is removed. W2.a adds `stock.operate` to it.
"""

from django.db import migrations

# Frozen copy of the Pharmacist role in apps.members.permissions.DEFAULT_ROLES at this time.
NAME = "Pharmacist"
PERMISSIONS = ["sales.operate", "finance.claim"]


def create_pharmacist_role(apps, schema_editor):
    AccessRole = apps.get_model("members", "AccessRole")
    Company = apps.get_model("companies", "Company")
    taken = set(AccessRole.objects.filter(name=NAME).values_list("company_id", flat=True))
    AccessRole.objects.bulk_create(
        AccessRole(company_id=company_id, name=NAME, permissions=list(PERMISSIONS))
        for company_id in Company.objects.order_by("pk").values_list("pk", flat=True)
        if company_id not in taken
    )


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0008_phase2_default_role_permissions"),
    ]

    operations = [
        migrations.RunPython(create_pharmacist_role, migrations.RunPython.noop),
    ]
