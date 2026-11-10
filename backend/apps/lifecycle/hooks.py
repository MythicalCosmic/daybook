"""Registrations with the shared registries and signal receivers of the people lifecycle.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from django.utils.translation import gettext_lazy as _

import apps.lifecycle.equipment.hooks  # noqa: F401  (equipment's registrations)
from apps.audit import registry as audit_registry
from apps.console import registry
from apps.console.perms import AnyOf
from apps.core.files import register_file_check
from apps.inbox.registry import register_action, register_kind
from apps.lifecycle import job_changes, notify, providers, terminations
from apps.lifecycle.audit_actions import LifecycleAction
from apps.members.permissions import Perm
from apps.members.signals import member_left

FEATURE = "hr"
LEAVING_VIEW = AnyOf(Perm.HR_TERMINATE, Perm.HR_VIEW)
CHANGES_VIEW = AnyOf(Perm.HR_MANAGE, Perm.HR_VIEW)

audit_registry.register(LifecycleAction)

register_file_check("lifecycle.evidence", providers.may_open_evidence)

registry.register_pulse(
    "lifecycle.discipline",
    perm=AnyOf(Perm.HR_DISCIPLINE, Perm.HR_VIEW),
    count=None,
    feature=FEATURE,
)

# The person hears a record was given (the employee bot, into "My record"); whoever gave it
# hears the explanation.
register_kind(
    notify.RECORD,
    label=_("Warnings and reprimands"),
    audience="employee",
    default_telegram=True,
    severity="warning",
)
register_kind(
    notify.EXPLANATION,
    label=_("Explanations to records"),
    audience="owner",
    default_telegram=True,
)

# Leaving: requests in Needs you (and their Telegram copy with buttons), the sidebar badge, the
# pages' version key, what HR and the person hear, the last days on the calendar.
register_kind(
    notify.RESIGNATION,
    label=_("Requests to leave"),
    audience="owner",
    default_telegram=True,
    queue_kind=terminations.QUEUE,
)
register_action(notify.RESIGNATION, "agree", providers.agree_from_inbox)
register_action(notify.RESIGNATION, "decline", providers.decline_from_inbox)
registry.register_queue(
    terminations.QUEUE,
    perm=Perm.HR_TERMINATE,
    label=_("Requests to leave"),
    count=providers.resignation_count,
    items=providers.resignation_items,
    feature=FEATURE,
)
registry.register_pulse(
    terminations.QUEUE, perm=Perm.HR_TERMINATE, count=providers.resignation_count, feature=FEATURE
)
registry.register_pulse(terminations.PULSE, perm=LEAVING_VIEW, count=None, feature=FEATURE)
register_kind(
    notify.LEAVING_UPDATE,
    label=_("Leaving: withdrawn requests, last days, problems"),
    audience="owner",
    default_telegram=True,
)
register_kind(
    notify.LEFT,
    label=_("People who left"),
    audience="owner",
    default_telegram=True,
)
register_kind(
    notify.LEAVING,
    label=_("Your leaving"),
    audience="employee",
    default_telegram=True,
)
registry.register_calendar_source(
    "lifecycle.last_days",
    label=_("Last working days"),
    perm=LEAVING_VIEW,
    events=providers.calendar_last_days,
    feature=FEATURE,
)
# Someone offboarded from their page while leaving: the wizard says so, and the leaving closes.
registry.register_offboard_step(
    "lifecycle",
    perm=None,
    order=15,
    label=_("Leaving and handover"),
    preview=providers.offboard_step,
    feature=FEATURE,
)
member_left.connect(terminations.on_member_left, dispatch_uid="lifecycle.member_left")

# Job changes: proposals in Needs you (with Approve / Reject in Telegram), the badge, what the
# proposer, the approver and the person hear, the days they take effect on the calendar.
register_kind(
    notify.JOB_CHANGE,
    label=_("Job changes to approve"),
    audience="owner",
    default_telegram=True,
    queue_kind=job_changes.QUEUE,
)
register_action(notify.JOB_CHANGE, "approve", providers.approve_from_inbox)
register_action(notify.JOB_CHANGE, "reject", providers.reject_from_inbox)
registry.register_queue(
    job_changes.QUEUE,
    perm=Perm.HR_MANAGE,
    label=_("Job changes to approve"),
    count=providers.change_count,
    items=providers.change_items,
    feature=FEATURE,
)
registry.register_pulse(
    job_changes.QUEUE, perm=Perm.HR_MANAGE, count=providers.change_count, feature=FEATURE
)
registry.register_pulse(job_changes.PULSE, perm=CHANGES_VIEW, count=None, feature=FEATURE)
register_kind(
    notify.JOB_CHANGE_UPDATE,
    label=_("Job changes decided or not applied"),
    audience="owner",
    default_telegram=True,
)
register_kind(
    notify.JOB_CHANGED,
    label=_("Changes to your job"),
    audience="employee",
    default_telegram=True,
)
registry.register_calendar_source(
    "lifecycle.job_changes",
    label=_("Job changes"),
    perm=CHANGES_VIEW,
    events=providers.calendar_job_changes,
    feature=FEATURE,
)
