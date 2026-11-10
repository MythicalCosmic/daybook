"""Leaving (docs/PLAN-OWNER.md §13.4 "How a termination runs"): a resignation asked for in the
mini app or a leaving HR starts, the last working day agreed, the handover list, and on that
day's evening the person leaves with their final payslip prepared.

- `request` (the person, mini app) waits in HR's Needs you; HR `agree`s a day (today or later,
  the one asked for by default) or `decline`s it. `start` (HR) is agreed at once. `withdraw`:
  the person before their last day, HR until they leave (with the reason).
- The handover list is built when the day is agreed: the equipment they hold (apps.assets), their
  open tasks, keys and documents; HR adds its own items and ticks them off. Equipment handed back
  in the Equipment pages and tasks finished count as done by themselves.
- On the last day's evening (`due_at`: 20:00 in the company's time, or a quarter of an hour after
  their last shift that day ends) the Celery job completes it through C's offboarding service with
  `by=None`: their access ends, their work goes back, HR ends the contract, assets takes back what
  was ticked off and payroll prepares the final payslip (`details["payroll"]`, payroll's own
  `member_left` receiver). A refusal (the company's only owner) waits for HR's "Try again".
- Someone offboarded or blocked another way meanwhile: their open leaving closes as left
  (`on_member_left`), and their open job changes are cancelled.

Rules: `hr.terminate`, the person inside the manager's branch scope, never oneself; an owner only
by an owner. Every change is audited on the person (no notes or answers in the details).
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from functools import partial
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.hr import queries as hr_queries
from apps.inbox import services as inbox
from apps.lifecycle import integrations, tasks
from apps.lifecycle.audit_actions import LifecycleAction
from apps.lifecycle.models import HandoverItem, JobChange, Termination
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

Status = Termination.Status
Kind = Termination.Kind
Item = HandoverItem.Kind
OPEN = (Status.REQUESTED, Status.AGREED)
CLOSED = (Status.WITHDRAWN, Status.DECLINED)
PULSE = "lifecycle.terminations"
QUEUE = "lifecycle.resignations"
REQUEST_KIND = "lifecycle.resignation"

# A resignation's usual notice (the Labour Code's two weeks; a setting once a lawyer confirms).
NOTICE_DAYS = 14
EVENING = time(20, 0)
AFTER_SHIFT = timedelta(minutes=15)
REMIND_AT = time(9, 0)
MAX_DAYS_AHEAD = 366
MAX_TEXT = 2000
MAX_NOTES = 4000
MAX_LEAVE_DAYS = Decimal(366)
# The offboarding wizard's reason for each kind (members.services.OFFBOARD_REASONS).
WIZARD_REASONS = {
    Kind.RESIGNATION: "resignation",
    Kind.COMPANY: "dismissal",
    Kind.CONTRACT_END: "contract_end",
    Kind.OTHER: "other",
}
# The standard items of a new list, after the equipment.
STANDARD_ITEMS = (Item.TASKS, Item.KEYS, Item.DOCUMENTS)
# What HR may add by hand.
ADDABLE = ("keys", "documents", "other")
ITEM_ORDER = {Item.EQUIPMENT: 0, Item.TASKS: 1, Item.KEYS: 2, Item.DOCUMENTS: 3, Item.OTHER: 4}
# The exit questions: why they leave, and whether they would recommend working here.
EXIT_REASONS = (
    "pay",
    "schedule",
    "workload",
    "team",
    "growth",
    "moving",
    "studies",
    "health",
    "family",
    "other",
)
RECOMMEND = ("yes", "maybe", "no")
EDITABLE = ("kind", "reason", "notes", "rehire", "leave_days", "final_payslip")
# What may still change once it is closed or they have left.
ALWAYS_EDITABLE = ("notes", "rehire")


# Who may -------------------------------------------------------------------------------------


def is_owner(member: Membership | None) -> bool:
    return member is not None and member.role is not None and member.role.is_owner


def may_manage(member: Membership, person: Membership, *, in_scope: bool = False) -> bool:
    """Whether `member` may run `person`'s leaving: hr.terminate, the person in their branch
    scope, not themselves, and an owner only if they are one. `in_scope`: the caller already
    limited the people to `member`'s branch scope."""
    if member.company_id != person.company_id or member.pk == person.pk:
        return False
    if not member.has_perm(Perm.HR_TERMINATE):
        return False
    if is_owner(person) and not is_owner(member):
        return False
    if in_scope:
        return True
    return (
        hr_queries.person(person.company, person.pk, branch_ids=scope.branch_ids(member))
        is not None
    )


def _ensure_may_manage(person: Membership, by: Membership) -> None:
    if by.pk == person.pk:
        raise DomainError(_("You can't do this for your own leaving."))
    if not may_manage(by, person):
        raise PermissionDenied(_("You don't have permission to do this."))


# The person ----------------------------------------------------------------------------------


@transaction.atomic
def request(membership: Membership, *, by: Membership, wished_last_day: date, reason: str = ""):
    """The person asks to leave from `wished_last_day` (their last working day, today or
    later); HR hears in Needs you."""
    if by.pk != membership.pk:
        raise PermissionDenied(_("You don't have permission to do this."))
    membership = _lock_member(membership)
    if membership.status != Membership.Status.APPROVED:
        raise DomainError(_("Only people who work here can ask to leave."))
    today = hr_queries.today(membership.company)
    _check_day(wished_last_day, today)
    if open_for(membership) is not None:
        raise DomainError(_("You have already asked to leave."))
    termination = Termination(
        company_id=membership.company_id,
        membership=membership,
        kind=Kind.RESIGNATION,
        status=Status.REQUESTED,
        reason=_text(reason, limit=MAX_TEXT),
        requested_by=by,
        requested_at=timezone.now(),
        wished_last_day=wished_last_day,
    )
    _event(termination, "requested", by, day=wished_last_day)
    _create(termination)
    _audit(
        LifecycleAction.LEAVE_REQUESTED,
        termination,
        by,
        wished_last_day=wished_last_day.isoformat(),
    )
    transaction.on_commit(partial(tasks.notify_leave_requested.delay, termination.pk))
    bump(termination.company_id, queue=True)
    return termination


@transaction.atomic
def answer_exit(
    termination: Termination, *, by: Membership, reason: str, better: str = "", recommend: str = ""
) -> Termination:
    """The person's answers before they go: why they leave, what would have made it better,
    whether they would recommend working here. They can change them until they leave."""
    termination = _lock(termination)
    if by.pk != termination.membership_id:
        raise PermissionDenied(_("You don't have permission to do this."))
    if termination.status not in OPEN:
        raise DomainError(_("This request is closed."))
    if reason not in EXIT_REASONS:
        raise DomainError(_("Pick the main reason you are leaving."))
    if recommend not in ("", *RECOMMEND):
        raise DomainError(_("Pick an answer from the list."))
    termination.exit_interview = {
        "reason": reason,
        "better": _text(better, limit=1000),
        "recommend": recommend,
        "answered_at": timezone.now().isoformat(),
    }
    termination.save(update_fields=["exit_interview", "updated_at"])
    _audit(LifecycleAction.EXIT_INTERVIEW, termination, by)
    bump(termination.company_id)
    return termination


# HR ------------------------------------------------------------------------------------------


@transaction.atomic
def start(
    membership: Membership,
    *,
    by: Membership,
    kind: str,
    last_day: date,
    reason: str = "",
    leave_days=None,
    final_payslip: bool = True,
) -> Termination:
    """HR starts someone's leaving with the last day agreed at once (a resignation handed in on
    paper, the company ending the work, a contract running out)."""
    _ensure_may_manage(membership, by)
    membership = _lock_member(membership)
    if membership.status not in hr_queries.CURRENT:
        raise DomainError(_("Only people who work here can be given a last day."))
    if kind not in Kind.values:
        raise DomainError(_("Pick why they are leaving."))
    today = hr_queries.today(membership.company)
    _check_day(last_day, today)
    if open_for(membership) is not None:
        raise DomainError(
            _("%(name)s is already leaving: open it to change the day.") % {"name": membership}
        )
    now = timezone.now()
    termination = Termination(
        company_id=membership.company_id,
        membership=membership,
        kind=kind,
        status=Status.AGREED,
        reason=_text(reason, limit=MAX_TEXT),
        requested_by=by,
        requested_at=now,
        wished_last_day=last_day,
        last_day=last_day,
        agreed_by=by,
        agreed_at=now,
        final_payslip=bool(final_payslip),
        leave_days=_leave_days(leave_days),
    )
    _event(termination, "started", by, day=last_day)
    _create(termination)
    build_handover(termination)
    _audit(
        LifecycleAction.LEAVE_STARTED,
        termination,
        by,
        kind=kind,
        last_day=last_day.isoformat(),
    )
    transaction.on_commit(partial(tasks.notify_leave_agreed.delay, termination.pk))
    bump(termination.company_id)
    return termination


@transaction.atomic
def agree(
    termination: Termination,
    *,
    by: Membership,
    last_day: date | None = None,
    leave_days=None,
    final_payslip: bool | None = None,
) -> Termination:
    """Agree the last working day (the one asked for unless another is given), or move an
    agreed one. The handover list is made; the person hears the day."""
    termination = _lock(termination)
    _ensure_may_manage(termination.membership, by)
    if termination.status not in OPEN:
        raise DomainError(_("This leaving is closed."))
    day = last_day or termination.last_day or termination.wished_last_day
    if day is None:
        raise DomainError(_("Pick their last working day."))
    _check_day(day, hr_queries.today(termination.company))
    first = termination.status == Status.REQUESTED
    before = termination.last_day
    moved = not first and day != before
    termination.status = Status.AGREED
    termination.last_day = day
    termination.agreed_by = by
    termination.agreed_at = timezone.now()
    termination.error = ""
    if leave_days is not None:
        termination.leave_days = _leave_days(leave_days)
    if final_payslip is not None:
        termination.final_payslip = bool(final_payslip)
    if first or moved:
        _event(termination, "agreed" if first else "moved", by, day=day)
    termination.save()
    build_handover(termination)
    if first:
        inbox.settle(termination, outcome=gettext_lazy("Agreed"), by=by, kind=REQUEST_KIND)
    details = {"last_day": day.isoformat()}
    if moved and before is not None:
        details["was"] = before.isoformat()
    _audit(LifecycleAction.LEAVE_AGREED, termination, by, **details)
    if first or moved:
        transaction.on_commit(partial(tasks.notify_leave_agreed.delay, termination.pk))
    bump(termination.company_id, queue=first)
    return termination


@transaction.atomic
def decline(termination: Termination, *, by: Membership, reason: str) -> Termination:
    """Say no to a request to leave (talked through, they stay), with the reason they read."""
    termination = _lock(termination)
    _ensure_may_manage(termination.membership, by)
    if termination.status != Status.REQUESTED:
        raise DomainError(_("Only a request waiting for an answer can be declined."))
    reason = _text(reason, limit=300, one_line=True)
    if not reason:
        raise DomainError(_("Say why the request is declined."))
    termination.status = Status.DECLINED
    _close(termination, by, reason)
    _event(termination, "declined", by, note=reason)
    termination.save()
    inbox.settle(termination, outcome=gettext_lazy("Declined"), by=by, kind=REQUEST_KIND)
    _audit(LifecycleAction.LEAVE_DECLINED, termination, by)
    transaction.on_commit(partial(tasks.notify_leave_declined.delay, termination.pk))
    bump(termination.company_id, queue=True)
    return termination


@transaction.atomic
def withdraw(termination: Termination, *, by: Membership, reason: str = "") -> Termination:
    """Call it off: the person (they stay) until the day before their last day, HR (with the
    reason) until they leave."""
    termination = _lock(termination)
    own = by.pk == termination.membership_id
    if termination.status not in OPEN:
        raise DomainError(_("This leaving is closed."))
    reason = _text(reason, limit=300, one_line=True)
    if own:
        today = hr_queries.today(termination.company)
        if termination.status == Status.AGREED and today >= termination.last_day:
            raise DomainError(_("Your last day has come: talk to your manager if you'd stay."))
    else:
        _ensure_may_manage(termination.membership, by)
        if not reason:
            raise DomainError(_("Say why it is called off."))
    was = termination.status
    termination.status = Status.WITHDRAWN
    _close(termination, by, reason)
    _event(termination, "withdrawn", by, note=reason)
    termination.save()
    if was == Status.REQUESTED:
        inbox.settle(termination, outcome=gettext_lazy("Withdrawn"), by=by, kind=REQUEST_KIND)
    _audit(LifecycleAction.LEAVE_WITHDRAWN, termination, by, by_person=own)
    transaction.on_commit(partial(tasks.notify_leave_withdrawn.delay, termination.pk))
    bump(termination.company_id, queue=was == Status.REQUESTED)
    return termination


@transaction.atomic
def update(termination: Termination, *, by: Membership, **fields) -> Termination:
    """Change the details: why and how they leave, the final payslip's leave days, HR's notes
    and whether they would be hired again (the last two also after they left)."""
    termination = _lock(termination)
    _ensure_may_manage(termination.membership, by)
    if unknown := set(fields) - set(EDITABLE):
        raise DomainError(_("Unknown field: %(name)s") % {"name": ", ".join(sorted(unknown))})
    if not termination.is_open and set(fields) - set(ALWAYS_EDITABLE):
        raise DomainError(_("This leaving is closed: only the notes and the rehire answer change."))
    clean: dict = {}
    if "kind" in fields:
        if fields["kind"] not in Kind.values:
            raise DomainError(_("Pick why they are leaving."))
        clean["kind"] = fields["kind"]
    if "reason" in fields:
        clean["reason"] = _text(fields["reason"], limit=MAX_TEXT)
    if "notes" in fields:
        clean["notes"] = _text(fields["notes"], limit=MAX_NOTES)
    if "rehire" in fields:
        if (fields["rehire"] or "") not in ("", *Termination.Rehire.values):
            raise DomainError(_("Pick an answer from the list."))
        clean["rehire"] = fields["rehire"] or ""
    if "leave_days" in fields:
        clean["leave_days"] = _leave_days(fields["leave_days"])
    if "final_payslip" in fields:
        clean["final_payslip"] = bool(fields["final_payslip"])
    changed = sorted(name for name, value in clean.items() if getattr(termination, name) != value)
    if not changed:
        return termination
    for name in changed:
        setattr(termination, name, clean[name])
    termination.save()
    _audit(LifecycleAction.LEAVE_CHANGED, termination, by, fields=changed)
    bump(termination.company_id)
    return termination


# The handover list ---------------------------------------------------------------------------


def build_handover(termination: Termination) -> int:
    """The standard items on a new list, and an item for every piece of equipment the person
    holds that isn't on it yet. Returns how many were added."""
    items = list(termination.handover.all())
    listed = {item.asset_id for item in items if item.asset_id}
    order = max((item.order for item in items), default=0)
    new = []
    for asset_id, label in integrations.held_assets(termination.membership):
        if asset_id not in listed:
            order += 1
            new.append(
                HandoverItem(
                    company_id=termination.company_id,
                    termination=termination,
                    kind=Item.EQUIPMENT,
                    title=label[:200],
                    asset_id=asset_id,
                    order=order,
                )
            )
    if not items:
        for kind in STANDARD_ITEMS:
            order += 1
            new.append(
                HandoverItem(
                    company_id=termination.company_id,
                    termination=termination,
                    kind=kind,
                    order=order,
                )
            )
    HandoverItem.objects.bulk_create(new)
    return len(new)


@transaction.atomic
def add_item(
    termination: Termination, *, by: Membership, title: str, kind: str = Item.OTHER
) -> HandoverItem:
    """An item of HR's own ("The narcotics register to Farrux", "The safe's second key")."""
    termination = _lock(termination)
    _ensure_may_manage(termination.membership, by)
    _ensure_open(termination)
    title = _text(title, limit=200, one_line=True)
    if not title:
        raise DomainError(_("Say what is to be handed over."))
    if kind not in ADDABLE:
        kind = Item.OTHER
    order = max(termination.handover.values_list("order", flat=True), default=0) + 1
    item = HandoverItem.objects.create(
        company_id=termination.company_id,
        termination=termination,
        kind=kind,
        title=title,
        order=order,
    )
    _audit(LifecycleAction.HANDOVER_CHANGED, termination, by, added=kind)
    bump(termination.company_id)
    return item


@transaction.atomic
def set_item(
    item: HandoverItem, *, by: Membership, done: bool | None = None, note: str | None = None
) -> HandoverItem:
    """Tick an item off (or back on), with an optional note ("Handed to Farrux")."""
    termination = _lock(item.termination)
    _ensure_may_manage(termination.membership, by)
    _ensure_open(termination)
    item = HandoverItem.objects.select_for_update().get(pk=item.pk, termination=termination)
    changed = []
    if done is not None and bool(done) != item.done:
        item.done = bool(done)
        item.done_at = timezone.now() if item.done else None
        item.done_by = by if item.done else None
        changed.append("done")
    if note is not None:
        note = _text(note, limit=300, one_line=True)
        if note != item.note:
            item.note = note
            changed.append("note")
    if not changed:
        return item
    item.save()
    _audit(
        LifecycleAction.HANDOVER_CHANGED,
        termination,
        by,
        item=item.kind,
        done=item.done,
    )
    bump(termination.company_id)
    return item


@transaction.atomic
def remove_item(item: HandoverItem, *, by: Membership) -> None:
    """Take an item off the list (equipment only once they no longer hold it)."""
    termination = _lock(item.termination)
    _ensure_may_manage(termination.membership, by)
    _ensure_open(termination)
    if item.asset_id and item.asset_id in dict(integrations.held_assets(termination.membership)):
        raise DomainError(_("They still hold it: tick it off once it is handed back."))
    kind = item.kind
    item.delete()
    _audit(LifecycleAction.HANDOVER_CHANGED, termination, by, removed=kind)
    bump(termination.company_id)


def item_states(termination: Termination) -> dict | None:
    """What an open list's items stand at now: {"held": {asset id: label}, "open_tasks": n}
    (an equipment item no longer held counts as handed back, the tasks item as done when
    nothing is open). None for a closed list: its items were settled when it closed."""
    return states_for([termination]).get(termination.pk)


def states_for(rows) -> dict[int, dict]:
    """`item_states` of many leavings at once (a page of the list), the open ones only."""
    open_rows = [row for row in rows if row.is_open]
    if not open_rows:
        return {}
    company = open_rows[0].membership.company
    ids = [row.membership_id for row in open_rows]
    held = integrations.held_assets_for(company, ids)
    open_tasks = integrations.open_task_counts(company, ids)
    return {
        row.pk: {
            "held": held.get(row.membership_id, {}),
            "open_tasks": open_tasks.get(row.membership_id, 0),
        }
        for row in open_rows
    }


def item_done(item: HandoverItem, states: dict | None) -> bool:
    if item.done:
        return True
    if states is None:
        return False
    if item.kind == Item.EQUIPMENT:
        return item.asset_id is not None and item.asset_id not in states["held"]
    if item.kind == Item.TASKS:
        return states["open_tasks"] == 0
    return False


def progress(termination: Termination, states: dict | None = None) -> tuple[int, int]:
    """(done, total) of the handover list; `states` as `item_states` gives them (looked up
    when not given)."""
    items = list(termination.handover.all())
    if not items:
        return 0, 0
    if states is None and termination.is_open:
        states = item_states(termination)
    return sum(1 for item in items if item_done(item, states)), len(items)


def _settle_items(termination: Termination, states: dict | None) -> list[str]:
    """Freeze the list as it closes: what counted as done by itself is marked done (by
    nobody); returns the labels of what is still open."""
    still_open = []
    now = timezone.now()
    for item in termination.handover.all():
        if item.done:
            continue
        if item_done(item, states):
            item.done, item.done_at, item.done_by = True, now, None
            item.save(update_fields=["done", "done_at", "done_by", "updated_at"])
        else:
            still_open.append(_item_label(item))
    return still_open


# The last day --------------------------------------------------------------------------------


def due_at(termination: Termination) -> datetime:
    """When the person leaves on their last day: 20:00 in the company's time, or a quarter of
    an hour after their last shift that day ends when it ends later (a night shift: the next
    morning)."""
    zone = ZoneInfo(termination.company.timezone)
    evening = datetime.combine(termination.last_day, EVENING, tzinfo=zone)
    shift_end = integrations.last_shift_end(termination.membership, termination.last_day)
    if shift_end is not None and shift_end + AFTER_SHIFT > evening:
        return shift_end + AFTER_SHIFT
    return evening


def complete(termination: Termination, *, by: Membership | None = None) -> Termination:
    """Their last day is over: they leave through the offboarding service (by the system),
    what was ticked off is taken back, and payroll prepares the final payslip. `by` is HR
    pressing "Try again" after a refusal; None the evening job."""
    with transaction.atomic():
        termination = _lock(termination)
        membership = termination.membership
        if by is not None:
            _ensure_may_manage(membership, by)
        if termination.status != Status.AGREED:
            raise DomainError(_("Only a leaving with an agreed last day can be completed."))
        if termination.last_day > hr_queries.today(termination.company):
            raise DomainError(_("Their last day hasn't come yet."))
        if membership.status not in hr_queries.CURRENT:
            # Offboarded another way meanwhile (the receiver missed it): only the record closes.
            _mark_left(termination, by=by, left_on=termination.last_day)
            return termination
        build_handover(termination)
        items = list(termination.handover.all())
        states = item_states(termination) or {"held": {}, "open_tasks": 0}
        ticked = {item.asset_id for item in items if item.asset_id and item.done}
        blockers = integrations.offboard_blockers(membership)
        left_open = [*_settle_items(termination, states), *blockers]
        steps = {
            "assets": {
                f"asset_{asset_id}": "returned" if asset_id in ticked else "keep"
                for asset_id in states["held"]
            },
            "payroll": {
                "prepare": termination.final_payslip
                and integrations.has_pay(membership, on=termination.last_day),
                "leave_days": str(termination.leave_days),
            },
            "lifecycle": {"termination": termination.pk, "kind": termination.kind},
        }
        from apps.members import services as members

        members.complete_offboarding(
            membership,
            by=None,
            terminated_on=termination.last_day,
            reason=WIZARD_REASONS.get(termination.kind, "other"),
            note=termination.reason[:1000],
            steps=steps,
            override_blockers=True,
        )
        termination.status = Status.COMPLETED
        termination.completed_at = timezone.now()
        termination.completed_by = by
        termination.left_on = termination.last_day
        termination.left_open = left_open[:50]
        termination.error = ""
        _event(termination, "completed", by, day=termination.last_day)
        termination.save()
        _audit(
            LifecycleAction.LEAVE_COMPLETED,
            termination,
            by,
            last_day=termination.last_day.isoformat(),
            open_items=len(left_open),
        )
        transaction.on_commit(partial(tasks.notify_left.delay, termination.pk))
        bump(termination.company_id)
    return termination


def complete_due(now: datetime | None = None) -> int:
    """The evening job (every 15 minutes): complete every agreed leaving whose last day's
    evening has come in its company's time. Idempotent: a completed one is left alone, and one
    that was refused waits for HR. Returns how many were completed."""
    now = now or timezone.now()
    rows = (
        Termination.objects.filter(
            status=Status.AGREED,
            error="",
            last_day__lte=timezone.localtime(now).date() + timedelta(days=1),
            company__is_active=True,
        )
        .select_related("company", "membership")
        .order_by("last_day", "pk")
    )
    completed = 0
    for termination in rows:
        if termination.last_day > hr_queries.today(termination.company, now):
            continue
        if now < due_at(termination):
            continue
        try:
            complete(termination)
        except (DomainError, PermissionDenied) as exc:
            _failed(termination, exc)
        else:
            completed += 1
    return completed


def remind_due(now: datetime | None = None) -> int:
    """The morning of a last day (from 09:00 in the company's time), once: whoever agreed it
    hears what of the handover is still open. Nothing when everything is done."""
    now = now or timezone.now()
    rows = Termination.objects.filter(
        status=Status.AGREED,
        last_day__lte=timezone.localtime(now).date() + timedelta(days=1),
        last_day__gte=timezone.localtime(now).date() - timedelta(days=1),
        company__is_active=True,
    ).select_related("company", "membership")
    sent = 0
    for termination in rows:
        zone = ZoneInfo(termination.company.timezone)
        local = timezone.localtime(now, zone)
        if termination.last_day != local.date() or local.time() < REMIND_AT:
            continue
        if termination.reminded_on == local.date():
            continue
        updated = Termination.objects.filter(pk=termination.pk, status=Status.AGREED).exclude(
            reminded_on=local.date()
        )
        if not updated.update(reminded_on=local.date()):
            continue
        done, total = progress(termination)
        if total and done < total:
            tasks.notify_last_day.delay(termination.pk)
            sent += 1
    return sent


def _failed(termination: Termination, exc: Exception) -> None:
    """The evening job couldn't complete it: keep why, tell HR once."""
    message = str(getattr(exc, "message", None) or exc)[:300] or _("It couldn't be completed.")
    updated = Termination.objects.filter(pk=termination.pk, status=Status.AGREED, error="").update(
        error=message, updated_at=timezone.now()
    )
    if updated:
        transaction.on_commit(partial(tasks.notify_leave_failed.delay, termination.pk))
        bump(termination.company_id)


def retry(termination: Termination, *, by: Membership) -> Termination:
    """HR's "Try again" after the evening job was refused: complete it now (its last day has
    come), as `by`."""
    return complete(termination, by=by)


# Someone left another way --------------------------------------------------------------------


def on_member_left(
    sender, membership, reason=None, by=None, details=None, terminated_on=None, **kwargs
) -> None:
    """Offboarded from the person's page or blocked while leaving: their open leaving closes
    as left that day, and their open job changes are cancelled."""
    with transaction.atomic():
        for termination in Termination.objects.select_for_update().filter(
            membership=membership, status__in=OPEN
        ):
            _mark_left(termination, by=by, left_on=terminated_on)
        from apps.lifecycle import job_changes

        for change in JobChange.objects.select_for_update().filter(
            membership=membership, status__in=job_changes.OPEN
        ):
            job_changes.cancel_for_leaver(change)


def _mark_left(termination: Termination, *, by: Membership | None, left_on: date | None) -> None:
    termination.status = Status.COMPLETED
    termination.completed_at = timezone.now()
    termination.completed_by = by
    termination.left_on = left_on or hr_queries.today(termination.company)
    termination.last_day = termination.last_day or termination.left_on
    termination.error = ""
    _event(termination, "left", by, day=termination.left_on)
    termination.save()
    inbox.settle(termination, outcome=gettext_lazy("Left"), by=by, kind=REQUEST_KIND)
    bump(termination.company_id, queue=True)


# Helpers -------------------------------------------------------------------------------------


def open_for(membership: Membership) -> Termination | None:
    return Termination.objects.filter(membership=membership, status__in=OPEN).first()


def notice_days(termination: Termination) -> int | None:
    """Days between asking (or starting) and the last day: the notice given."""
    day = termination.last_day or termination.wished_last_day
    if day is None:
        return None
    asked = timezone.localtime(
        termination.requested_at, ZoneInfo(termination.company.timezone)
    ).date()
    return max(0, (day - asked).days)


def _item_label(item: HandoverItem) -> str:
    return item.title or str(item.get_kind_display())


def _check_day(day, today: date) -> None:
    if not isinstance(day, date):
        raise DomainError(_("Pick the last working day."))
    if day < today:
        raise DomainError(_("The last working day can't be in the past."))
    if day > today + timedelta(days=MAX_DAYS_AHEAD):
        raise DomainError(_("Pick a last working day within a year."))


def _leave_days(value) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    try:
        days = Decimal(str(value).strip().replace(",", ".")).quantize(Decimal("0.01"))
    except InvalidOperation, ValueError:
        raise DomainError(_("Enter the unused leave days: a number from 0 to 366.")) from None
    if not days.is_finite() or days < 0 or days > MAX_LEAVE_DAYS:
        raise DomainError(_("Enter the unused leave days: a number from 0 to 366."))
    return days


def _text(value, *, limit: int, one_line: bool = False) -> str:
    text = str(value or "").strip()
    if one_line:
        text = " ".join(text.split())
    if len(text) > limit:
        raise DomainError(_("Keep it under %(limit)s characters.") % {"limit": limit})
    return text


def _ensure_open(termination: Termination) -> None:
    if not termination.is_open:
        raise DomainError(_("This leaving is closed: its handover list no longer changes."))


def _close(termination: Termination, by: Membership, reason: str) -> None:
    termination.closed_by = by
    termination.closed_at = timezone.now()
    termination.close_reason = reason[:300]


def _event(
    termination: Termination,
    kind: str,
    by: Membership | None,
    *,
    day: date | None = None,
    note: str = "",
) -> None:
    termination.events = [
        *(termination.events or []),
        {
            "kind": kind,
            "at": timezone.now().isoformat(),
            "by": by.pk if by is not None else None,
            "name": str(by) if by is not None else "",
            "day": day.isoformat() if day else None,
            "note": note[:300],
        },
    ]


def _create(termination: Termination) -> None:
    try:
        with transaction.atomic():
            termination.save()
    except IntegrityError:
        raise DomainError(
            _("%(name)s is already leaving: open it to change the day.")
            % {"name": termination.membership}
        ) from None


def _lock(termination: Termination) -> Termination:
    return (
        Termination.objects.select_for_update(of=("self",))
        .select_related("membership__company", "membership__role", "membership__user", "company")
        .get(pk=termination.pk)
    )


def _lock_member(membership: Membership) -> Membership:
    return (
        Membership.objects.select_for_update(of=("self",))
        .select_related("company", "role", "user")
        .get(pk=membership.pk)
    )


def _audit(action: str, termination: Termination, by: Membership | None, **details) -> None:
    audit.record(
        action,
        company_id=termination.company_id,
        actor=by.user if by is not None else None,
        target=termination.membership,
        required_perm=Perm.HR_VIEW,
        termination=termination.pk,
        **details,
    )


def bump(company_id: int, *, queue: bool = False) -> None:
    keys = (PULSE, QUEUE) if queue else (PULSE,)
    transaction.on_commit(partial(pulse.bump, company_id, *keys))
