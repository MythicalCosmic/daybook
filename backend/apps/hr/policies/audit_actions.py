"""Audit action codes and labels of policies (`apps.audit.registry.register`).

What happens to a policy is recorded against the policy (its History tab); a signature is
recorded against the person's membership, so Person 360 shows it in their timeline.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class PolicyAction(models.TextChoices):
    CREATED = "hr.policy_created", _("Created a policy")
    CHANGED = "hr.policy_changed", _("Changed a policy")
    ARCHIVED = "hr.policy_archived", _("Archived a policy")
    RESTORED = "hr.policy_restored", _("Restored a policy")
    REMOVED = "hr.policy_removed", _("Deleted a policy that was never published")
    DRAFT_SAVED = "hr.policy_draft_saved", _("Saved a policy draft")
    DRAFT_DISCARDED = "hr.policy_draft_discarded", _("Discarded a policy draft")
    PUBLISHED = "hr.policy_published", _("Published a policy version")
    REMINDED = "hr.policy_reminded", _("Reminded people to sign a policy")
    SIGNED = "hr.policy_signed", _("Read and signed a policy")
