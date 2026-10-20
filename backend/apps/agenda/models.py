"""Models of the company calendar (docs/PLAN-OWNER.md §13.5).

The calendar page shows dates from many modules through `console.registry`'s calendar sources
(holidays and time off, birthdays, shifts, payroll dates…). This app owns the consumer of that
registry and the company's **own events**: meetings, trainings, inventory days, celebrations.

An event happens once or repeats weekly or monthly until a day. Its attendees answer whether
they're coming and get a bot reminder `remind_before` minutes before each occurrence.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, TenantModel
from apps.members.models import Membership


class Event(TenantModel):
    class Kind(models.TextChoices):
        MEETING = "meeting", _("Meeting")
        TRAINING = "training", _("Training")
        INVENTORY = "inventory", _("Inventory")
        CELEBRATION = "celebration", _("Celebration")
        DEADLINE = "deadline", _("Deadline")
        OTHER = "other", _("Other")

    class Visibility(models.TextChoices):
        COMPANY = "company", _("Everyone in the company")
        ATTENDEES = "attendees", _("Only the people invited")

    class Repeat(models.TextChoices):
        NONE = "none", _("Doesn't repeat")
        WEEKLY = "weekly", _("Every week")
        MONTHLY = "monthly", _("Every month")

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.MEETING)
    start = models.DateTimeField()
    end = models.DateTimeField(null=True, blank=True)
    all_day = models.BooleanField(
        default=False, help_text=_("All-day events use the company's calendar days.")
    )
    place = models.CharField(max_length=200, blank=True)
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=_("Where it happens. Empty: the whole company."),
    )
    visibility = models.CharField(
        max_length=10, choices=Visibility.choices, default=Visibility.COMPANY
    )
    attendees = models.ManyToManyField(
        Membership, through="EventAttendee", related_name="agenda_events", blank=True
    )
    remind_before = models.PositiveIntegerField(
        null=True,
        blank=True,
        default=60,
        help_text=_("Minutes before the start the attendees get a reminder. Empty: none."),
    )
    repeat = models.CharField(max_length=8, choices=Repeat.choices, default=Repeat.NONE)
    repeat_until = models.DateField(
        null=True, blank=True, help_text=_("The last day it may repeat on (company calendar).")
    )
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["start", "pk"]
        indexes = [
            models.Index(fields=["company", "start"]),
            models.Index(fields=["company", "cancelled_at", "repeat"]),
        ]

    def __str__(self):
        return self.title


class EventAttendee(TenantModel):
    class Response(models.TextChoices):
        PENDING = "pending", _("Not answered")
        GOING = "going", _("Going")
        DECLINED = "declined", _("Can't come")

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="invites")
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="agenda_invites"
    )
    response = models.CharField(max_length=10, choices=Response.choices, default=Response.PENDING)
    responded_at = models.DateTimeField(null=True, blank=True)
    reminded_for = models.DateTimeField(
        null=True, blank=True, help_text=_("The occurrence the last reminder was for.")
    )

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["event", "membership"], name="agenda_unique_attendee")
        ]


class AgendaSettings(models.Model):
    """The company's calendar settings (`conf.get_settings`)."""

    company = models.OneToOneField(
        "companies.Company", on_delete=models.CASCADE, related_name="agenda_settings"
    )
    default_remind_before = models.PositiveIntegerField(
        null=True, blank=True, default=60, help_text=_("The reminder new events start with.")
    )
    notify_invites = models.BooleanField(
        default=True, help_text=_("Tell people in Telegram when they're invited to an event.")
    )

    def __str__(self):
        return f"Calendar settings of {self.company_id}"
