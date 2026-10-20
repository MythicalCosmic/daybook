from django.db import models
from django.utils.translation import gettext_lazy as _


class Perm(models.TextChoices):
    """Every permission an access role can grant. Roles are per company; this list is fixed."""

    MEMBERS_VIEW = "members.view", _("View members")
    MEMBERS_APPROVE = "members.approve", _("Approve or reject join requests")
    MEMBERS_MANAGE = "members.manage", _("Edit and block members, change their roles")
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
