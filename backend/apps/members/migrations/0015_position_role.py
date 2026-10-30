"""A job title gives a role. Companies made before this get the usual ones: each default title
(in any of its three languages) gives the default role it names, when the company still has a
role of that name. Nobody's own role changes."""

import django.db.models.deletion
from django.db import migrations, models

# Frozen copies of positions.DEFAULT_POSITIONS and DEFAULT_TITLE_ROLES at this migration.
TITLES = (
    (("Top manager", "Bosh menejer", "Топ-менеджер"), "Manager"),
    (("Manager", "Menejer", "Менеджер"), "Manager"),
    (("Senior pharmacist", "Provizor", "Провизор"), "Pharmacist"),
    (("Pharmacist", "Farmatsevt", "Фармацевт"), "Pharmacist"),
    (("Cashier", "Kassir", "Кассир"), "Cashier"),
    (("Accountant", "Buxgalter", "Бухгалтер"), "Accountant"),
)


def give_default_roles(apps, schema_editor):
    Position = apps.get_model("members", "Position")
    AccessRole = apps.get_model("members", "AccessRole")
    role_for_title = {title.casefold(): role for titles, role in TITLES for title in titles}
    roles = {
        (role.company_id, role.name): role
        for role in AccessRole.objects.filter(is_owner=False, name__in={role for _, role in TITLES})
    }
    for position in Position.objects.filter(role__isnull=True):
        name = role_for_title.get(position.name.strip().casefold())
        role = roles.get((position.company_id, name)) if name else None
        if role is not None:
            position.role = role
            position.save(update_fields=["role"])


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0014_seat_heads"),
    ]

    operations = [
        migrations.AddField(
            model_name="position",
            name="role",
            field=models.ForeignKey(
                blank=True,
                help_text="The access people with this job title get. Empty: the default role.",
                null=True,
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="positions",
                to="members.accessrole",
            ),
        ),
        migrations.RunPython(give_default_roles, migrations.RunPython.noop),
    ]
