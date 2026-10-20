from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, TenantModel
from apps.members.permissions import Perm


class AccessRole(TenantModel):
    """A named bundle of permissions. Only owners assign roles; employees never pick them."""

    name = models.CharField(max_length=100)
    permissions = ArrayField(
        models.CharField(max_length=64, choices=Perm.choices), default=list, blank=True
    )
    is_owner = models.BooleanField(default=False, help_text=_("Owners have every permission."))
    is_default = models.BooleanField(
        default=False, help_text=_("Given to new members when they are approved.")
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="unique_role_name_per_company"
            ),
            models.UniqueConstraint(
                fields=["company"],
                condition=Q(is_default=True),
                name="one_default_role_per_company",
            ),
        ]

    def __str__(self):
        return self.name

    def grants(self, perm: Perm) -> bool:
        return self.is_owner or perm in self.permissions


class Position(TenantModel):
    """A job title (Cashier, Cook…) the employee picks during onboarding. Grants nothing."""

    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="unique_position_name_per_company"
            ),
        ]

    def __str__(self):
        return self.name


class Membership(TenantModel):
    """A person's employee record in one company."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        BLOCKED = "blocked", _("Blocked")
        LEFT = "left", _("Left")
        # Access paused (discipline, investigation); the record and history stay.
        SUSPENDED = "suspended", _("Suspended")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    position = models.ForeignKey(
        Position, on_delete=models.PROTECT, null=True, blank=True, related_name="members"
    )
    role = models.ForeignKey(
        AccessRole, on_delete=models.PROTECT, null=True, blank=True, related_name="members"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    onboarded_at = models.DateTimeField(null=True, blank=True)
    branches = models.ManyToManyField(
        Branch,
        blank=True,
        related_name="members",
        help_text=_("Branches whose data they see (unless their role sees every branch)."),
    )
    home_branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="home_members",
        help_text=_("Where they work. New tasks belong to this branch."),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "user"], name="unique_membership_per_company"
            ),
        ]
        indexes = [models.Index(fields=["company", "status"])]

    def __str__(self):
        return self.full_name or str(self.user)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_onboarded(self) -> bool:
        return self.onboarded_at is not None

    @property
    def rejoin_available_at(self) -> datetime | None:
        if self.status != self.Status.REJECTED or self.decided_at is None:
            return None
        return self.decided_at + timedelta(hours=self.company.rejoin_cooldown_hours)

    def clean(self):
        # Tenant guard: a role, position or branch from another company must never be attached.
        for field in ("role", "position", "home_branch"):
            related = getattr(self, field)
            if related is not None and related.company_id != self.company_id:
                raise ValidationError({field: _("Must belong to the same company.")})
        if self.pk is not None:
            self.clean_branches(list(self.branches.all()))

    def clean_branches(self, branches: list[Branch]) -> None:
        """Check a new set of branches (before it's saved) against the company and home branch."""
        if any(branch.company_id != self.company_id for branch in branches):
            raise ValidationError({"branches": _("Must belong to the same company.")})
        ids = {branch.pk for branch in branches}
        if ids and self.home_branch_id is not None and self.home_branch_id not in ids:
            raise ValidationError({"home_branch": _("Must be one of the branches they work in.")})

    def has_perm(self, perm: Perm) -> bool:
        return (
            self.status == self.Status.APPROVED and self.role is not None and self.role.grants(perm)
        )
