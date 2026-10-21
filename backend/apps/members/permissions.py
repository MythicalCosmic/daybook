from django.db import models
from django.utils.translation import gettext_lazy as _


class Perm(models.TextChoices):
    """Every permission an access role can grant. Roles are per company; this list is fixed.

    The bot, the mini app and the owner dashboard all read this one registry. Adding a code
    needs a migration of `AccessRole.permissions` (its choices).
    """

    MEMBERS_VIEW = "members.view", _("View members")
    MEMBERS_APPROVE = "members.approve", _("Approve or reject join requests")
    # Changing someone's role needs roles.manage.
    MEMBERS_MANAGE = "members.manage", _("Edit, block and offboard members")
    ROLES_MANAGE = "roles.manage", _("Manage access roles")
    POSITIONS_MANAGE = "positions.manage", _("Manage positions")
    TASKS_VIEW_ALL = "tasks.view_all", _("View everyone's tasks")
    TASKS_ASSIGN = "tasks.assign", _("Assign tasks to others")
    TASKS_TEMPLATES = "tasks.templates", _("Manage daily task templates")
    TASKS_CONFIRM = "tasks.confirm", _("Confirm completed tasks")
    REMINDERS_CONFIGURE = "reminders.configure", _("Configure reminders")
    GROUPS_MANAGE = "groups.manage", _("Connect and configure groups")
    REPORTS_VIEW = "reports.view", _("View reports and statistics")
    TIME_OFF_APPROVE = "time_off.approve", _("Approve or reject time off")
    ANNOUNCE = "announcements.send", _("Send announcements")

    # Owner console
    DASHBOARD_ACCESS = "dashboard.access", _("Open the owner dashboard")
    COMPANY_SETTINGS = "company.settings", _("Change company settings, branches and modules")
    AUDIT_VIEW = "audit.view", _("View the audit log")
    DATA_EXPORT = "data.export", _("Export data to Excel/CSV")
    BRANCHES_ALL = "branches.all", _("See every branch (otherwise only their own)")

    # Sales and stock
    SALES_VIEW = "sales.view", _("See sales, shifts, cash and stock")
    SALES_OPERATE = (
        "sales.operate",
        _("Run their own till: open and close shifts, record sales, payouts and handovers"),
    )
    SALES_MANAGE = (
        "sales.manage",
        _("Verify, correct and void shifts; registers, payment methods, targets, customers"),
    )
    SALES_INVOICES = "sales.invoices", _("Create, issue and void invoices")
    STOCK_MANAGE = (
        "stock.manage",
        _("Manage products, goods receipts, stock counts and write-offs (includes reading stock)"),
    )

    # Finance
    FINANCE_VIEW = "finance.view", _("See accounts, transactions, debts, profit and cost prices")
    FINANCE_RECORD = (
        "finance.record",
        _("Record income, expenses, transfers and payments on accounts they operate"),
    )
    FINANCE_MANAGE = (
        "finance.manage",
        _("Manage accounts, categories, budgets and rates; fix or void entries; lock periods"),
    )
    FINANCE_APPROVE = "finance.approve", _("Approve expense claims")
    FINANCE_CLAIM = "finance.claim", _("Submit their own expenses with receipts")

    # HR
    HR_VIEW = "hr.view", _("See profiles, documents and contracts (IDs and ID scans hidden)")
    HR_MANAGE = "hr.manage", _("Edit profiles, documents, contracts, policies and equipment")
    HR_SENSITIVE = (
        "hr.sensitive",
        _("See passport, PINFL and card numbers and ID scans (every view is audited)"),
    )
    HR_HIRING = "hr.hiring", _("Manage vacancies and applicants")

    # Attendance and leave
    ATTENDANCE_VIEW = "attendance.view", _("See everyone's attendance and the roster")
    ATTENDANCE_MANAGE = (
        "attendance.manage",
        _("Manage schedules and the roster; correct attendance; approve overtime and swaps"),
    )
    TIME_OFF_MANAGE = "time_off.manage", _("Manage leave types and adjust balances")

    # Payroll
    PAYROLL_VIEW = "payroll.view", _("See salaries, payslips and payroll reports")
    PAYROLL_PROPOSE = "payroll.propose", _("Propose bonuses and fines for others")
    PAYROLL_MANAGE = (
        "payroll.manage",
        _("Set pay, rules, approve adjustments and advances, calculate runs"),
    )
    PAYROLL_FINALIZE = "payroll.finalize", _("Finalize and publish payroll runs")
    PAYROLL_PAY = "payroll.pay", _("Mark payslips and advances paid")

    # AI
    AI_USE = "ai.use", _("Use the AI assistant, task drafts and writing help")
    AI_CONFIGURE = "ai.configure", _("Configure AI, its budget and what data it may see")

    # Projects
    PROJECTS_VIEW_ALL = "projects.view_all", _("See every project and its tasks")
    PROJECTS_MANAGE = "projects.manage", _("Create and manage projects")
    PROJECTS_TIME_VIEW = "projects.time_view", _("See everyone's time entries")

    # People lifecycle
    HR_DISCIPLINE = "hr.discipline", _("Issue warnings and reprimands")
    HR_SUSPEND = "hr.suspend", _("Suspend and reinstate employees")
    HR_TERMINATE = "hr.terminate", _("Terminate employment")
    ASSETS_MANAGE = "assets.manage", _("Manage equipment and who holds it")
    REVIEWS_MANAGE = "reviews.manage", _("Run performance reviews and set goals")

    # Knowledge base, calendar, CRM
    KNOWLEDGE_MANAGE = "knowledge.manage", _("Write and publish knowledge base pages")
    AGENDA_MANAGE = "agenda.manage", _("Add company events to the calendar")
    CRM_VIEW = "crm.view", _("See CRM deals")
    CRM_MANAGE = "crm.manage", _("Manage CRM deals and pipelines")


# The roles every new company starts with. Existing companies got theirs through migrations
# that only add (members/0005 creates Cashier and Accountant; members/0008 gives each role still
# named like one of these its Phase 2 permissions; members/0009 creates Pharmacist where the
# name is free). A permission added here later needs a migration of its own for existing
# companies (members/tests/test_phase2_role_migration.py, test_pharmacist_role_migration.py).
# Pharmacist is for a pharmacy's qualified staff, who sell at the counter and run its till
# (docs/PLAN-OWNER.md §14.3); W2.a adds `stock.operate` to it.
DEFAULT_ROLES = (
    {"name": "Owner", "is_owner": True},
    {
        "name": "Manager",
        "permissions": [
            Perm.MEMBERS_VIEW,
            Perm.MEMBERS_APPROVE,
            Perm.TASKS_VIEW_ALL,
            Perm.TASKS_ASSIGN,
            Perm.TASKS_TEMPLATES,
            Perm.TASKS_CONFIRM,
            Perm.GROUPS_MANAGE,
            Perm.REPORTS_VIEW,
            Perm.TIME_OFF_APPROVE,
            Perm.ANNOUNCE,
            Perm.DASHBOARD_ACCESS,
            Perm.BRANCHES_ALL,
            Perm.SALES_VIEW,
            Perm.SALES_MANAGE,
            Perm.STOCK_MANAGE,
            Perm.FINANCE_CLAIM,
            Perm.HR_VIEW,
            Perm.HR_HIRING,
            Perm.ATTENDANCE_VIEW,
            Perm.ATTENDANCE_MANAGE,
            Perm.PAYROLL_PROPOSE,
            Perm.PROJECTS_VIEW_ALL,
            Perm.PROJECTS_MANAGE,
            Perm.PROJECTS_TIME_VIEW,
            Perm.HR_DISCIPLINE,
            Perm.REVIEWS_MANAGE,
        ],
    },
    {
        "name": "Accountant",
        "permissions": [
            Perm.MEMBERS_VIEW,
            Perm.REPORTS_VIEW,
            Perm.DASHBOARD_ACCESS,
            Perm.AUDIT_VIEW,
            Perm.DATA_EXPORT,
            Perm.BRANCHES_ALL,
            Perm.SALES_VIEW,
            Perm.SALES_INVOICES,
            Perm.FINANCE_VIEW,
            Perm.FINANCE_RECORD,
            Perm.FINANCE_MANAGE,
            Perm.FINANCE_APPROVE,
            Perm.FINANCE_CLAIM,
            Perm.HR_VIEW,
            Perm.HR_MANAGE,
            Perm.ATTENDANCE_VIEW,
            Perm.TIME_OFF_MANAGE,
            Perm.PAYROLL_VIEW,
            Perm.PAYROLL_PROPOSE,
            Perm.PAYROLL_MANAGE,
            Perm.PAYROLL_PAY,
        ],
    },
    {"name": "Pharmacist", "permissions": [Perm.SALES_OPERATE, Perm.FINANCE_CLAIM]},
    {"name": "Cashier", "permissions": [Perm.SALES_OPERATE, Perm.FINANCE_CLAIM]},
    {"name": "Employee", "is_default": True, "permissions": [Perm.FINANCE_CLAIM]},
)
