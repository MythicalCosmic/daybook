"""Registrations of package Q1 (courses, lessons, videos, who watched what).

Imported by `hooks.py`; register a function only once it exists (inbox kinds and actions,
pulse keys, search, streams, file checks, setup steps, company facts, signal receivers).
"""

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.utils.translation import gettext_lazy as _

from apps.audit import registry as audit_registry
from apps.console import registry
from apps.core.files import register_file_check
from apps.inbox.registry import register_kind
from apps.knowledge.models import PageAck
from apps.learning import certificates, courses, media, notify_courses
from apps.members.permissions import Perm

logger = logging.getLogger(__name__)

FEATURE = "learning"

# Lesson videos and their posters: managers of learning, and whoever may open a lesson with it.
register_file_check("learning.video", media.may_open_video)
# Certificates: the person (also while suspended) and holders of learning.view who see them.
register_file_check("learning.certificate", certificates.may_open, allow_suspended=True)

# Version keys: open dashboards refetch courses, lessons and people when they change.
registry.register_pulse(courses.PULSE_KEY, perm=Perm.LEARNING_VIEW, count=None, feature=FEATURE)
registry.register_pulse(media.PULSE_KEY, perm=Perm.LEARNING_VIEW, count=None, feature=FEATURE)

for model_name in ("course", "lesson", "video", "assignment", "learningsettings"):
    audit_registry.register_target(model_name, Perm.LEARNING_MANAGE)

register_kind(
    notify_courses.ASSIGNED,
    label=_("New training given to you"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    notify_courses.DUE_SOON,
    label=_("Training due soon"),
    audience="employee",
    default_telegram=True,
)
register_kind(
    notify_courses.OVERDUE,
    label=_("Training that is late"),
    audience="employee",
    default_telegram=True,
    severity="warning",
)
register_kind(
    notify_courses.ESCALATED,
    label=_("People late with their training"),
    audience="owner",
    default_telegram=True,
    severity="warning",
)
register_kind(
    notify_courses.CERTIFICATE,
    label=_("Certificates of finished courses"),
    audience="employee",
    default_telegram=True,
)


def on_page_ack(sender, instance: PageAck, created: bool, **kwargs) -> None:
    """A confirmed page is a done course step (after the confirmation is committed)."""
    if not created:
        return
    ack_id = instance.pk

    def run():
        ack = PageAck.objects.select_related("page__company").filter(pk=ack_id).first()
        if ack is None:
            return
        try:
            courses.on_page_ack(ack)
        except Exception:
            logger.exception("Counting page %s for the courses failed", ack.page_id)

    transaction.on_commit(run)


post_save.connect(on_page_ack, sender=PageAck, dispatch_uid="learning.on_page_ack")
