"""Default roles of companies made before Phase 2 get the Phase 2 permissions their definition
in `DEFAULT_ROLES` now lists (members/0005 created Accountant and Cashier and granted a few;
the Manager role still lacked sales, stock, attendance, projects, hiring and the rest).

A role counts as a default role by its name, the way `members.services.create_default_roles`
tells them apart; a renamed or custom role is the owner's own and stays as it is. Only adds,
never removes. The owner role holds every permission and needs none.
"""

from django.db import migrations

# Frozen copy of the Phase 2 permissions (every code after `announcements.send` in
# apps.members.permissions.Perm) that apps.members.permissions.DEFAULT_ROLES gives each
# default role at this time, in its order.
PHASE2_PERMISSIONS = {
    "Manager": [
        "dashboard.access",
        "branches.all",
        "sales.view",
        "sales.manage",
        "stock.manage",
        "finance.claim",
        "hr.view",
        "hr.hiring",
        "attendance.view",
        "attendance.manage",
        "payroll.propose",
        "projects.view_all",
        "projects.manage",
        "projects.time_view",
        "hr.discipline",
        "reviews.manage",
    ],
    "Accountant": [
        "dashboard.access",
        "audit.view",
        "data.export",
        "branches.all",
        "sales.view",
        "sales.invoices",
        "finance.view",
        "finance.record",
        "finance.manage",
        "finance.approve",
        "finance.claim",
        "hr.view",
        "hr.manage",
        "attendance.view",
        "time_off.manage",
        "payroll.view",
        "payroll.propose",
        "payroll.manage",
        "payroll.pay",
    ],
    "Cashier": ["sales.operate", "finance.claim"],
    "Employee": ["finance.claim"],
}


def grant_phase2_permissions(apps, schema_editor):
    AccessRole = apps.get_model("members", "AccessRole")
    roles = AccessRole.objects.filter(is_owner=False, name__in=PHASE2_PERMISSIONS)
    for role in roles.order_by("pk"):
        held = list(role.permissions)
        missing = [perm for perm in PHASE2_PERMISSIONS[role.name] if perm not in held]
        if missing:
            role.permissions = held + missing
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0007_membership_suspended_until"),
    ]

    operations = [
        migrations.RunPython(grant_phase2_permissions, migrations.RunPython.noop),
    ]
