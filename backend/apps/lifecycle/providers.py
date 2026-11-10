"""What the people lifecycle hands the shared registries: the evidence file check, the Needs you
items (requests to leave, job changes to approve) and the buttons of their Telegram copies, the
calendar's last days and job changes, and the step it adds to the offboarding wizard."""

from datetime import date

from django.utils.translation import gettext as _

from apps.console.registry import CalendarItem, OffboardStep, QueueAction, QueueItem
from apps.hr import queries as hr_queries
from apps.lifecycle import bot_messages, job_changes, queries, terminations
from apps.lifecycle.models import DisciplinaryRecord, JobChange, Termination
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm


def may_open_evidence(user, company_id: int, record_id: int) -> bool:
    """`lifecycle.evidence` files: for hr.discipline or hr.view, the person in their branch
    scope (the person themselves reads the record, not the evidence)."""
    record = DisciplinaryRecord.objects.filter(company_id=company_id, pk=record_id).first()
    viewer = (
        Membership.objects.filter(
            company_id=company_id, user=user, status=Membership.Status.APPROVED
        )
        .select_related("company", "role")
        .first()
    )
    if record is None or viewer is None:
        return False
    if not (viewer.has_perm(Perm.HR_DISCIPLINE) or viewer.has_perm(Perm.HR_VIEW)):
        return False
    return (
        hr_queries.person(viewer.company, record.membership_id, branch_ids=scope.branch_ids(viewer))
        is not None
    )


# Needs you -----------------------------------------------------------------------------------


def resignation_count(member: Membership) -> int:
    return len(queries.resignations_for(member))


def resignation_items(member: Membership, limit: int) -> list[QueueItem]:
    items = []
    for termination in queries.resignations_for(member, limit):
        subtitle = _("Last working day asked for: %(date)s") % {
            "date": bot_messages.day(termination.wished_last_day)
        }
        if termination.reason:
            subtitle = f"{subtitle} · {bot_messages._reason(termination.reason)[:120]}"
        items.append(
            QueueItem(
                kind=terminations.QUEUE,
                id=termination.pk,
                title=bot_messages.leave_request_title(termination),
                subtitle=subtitle,
                created_at=termination.requested_at,
                url=f"lifecycle/terminations?termination={termination.pk}",
                actions=(
                    QueueAction(
                        "agree",
                        _("Agree"),
                        "primary",
                        "POST",
                        f"lifecycle/terminations/{termination.pk}/agree/",
                    ),
                    QueueAction(
                        "decline",
                        _("Decline request"),
                        "danger",
                        "POST",
                        f"lifecycle/terminations/{termination.pk}/decline/",
                        needs_reason=True,
                    ),
                ),
            )
        )
    return items


def change_count(member: Membership) -> int:
    return len(queries.changes_to_decide(member))


def change_items(member: Membership, limit: int) -> list[QueueItem]:
    items = []
    for change in queries.changes_to_decide(member, limit):
        lines = bot_messages.change_lines(change)
        subtitle = " · ".join(
            [_("Starts: %(date)s") % {"date": bot_messages.day(change.effective_on)}, *lines]
        )
        items.append(
            QueueItem(
                kind=job_changes.QUEUE,
                id=change.pk,
                title=bot_messages.change_proposed_title(change),
                subtitle=subtitle,
                created_at=change.created_at,
                url=f"lifecycle/job-changes?change={change.pk}",
                actions=(
                    QueueAction(
                        "approve",
                        _("Approve"),
                        "primary",
                        "POST",
                        f"lifecycle/job-changes/{change.pk}/approve/",
                    ),
                    QueueAction(
                        "reject",
                        _("Reject"),
                        "danger",
                        "POST",
                        f"lifecycle/job-changes/{change.pk}/reject/",
                        needs_reason=True,
                    ),
                ),
            )
        )
    return items


# The Telegram copies' buttons ----------------------------------------------------------------


def _termination(notification) -> Termination:
    return Termination.objects.select_related("membership__company", "membership__role").get(
        pk=notification.target_id, company_id=notification.company_id
    )


def _change(notification) -> JobChange:
    return JobChange.objects.select_related("membership__company", "membership__role").get(
        pk=notification.target_id, company_id=notification.company_id
    )


def agree_from_inbox(notification, by: Membership, reason: str) -> str:
    termination = terminations.agree(_termination(notification), by=by)
    return _("Agreed: last working day %(date)s") % {"date": bot_messages.day(termination.last_day)}


def decline_from_inbox(notification, by: Membership, reason: str) -> str:
    terminations.decline(_termination(notification), by=by, reason=reason)
    return _("Declined")


def approve_from_inbox(notification, by: Membership, reason: str) -> str:
    job_changes.approve(_change(notification), by=by)
    return _("Approved")


def reject_from_inbox(notification, by: Membership, reason: str) -> str:
    job_changes.reject(_change(notification), by=by, reason=reason)
    return _("Rejected")


# The company calendar ------------------------------------------------------------------------


def calendar_last_days(company, start: date, end: date, member: Membership) -> list[CalendarItem]:
    """Last working days agreed (and those already past) of the people in the viewer's scope."""
    rows = (
        queries.terminations(company, branch_ids=scope.branch_ids(member))
        .filter(
            status__in=(Termination.Status.AGREED, Termination.Status.COMPLETED),
            last_day__range=(start, end),
        )
        .select_related("membership")
        .order_by("last_day")
    )
    return [
        CalendarItem(
            id=f"lifecycle.leaving:{row.pk}",
            kind="lifecycle.last_days",
            # Translators: %(name)s is a person's name; it stands alone after the colon.
            title=_("Last working day: %(name)s") % {"name": row.membership},
            start=row.last_day,
            end=row.last_day,
            all_day=True,
            color="warning" if row.status == Termination.Status.AGREED else "chart-8",
            url=f"lifecycle/terminations?termination={row.pk}",
        )
        for row in rows
    ]


def calendar_job_changes(company, start: date, end: date, member: Membership) -> list[CalendarItem]:
    """Days approved job changes take (or took) effect, in the viewer's scope."""
    rows = (
        queries.job_changes(company, branch_ids=scope.branch_ids(member))
        .filter(
            status__in=(JobChange.Status.APPROVED, JobChange.Status.APPLIED),
            effective_on__range=(start, end),
        )
        .select_related("membership")
        .order_by("effective_on")
    )
    return [
        CalendarItem(
            id=f"lifecycle.change:{row.pk}",
            kind="lifecycle.job_changes",
            title=_("Job change: %(name)s") % {"name": row.membership},
            start=row.effective_on,
            end=row.effective_on,
            all_day=True,
            color="chart-6",
            url=f"lifecycle/job-changes?change={row.pk}",
        )
        for row in rows
    ]


# The offboarding wizard ----------------------------------------------------------------------


def offboard_step(membership: Membership) -> OffboardStep | None:
    """A leaving under way, when someone offboards the person from their page meanwhile: the
    agreed day and what of the handover is still open (it closes as left with the wizard)."""
    termination = terminations.open_for(membership)
    if termination is None:
        return None
    lines = []
    if termination.status == Termination.Status.AGREED and termination.last_day:
        lines.append(
            _("Their last working day was agreed: %(date)s.")
            % {"date": bot_messages.day(termination.last_day)}
        )
        done, total = terminations.progress(termination)
        if total:
            lines.append(
                _("Handed over: %(done)s. Still open: %(open)s.")
                % {"done": done, "open": total - done}
            )
    else:
        lines.append(
            _(
                "They asked to leave; the request is still waiting (last working day asked for: "
                "%(date)s)."
            )
            % {"date": bot_messages.day(termination.wished_last_day)}
        )
    lines.append(_("Offboarding them now closes it as left today."))
    return OffboardStep(lines=lines, blockers=[], fields=[], defaults={})
