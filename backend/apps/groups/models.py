from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, TenantModel, TenantQuerySet
from apps.members.models import Membership, Position


class GroupEvent(models.TextChoices):
    DAILY_DONE = "daily_done", _("Daily tasks done")
    TASKS_DONE = "tasks_done", _("Assigned tasks done")
    LATE = "late", _("Late tasks")
    MEMBERS = "members", _("New people")
    MORNING = "morning", _("Morning plan")
    EVENING = "evening", _("End-of-day summary")
    ATTENDANCE = "attendance", _("Check-ins and lateness")
    SHIFTS = "shifts", _("Shift changes")
    CASH = "cash", _("Cash and handovers")
    SALES = "sales", _("Sales")
    CELEBRATIONS = "celebrations", _("Birthdays and work anniversaries")
    KUDOS = "kudos", _("Kudos")


# What a freshly connected group gets until someone changes it.
DEFAULT_EVENTS = [GroupEvent.DAILY_DONE, GroupEvent.LATE, GroupEvent.EVENING]

# Events that only exist once their module is switched on (Company.features).
EVENT_FEATURES = {
    GroupEvent.ATTENDANCE: "attendance",
    GroupEvent.SHIFTS: "attendance",
    GroupEvent.CASH: "sales",
    GroupEvent.SALES: "sales",
    GroupEvent.CELEBRATIONS: "hr",
    GroupEvent.KUDOS: "recognition",
}


def available_events(company, chosen=()) -> list[GroupEvent]:
    """The events a group of `company` can post: the task events, plus each module's once it's
    on. Events already `chosen` stay listed, so they can still be turned off."""
    return [
        event
        for event in GroupEvent
        if event in chosen
        or event not in EVENT_FEATURES
        or company.has_feature(EVENT_FEATURES[event])
    ]


class TelegramGroupQuerySet(TenantQuerySet):
    def move_chat(self, old_chat_id: int, new_chat_id: int) -> None:
        """A group upgraded to a supergroup gets a new id; keep its settings under that id."""
        with transaction.atomic():
            group = self.select_for_update().filter(chat_id=old_chat_id).first()
            if group is None:
                return
            # The bot may have been linked to the new id already; the old settings win.
            self.filter(chat_id=new_chat_id).exclude(pk=group.pk).delete()
            group.chat_id = new_chat_id
            group.save(update_fields=["chat_id", "updated_at"])


class TelegramGroup(TenantModel):
    """A Telegram group the bot posts company news to."""

    chat_id = models.BigIntegerField(unique=True)
    title = models.CharField(max_length=255, blank=True)
    events = ArrayField(
        models.CharField(max_length=16, choices=GroupEvent.choices), default=list, blank=True
    )
    positions = models.ManyToManyField(
        Position,
        blank=True,
        related_name="+",
        help_text=_("Only news about people in these positions. None = everyone."),
    )
    branches = models.ManyToManyField(
        Branch,
        blank=True,
        related_name="telegram_groups",
        help_text=_("Only news from these branches. None = every branch."),
    )
    linked_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Posts are spaced out so a busy group stays under Telegram's limit.
    next_post_at = models.DateTimeField(null=True, blank=True, editable=False)
    is_active = models.BooleanField(
        default=True, help_text=_("Off once the bot is removed or the group is disconnected.")
    )

    objects = TelegramGroupQuerySet.as_manager()

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title or str(self.chat_id)


class GroupReport(models.Model):
    """A daily report a group already got, so each one goes out once a day."""

    group = models.ForeignKey(TelegramGroup, on_delete=models.CASCADE, related_name="reports")
    kind = models.CharField(
        max_length=16,
        choices=[(event.value, event.label) for event in (GroupEvent.MORNING, GroupEvent.EVENING)],
    )
    day = models.DateField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group", "kind", "day"], name="one_report_per_day"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.day} → {self.group}"
