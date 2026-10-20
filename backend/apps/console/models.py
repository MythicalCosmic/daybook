"""Models of the owner console."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import TenantModel
from apps.members.models import Membership


class SavedView(TenantModel):
    """Filters, columns and sort of a dashboard table, saved under a name.

    The personal Overview layout is one too: `module="overview"`, `name="layout"`,
    `state={"widgets": [{"id", "hidden", "order", "span"}]}`.
    """

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="saved_views")
    module = models.CharField(max_length=32, help_text=_("Dashboard module id, e.g. tasks."))
    name = models.CharField(max_length=80)
    state = models.JSONField(default=dict, blank=True)
    is_shared = models.BooleanField(
        default=False, help_text=_("Everyone with dashboard access in the company can use it.")
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["module", "order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "module", "name"], name="unique_saved_view_name"
            ),
        ]
        indexes = [models.Index(fields=["company", "module", "is_shared"])]

    def __str__(self):
        return f"{self.module}: {self.name}"
