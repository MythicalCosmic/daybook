"""Business goals (v11): "1.5 bln revenue this quarter, 2 new branches, staff turnover under
10 %", tracked from the company's own data.

A goal names a metric (`apps.goals.metrics`), a target and a period, optionally for one branch,
with a person who owns it. The metric's value is always computed from the books, sales, people,
attendance or training, never typed in. The last evaluation is kept on the goal (`value`,
`forecast`, `progress`, `state`) and a weekly beat adds a `GoalPoint` to its series.

Personal review goals belong to the people lifecycle (`apps.lifecycle`, `ReviewGoal`).
"""

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, Company, TenantModel
from apps.members.models import Membership


class Metric(models.TextChoices):
    REVENUE = "revenue", _("Revenue")
    GROSS_PROFIT = "gross_profit", _("Gross profit")
    NET_PROFIT = "net_profit", _("Net profit")
    MARGIN = "margin", _("Net margin")
    BRANCHES = "branches", _("Branches open")
    HEADCOUNT = "headcount", _("Headcount")
    TURNOVER = "turnover", _("Staff turnover")
    AVERAGE_CHECK = "average_check", _("Average check")
    LATE_ARRIVALS = "late_arrivals", _("Late arrivals")
    TRAINING = "training", _("Training completed")


class Goal(TenantModel):
    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        ACHIEVED = "achieved", _("Achieved")
        MISSED = "missed", _("Missed")
        ARCHIVED = "archived", _("Archived")

    class State(models.TextChoices):
        NOT_STARTED = "not_started", _("Not started")
        ON_TRACK = "on_track", _("On track")
        AT_RISK = "at_risk", _("At risk")
        OFF_TRACK = "off_track", _("Off track")
        ACHIEVED = "achieved", _("Achieved")
        MISSED = "missed", _("Missed")
        NO_DATA = "no_data", _("No data")

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="goals")
    title = models.CharField(max_length=200)
    metric = models.CharField(max_length=16, choices=Metric.choices)
    target = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text=_("In the metric's unit: so‘m, percent or a count."),
    )
    starts_on = models.DateField()
    ends_on = models.DateField()
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="goals",
        help_text=_("Empty: the whole company."),
    )
    owner = models.ForeignKey(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_goals",
        help_text=_("Who answers for it."),
    )
    note = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    # The last evaluation (`apps.goals.progress.evaluate`).
    state = models.CharField(max_length=12, choices=State.choices, default=State.NOT_STARTED)
    value = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    forecast = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    baseline = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Where a level metric (branches, headcount, training) stood on day one."),
    )
    progress = models.DecimalField(max_digits=7, decimal_places=1, null=True, blank=True)
    computed_at = models.DateTimeField(null=True, blank=True)
    # The state its last "at risk" note was sent for, so each turn for the worse is told once.
    notified_state = models.CharField(max_length=12, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["ends_on", "pk"]
        indexes = [models.Index(fields=["company", "status", "ends_on"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_on__gte=F("starts_on")), name="goals_goal_ends_after_start"
            ),
            models.CheckConstraint(condition=Q(target__gte=0), name="goals_goal_target_positive"),
        ]

    def __str__(self):
        return self.title


class GoalPoint(models.Model):
    """One point of a goal's series: its value, forecast and state on a day (the weekly beat)."""

    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="points")
    on = models.DateField()
    value = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    forecast = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    state = models.CharField(max_length=12, choices=Goal.State.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["on", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["goal", "on"], name="goals_unique_point_per_day"),
        ]

    def __str__(self):
        return f"{self.goal_id} {self.on}: {self.value}"
