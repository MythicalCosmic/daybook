"""Who hears about the people lifecycle, through the inbox (`apps.inbox.services.notify`).

- `lifecycle.record`: the person, when a record is given to them (the employee bot, with a way
  into the mini app's "My record").
- `lifecycle.explanation`: whoever gave the record, when the person explains.
- `lifecycle.resignation`: HR who may run the person's leaving, when they ask to leave (a queue
  kind: Needs you in the dashboard, a Telegram copy with Agree / Decline).
- `lifecycle.leaving`: the person, when their last day is agreed or moved, their request is
  declined or their leaving is called off.
- `lifecycle.leaving_update`: HR, when the person withdraws, on the morning of a last day with
  the handover still open, and when the evening job couldn't complete it.
- `lifecycle.left`: HR, once the person has left (the final payslip waits in Payroll).
- `lifecycle.job_change`: who may decide a proposed job change (a queue kind, Approve / Reject).
- `lifecycle.job_change_update`: the proposer, when it is decided; the approver, when it couldn't
  take effect.
- `lifecycle.job_changed`: the person, when their job changes.
"""

from django.utils.translation import gettext as _

from apps.inbox import services as inbox
from apps.inbox.services import NotificationAction
from apps.lifecycle import bot_messages, integrations
from apps.lifecycle.models import DisciplinaryRecord, JobChange, Termination
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm

RECORD = "lifecycle.record"
EXPLANATION = "lifecycle.explanation"
RESIGNATION = "lifecycle.resignation"
LEAVING = "lifecycle.leaving"
LEAVING_UPDATE = "lifecycle.leaving_update"
LEFT = "lifecycle.left"
JOB_CHANGE = "lifecycle.job_change"
JOB_CHANGE_UPDATE = "lifecycle.job_change_update"
JOB_CHANGED = "lifecycle.job_changed"
LEAVING_SCREEN = "lifecycle.leaving"
CAREER_SCREEN = "lifecycle.career"


def record_screen(record: DisciplinaryRecord) -> str:
    return f"lifecycle.record:{record.pk}"


def record_issued(record_id: int) -> None:
    record = _load(record_id)
    if record is None or record.status == DisciplinaryRecord.Status.WITHDRAWN:
        return
    if record.membership.status != Membership.Status.APPROVED:
        return  # suspended: the bot leaves them alone; the record waits in the app
    inbox.notify(
        [record.membership],
        RECORD,
        title=lambda person: bot_messages.record_title(record),
        body=lambda person: bot_messages.record_body(record),
        app_screen=record_screen(record),
        target=record,
        severity="warning",
        dedupe_key=f"lifecycle.record:{record.pk}",
    )


def explanation(record_id: int) -> None:
    record = _load(record_id)
    if record is None or record.issued_by is None:
        return
    inbox.notify(
        [record.issued_by],
        EXPLANATION,
        title=lambda person: bot_messages.explanation_title(record),
        body=lambda person: bot_messages.explanation_body(record),
        url=f"/c/{record.company_id}/lifecycle/discipline?record={record.pk}",
        target=record,
        actor=record.membership,
    )


def _load(record_id: int) -> DisciplinaryRecord | None:
    return (
        DisciplinaryRecord.objects.select_related(
            "membership__user", "membership__company", "issued_by__user"
        )
        .filter(pk=record_id)
        .first()
    )


# Leaving -------------------------------------------------------------------------------------


def leaving_url(termination: Termination) -> str:
    return f"/c/{termination.company_id}/lifecycle/terminations?termination={termination.pk}"


def leaving_deciders(termination: Termination) -> list[Membership]:
    """Approved members who may run this person's leaving (hr.terminate, in scope, an owner's
    only owners), the person left out."""
    from apps.lifecycle import terminations

    person = termination.membership
    candidates = (
        members_with_perm(termination.company, Perm.HR_TERMINATE)
        .exclude(pk=person.pk)
        .select_related("user", "role", "company")
    )
    return [member for member in candidates if terminations.may_manage(member, person)]


def _hr_for(termination: Termination) -> list[Membership]:
    """Whoever agreed the day, when they still may; else everyone who may run it."""
    from apps.lifecycle import terminations

    agreed = termination.agreed_by
    if (
        agreed is not None
        and agreed.status == Membership.Status.APPROVED
        and terminations.may_manage(agreed, termination.membership)
    ):
        return [agreed]
    return leaving_deciders(termination)


def leave_requested(termination_id: int) -> None:
    from apps.lifecycle import terminations

    termination = _termination(termination_id)
    if termination is None or termination.status != Termination.Status.REQUESTED:
        return
    notice = terminations.notice_days(termination)
    inbox.notify(
        leaving_deciders(termination),
        RESIGNATION,
        title=lambda person: bot_messages.leave_request_title(termination),
        body=lambda person: bot_messages.leave_request_body(termination, notice),
        url=leaving_url(termination),
        target=termination,
        actor=termination.membership,
        actions=[
            NotificationAction("agree", lambda person: _("Agree"), "primary"),
            NotificationAction("decline", lambda person: _("Decline"), "danger", needs_reason=True),
        ],
        dedupe_key=f"lifecycle.resignation:{termination.pk}",
    )


def leave_agreed(termination_id: int) -> None:
    termination = _termination(termination_id)
    if termination is None or termination.status != Termination.Status.AGREED:
        return
    _tell_person(
        termination,
        title=lambda person: bot_messages.leave_agreed_title(termination),
        body=lambda person: bot_messages.leave_agreed_body(termination),
        # A moved day is news again.
        dedupe=f"lifecycle.leaving:{termination.pk}:{termination.last_day}",
    )


def leave_declined(termination_id: int) -> None:
    termination = _termination(termination_id)
    if termination is None or termination.status != Termination.Status.DECLINED:
        return
    _tell_person(
        termination,
        title=lambda person: bot_messages.leave_declined_title(termination),
        body=lambda person: bot_messages.leave_closed_body(termination),
        dedupe=f"lifecycle.leaving:{termination.pk}:declined",
    )


def leave_withdrawn(termination_id: int) -> None:
    """The person withdrew: HR hears. HR called it off: the person hears."""
    termination = _termination(termination_id)
    if termination is None or termination.status != Termination.Status.WITHDRAWN:
        return
    if termination.closed_by_id == termination.membership_id:
        inbox.notify(
            _hr_for(termination),
            LEAVING_UPDATE,
            title=lambda person: bot_messages.leave_withdrawn_title(termination),
            body=lambda person: bot_messages.leave_withdrawn_body(termination),
            url=leaving_url(termination),
            target=termination,
            actor=termination.membership,
            dedupe_key=f"lifecycle.leaving_update:{termination.pk}:withdrawn",
        )
        return
    _tell_person(
        termination,
        title=lambda person: bot_messages.leave_called_off_title(termination),
        body=lambda person: bot_messages.leave_closed_body(termination),
        dedupe=f"lifecycle.leaving:{termination.pk}:withdrawn",
    )


def left(termination_id: int) -> None:
    from apps.lifecycle import terminations

    termination = _termination(termination_id)
    if termination is None or termination.status != Termination.Status.COMPLETED:
        return
    final = integrations.final_run(termination.membership) is not None
    still_open = len(termination.left_open or [])
    recipients = {member.pk: member for member in leaving_deciders(termination)}
    agreed = termination.agreed_by
    if agreed is not None and terminations.may_manage(agreed, termination.membership):
        recipients.setdefault(agreed.pk, agreed)
    inbox.notify(
        list(recipients.values()),
        LEFT,
        title=lambda person: bot_messages.left_title(termination),
        body=lambda person: bot_messages.left_body(
            termination, final_payslip=final, still_open=still_open
        ),
        url=leaving_url(termination),
        target=termination,
        actor=termination.membership,
        dedupe_key=f"lifecycle.left:{termination.pk}",
    )


def last_day(termination_id: int) -> None:
    from apps.lifecycle import terminations

    termination = _termination(termination_id)
    if termination is None or termination.status != Termination.Status.AGREED:
        return
    done, total = terminations.progress(termination)
    if not total or done >= total:
        return
    inbox.notify(
        _hr_for(termination),
        LEAVING_UPDATE,
        title=lambda person: bot_messages.last_day_title(termination),
        body=lambda person: bot_messages.last_day_body(done, total),
        url=leaving_url(termination),
        target=termination,
        actor=termination.membership,
        dedupe_key=f"lifecycle.leaving_update:{termination.pk}:last_day:{termination.last_day}",
    )


def leave_failed(termination_id: int) -> None:
    termination = _termination(termination_id)
    if termination is None or not termination.error:
        return
    inbox.notify(
        leaving_deciders(termination),
        LEAVING_UPDATE,
        title=lambda person: bot_messages.leave_failed_title(termination),
        body=lambda person: bot_messages.leave_failed_body(termination),
        url=leaving_url(termination),
        target=termination,
        severity="warning",
        dedupe_key=f"lifecycle.leaving_update:{termination.pk}:failed:{termination.error[:40]}",
    )


def _tell_person(termination: Termination, *, title, body, dedupe: str) -> None:
    person = termination.membership
    if person.status != Membership.Status.APPROVED:
        return  # suspended: the bot leaves them alone; the app shows it
    inbox.notify(
        [person],
        LEAVING,
        title=title,
        body=body,
        app_screen=LEAVING_SCREEN,
        target=termination,
        dedupe_key=dedupe[:120],
    )


def _termination(termination_id: int) -> Termination | None:
    return (
        Termination.objects.select_related(
            "company",
            "membership__user",
            "membership__company",
            "membership__role",
            "agreed_by__user",
            "agreed_by__role",
            "agreed_by__company",
        )
        .filter(pk=termination_id)
        .first()
    )


# Job changes ---------------------------------------------------------------------------------


def change_url(change: JobChange) -> str:
    return f"/c/{change.company_id}/lifecycle/job-changes?change={change.pk}"


def change_deciders(change: JobChange) -> list[Membership]:
    """Approved members who may decide it, the person and the proposer left out."""
    from apps.lifecycle import job_changes

    candidates = (
        members_with_perm(change.company, Perm.HR_MANAGE)
        .exclude(pk__in=[change.membership_id, change.proposed_by_id or 0])
        .select_related("user", "role", "company")
    )
    return [member for member in candidates if job_changes.may_decide(member, change)]


def change_proposed(change_id: int) -> None:
    change = _change(change_id)
    if change is None or change.status != JobChange.Status.PROPOSED:
        return
    inbox.notify(
        change_deciders(change),
        JOB_CHANGE,
        title=lambda person: bot_messages.change_proposed_title(change),
        body=lambda person: bot_messages.change_proposed_body(change),
        url=change_url(change),
        target=change,
        actor=change.proposed_by,
        actions=[
            NotificationAction("approve", lambda person: _("Approve"), "primary"),
            NotificationAction("reject", lambda person: _("Reject"), "danger", needs_reason=True),
        ],
        dedupe_key=f"lifecycle.job_change:{change.pk}",
    )


def change_decided(change_id: int) -> None:
    change = _change(change_id)
    if change is None or change.proposed_by is None or change.status == JobChange.Status.PROPOSED:
        return
    inbox.notify(
        [change.proposed_by],
        JOB_CHANGE_UPDATE,
        title=lambda person: bot_messages.change_decided_title(change),
        body=lambda person: bot_messages.change_decided_body(change),
        url=change_url(change),
        target=change,
        actor=change.decided_by,
        dedupe_key=f"lifecycle.job_change_update:{change.pk}:{change.status}",
    )


def change_failed(change_id: int) -> None:
    from apps.lifecycle import job_changes

    change = _change(change_id)
    if change is None or not change.error or change.status != JobChange.Status.APPROVED:
        return
    found = {}
    for member in (change.decided_by, change.proposed_by):
        if member is not None and member.status == Membership.Status.APPROVED:
            found.setdefault(member.pk, member)
    recipients = [m for m in found.values() if job_changes.may_propose(m, change.membership)]
    inbox.notify(
        recipients or change_deciders(change),
        JOB_CHANGE_UPDATE,
        title=lambda person: bot_messages.change_failed_title(change),
        body=lambda person: bot_messages.change_failed_body(change),
        url=change_url(change),
        target=change,
        severity="warning",
        dedupe_key=f"lifecycle.job_change_update:{change.pk}:failed:{change.error[:40]}",
    )


def changed(change_id: int) -> None:
    change = _change(change_id)
    if change is None or change.status != JobChange.Status.APPLIED:
        return
    person = change.membership
    if person.status != Membership.Status.APPROVED:
        return
    inbox.notify(
        [person],
        JOB_CHANGED,
        title=lambda reader: bot_messages.changed_title(change),
        body=lambda reader: bot_messages.changed_body(change),
        app_screen=CAREER_SCREEN,
        target=change,
        dedupe_key=f"lifecycle.job_changed:{change.pk}",
    )


def _change(change_id: int) -> JobChange | None:
    return (
        JobChange.objects.select_related(
            "company",
            "membership__user",
            "membership__company",
            "membership__role",
            "proposed_by__user",
            "proposed_by__role",
            "proposed_by__company",
            "decided_by__user",
            "decided_by__role",
            "decided_by__company",
        )
        .filter(pk=change_id)
        .first()
    )
