"""Stock permissions for pharmacies (docs/PLAN-OWNER.md §14.5, W2.a).

Two new codes: `stock.operate` (look up stock, count, receive goods for checking, expiry checks
and defektura) and `stock.controlled` (the controlled-substance register and the prescription
log). Every role that runs a till (`sales.operate`) gains `stock.operate`, and a Pharmacist role
is made wherever the name is still free. Nothing is removed and no other role changes.
"""

import django.contrib.postgres.fields
from django.db import migrations, models

# Frozen copies of the codes and of the Pharmacist role in DEFAULT_ROLES at this time.
TILL = "sales.operate"
STOCK = "stock.operate"
NAME = "Pharmacist"
PERMISSIONS = ["sales.operate", "stock.operate", "finance.claim"]


def give_stock_operate(apps, schema_editor):
    AccessRole = apps.get_model("members", "AccessRole")
    Company = apps.get_model("companies", "Company")
    for role in AccessRole.objects.filter(permissions__contains=[TILL]).exclude(
        permissions__contains=[STOCK]
    ):
        role.permissions = [*role.permissions, STOCK]
        role.save(update_fields=["permissions"])
    taken = set(AccessRole.objects.filter(name=NAME).values_list("company_id", flat=True))
    AccessRole.objects.bulk_create(
        AccessRole(company_id=company_id, name=NAME, permissions=list(PERMISSIONS))
        for company_id in Company.objects.order_by("pk").values_list("pk", flat=True)
        if company_id not in taken
    )


class Migration(migrations.Migration):

    dependencies = [
        ('members', '0015_position_role'),
    ]

    operations = [
        migrations.AlterField(
            model_name='accessrole',
            name='permissions',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(choices=[('members.view', 'View members'), ('members.approve', 'Approve or reject join requests'), ('members.manage', 'Edit, block and offboard members'), ('roles.manage', 'Manage access roles'), ('positions.manage', 'Manage positions'), ('tasks.view_all', "View everyone's tasks"), ('tasks.assign', 'Assign tasks to others'), ('tasks.templates', 'Manage daily task templates'), ('tasks.confirm', 'Confirm completed tasks'), ('reminders.configure', 'Configure reminders'), ('groups.manage', 'Connect and configure groups'), ('reports.view', 'View reports and statistics'), ('time_off.approve', 'Approve or reject time off'), ('announcements.send', 'Send announcements'), ('dashboard.access', 'Open the owner dashboard'), ('company.settings', 'Change company settings, branches and modules'), ('audit.view', 'View the audit log'), ('data.export', 'Export data to Excel/CSV'), ('branches.all', 'See every branch (otherwise only their own)'), ('sales.view', 'See sales, shifts, cash and stock'), ('sales.operate', 'Run their own till: open and close shifts, record sales, payouts and handovers'), ('sales.manage', 'Verify, correct and void shifts; registers, payment methods, targets, customers'), ('sales.invoices', 'Create, issue and void invoices'), ('stock.manage', 'Manage products, goods receipts, stock counts and write-offs (includes reading stock)'), ('stock.operate', 'Look up stock, count, receive goods for checking, record expiry checks and defektura'), ('stock.controlled', 'Keep the controlled-substance register and the prescription log'), ('finance.view', 'See accounts, transactions, debts, profit and cost prices'), ('finance.record', 'Record income, expenses, transfers and payments on accounts they operate'), ('finance.manage', 'Manage accounts, categories, budgets and rates; fix or void entries; lock periods'), ('finance.approve', 'Approve expense claims'), ('finance.claim', 'Submit their own expenses with receipts'), ('hr.view', 'See profiles, documents and contracts (IDs and ID scans hidden)'), ('hr.manage', 'Edit profiles, documents, contracts, policies and equipment'), ('hr.sensitive', 'See passport, PINFL and card numbers and ID scans (every view is audited)'), ('hr.hiring', 'Manage vacancies and applicants'), ('attendance.view', "See everyone's attendance and the roster"), ('attendance.manage', 'Manage schedules and the roster; correct attendance; approve overtime and swaps'), ('time_off.manage', 'Manage leave types and adjust balances'), ('payroll.view', 'See salaries, payslips and payroll reports'), ('payroll.propose', 'Propose bonuses and fines for others'), ('payroll.manage', 'Set pay, rules, approve adjustments and advances, calculate runs'), ('payroll.finalize', 'Finalize and publish payroll runs'), ('payroll.pay', 'Mark payslips and advances paid'), ('ai.use', 'Use the AI assistant, task drafts and writing help'), ('ai.configure', 'Configure AI, its budget and what data it may see'), ('projects.view_all', 'See every project and its tasks'), ('projects.manage', 'Create and manage projects'), ('projects.time_view', "See everyone's time entries"), ('hr.discipline', 'Issue warnings and reprimands'), ('hr.suspend', 'Suspend and reinstate employees'), ('hr.terminate', 'Terminate employment'), ('assets.manage', 'Manage equipment and who holds it'), ('reviews.manage', 'Run performance reviews and set goals'), ('knowledge.manage', 'Write and publish knowledge base pages'), ('agenda.manage', 'Add company events to the calendar'), ('crm.view', 'See CRM deals'), ('crm.manage', 'Manage CRM deals and pipelines')], max_length=64), blank=True, default=list),
        ),
        migrations.RunPython(give_stock_operate, migrations.RunPython.noop),
    ]
