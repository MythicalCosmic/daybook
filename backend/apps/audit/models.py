from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import TenantModel


class AuditLog(TenantModel):
    """Who did what in a company, for owners to look back on. Rows are never edited."""

    class Action(models.TextChoices):
        MEMBER_APPROVED = "member.approved", _("Approved a join request")
        MEMBER_REJECTED = "member.rejected", _("Rejected a join request")
        MEMBER_BLOCKED = "member.blocked", _("Blocked a member")
        MEMBER_LEFT = "member.left", _("Offboarded a member")
        TASK_ASSIGNED = "task.assigned", _("Gave a task")
        TASK_CHANGED = "task.changed", _("Changed a task")
        TASK_CONFIRMED = "task.confirmed", _("Accepted a task")
        TASK_RETURNED = "task.returned", _("Sent a task back")
        TASK_CANCELLED = "task.cancelled", _("Cancelled a task")
        TEMPLATE_CREATED = "template.created", _("Added a daily task")
        TEMPLATE_CHANGED = "template.changed", _("Changed a daily task")
        TEMPLATE_DELETED = "template.deleted", _("Deleted a daily task")
        POLICY_CREATED = "policy.created", _("Added reminder settings")
        POLICY_CHANGED = "policy.changed", _("Changed reminder settings")
        POLICY_DELETED = "policy.deleted", _("Deleted reminder settings")
        GROUP_CONNECTED = "group.connected", _("Connected a group")
        GROUP_CHANGED = "group.changed", _("Changed a group's settings")
        GROUP_DISCONNECTED = "group.disconnected", _("Disconnected a group")
        GROUP_REMOVED = "group.removed", _("Removed the bot from a group")
        TIME_OFF_APPROVED = "time_off.approved", _("Approved time off")
        TIME_OFF_REJECTED = "time_off.rejected", _("Rejected time off")
        ANNOUNCEMENT_SENT = "announcement.sent", _("Sent an announcement")
        ADMIN_CREATED = "admin.created", _("Added in the admin")
        ADMIN_CHANGED = "admin.changed", _("Changed in the admin")
        ADMIN_DELETED = "admin.deleted", _("Deleted in the admin")

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=_("Empty when the system did it."),
    )
    # Codes are registered per app (apps.audit.registry); Action holds the original ones.
    action = models.CharField(max_length=48)
    target_type = models.CharField(max_length=32)
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    target = models.CharField(max_length=255, help_text=_("Its name at the time."))
    details = models.JSONField(default=dict, blank=True)
    required_perm = models.CharField(
        max_length=32,
        blank=True,
        help_text=_("Only people holding this permission see the row (it touched secret fields)."),
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["company", "-created_at"])]

    def __str__(self):
        return f"{self.action_label}: {self.target}"

    @property
    def action_label(self) -> str:
        return str(dict(self.Action.choices).get(self.action, self.action))
