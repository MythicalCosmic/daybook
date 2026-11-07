"""Models of recognition: points, levels, badges, streaks, kudos (docs/PLAN-LEARNING.md §7).

People earn **points** for what they learn (lessons, quizzes, courses, the daily question) and
for tasks done on time and kudos received; every award is one row of the ledger with a key
that makes it happen once. Their **level** follows from their total (a table in code).
**Badges** are awarded once per person (and per topic or month where the badge says so).
A **streak** is the run of workdays with something learned; days off and leave don't break it.
**Kudos** are thanks from a colleague, with a badge and a note (§3.16 of PLAN-OWNER).

Module switch `recognition` (`Company.features`): while it is off nothing is awarded or shown.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company, TenantModel
from apps.members.models import Membership


class RecognitionSettings(models.Model):
    """The company's recognition settings. Lazy: `apps.recognition.conf.get_settings(company)`."""

    class Scope(models.TextChoices):
        COMPANY = "company", _("The whole company")
        BRANCH = "branch", _("Their branch")

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="recognition_settings"
    )
    points_enabled = models.BooleanField(default=True)
    leaderboard_for_staff = models.BooleanField(
        default=True, help_text=_("Staff see the leaderboard: the top ten and their own place.")
    )
    leaderboard_scope = models.CharField(max_length=8, choices=Scope.choices, default=Scope.COMPANY)
    task_points = models.BooleanField(
        default=True, help_text=_("Tasks done on time earn points too.")
    )
    kudos_enabled = models.BooleanField(default=True)
    kudos_per_day = models.PositiveSmallIntegerField(default=3)
    post_kudos_to_groups = models.BooleanField(default=False)
    points_table = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Points per reason, where they differ from the defaults."),
    )

    def __str__(self):
        return f"Recognition settings of {self.company_id}"


class PointsEntry(TenantModel):
    """Points `membership` got (or lost, for a correction) for one thing. `key` names the thing
    ("quiz:attempt:12", "task:345"), so awarding it again does nothing."""

    class Reason(models.TextChoices):
        LESSON = "lesson", _("Lesson watched")
        PAGE = "page", _("Page read")
        QUIZ = "quiz", _("Quiz passed")
        QUIZ_PERFECT = "quiz_perfect", _("Perfect score")
        COURSE = "course", _("Course finished")
        DAILY = "daily", _("Question of the day")
        CHECK = "check", _("Regular check")
        STREAK = "streak", _("Streak")
        BADGE = "badge", _("Badge")
        KUDOS = "kudos", _("Kudos received")
        TASK = "task", _("Task done on time")
        ADJUST = "adjust", _("Correction")

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="points")
    points = models.SmallIntegerField()
    reason = models.CharField(max_length=16, choices=Reason.choices)
    key = models.CharField(max_length=80)
    at = models.DateTimeField()
    note = models.CharField(max_length=200, blank=True)
    by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-at"]
        constraints = [
            models.UniqueConstraint(fields=["company", "key"], name="recognition_unique_points_key")
        ]
        indexes = [
            models.Index(fields=["company", "-at"]),
            models.Index(fields=["membership", "-at"]),
        ]


class BadgeAward(TenantModel):
    """A badge of the catalogue (`apps.recognition.badges`) `membership` earned. `ref` tells
    badges that can come more than once apart (a topic id, a month "2026-11")."""

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="badges")
    badge = models.CharField(max_length=32)
    ref = models.CharField(max_length=32, blank=True)
    awarded_at = models.DateTimeField()
    seen_at = models.DateTimeField(
        null=True, blank=True, help_text=_("When the person saw the celebration in the app.")
    )

    class Meta:
        ordering = ["-awarded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "badge", "ref"], name="recognition_unique_badge"
            )
        ]


class Streak(TenantModel):
    """`membership`'s run of days of one kind ("learning"): the current run, the best one and
    the last day that counted (the company's date)."""

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="streaks")
    kind = models.CharField(max_length=16, default="learning")
    current = models.PositiveSmallIntegerField(default=0)
    best = models.PositiveSmallIntegerField(default=0)
    last_day = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["membership", "kind"], name="recognition_unique_streak")
        ]


class Kudos(TenantModel):
    """Thanks from one colleague to another, with a badge and a short note."""

    class Badge(models.TextChoices):
        THANKS = "thanks", _("Thank you")
        TEAMWORK = "teamwork", _("Great teamwork")
        FAST = "fast", _("Quick help")
        CAREFUL = "careful", _("Careful work")
        HELPFUL = "helpful", _("Helped a customer")
        STAR = "star", _("Star of the day")

    from_member = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="kudos_given"
    )
    to_member = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="kudos_received"
    )
    badge = models.CharField(max_length=16, choices=Badge.choices, default=Badge.THANKS)
    message = models.CharField(max_length=200, blank=True)
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    hidden_at = models.DateTimeField(null=True, blank=True)
    hidden_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(from_member=F("to_member")), name="recognition_no_self_kudos"
            )
        ]
        indexes = [
            models.Index(fields=["company", "to_member", "-created_at"]),
            models.Index(fields=["company", "-created_at"]),
        ]
