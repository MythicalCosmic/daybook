"""Every write of policies, shared by the dashboard, the mini app and Celery.

Each service takes `by: Membership` (None: the system), audits its changes through
`apps.audit.services.record` and moves the `hr.policies` pulse after commit.

Who may do what: `hr.manage` writes the policies their branch scope covers (with every branch:
all of them; a branch-bound manager: those of their own branches only) and reminds the people in
their scope; a person signs the policies that apply to them, in the mini app.

The life of a policy: created with a draft (version 1) → published (everyone it applies to owes
a signature within `ack_within_days`) → a new draft → published again, asking everyone again, or
as a small edit that keeps the signatures → archived when it is no longer in force.
"""

from datetime import timedelta
from functools import partial

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.companies.models import Branch
from apps.console import pulse
from apps.core import uploads
from apps.core.exceptions import DomainError
from apps.core.storage import private_storage
from apps.hr import tasks
from apps.hr.models import Policy, PolicyAcknowledgement, PolicyCategory, PolicyVersion
from apps.hr.policies import bodies, notify, queries
from apps.hr.policies.audit_actions import PolicyAction
from apps.members import scope
from apps.members.models import Membership, Position
from apps.members.permissions import Perm

PULSE = "hr.policies"
FILE_TYPES = ("pdf", "image")
# "Remind now" reaches one person once in this long at most.
REMIND_GAP = timedelta(hours=6)
MAX_DAYS = 90
SETTING_FIELDS = ("title", "category", "requires_ack", "ack_within_days", "is_active")
# "Leave it as it is" for the draft's fields.
UNSET = object()


# Policies ------------------------------------------------------------------------------------


@transaction.atomic
def create_policy(
    company,
    *,
    by: Membership,
    title: str,
    category: str = PolicyCategory.OTHER,
    position_ids=(),
    branch_ids=(),
    requires_ack: bool = True,
    ack_within_days: int = 7,
    body: str = "",
    file=None,
    change_note: str = "",
) -> Policy:
    """A new policy with its first draft (version 1): nothing is asked until it is published."""
    _ensure_manager(by, company)
    values = _clean_settings(
        {
            "title": title,
            "category": category,
            "requires_ack": requires_ack,
            "ack_within_days": ack_within_days,
        }
    )
    positions = _positions(company, position_ids)
    branches = _branches(company, branch_ids, by)
    policy = Policy.objects.create(company=company, created_by=by.user, **values)
    policy.positions.set(positions)
    policy.branches.set(branches)
    draft = PolicyVersion(company=company, policy=policy, number=1, created_by=by.user)
    _write(draft, body=body, file=file, change_note=change_note)
    draft.save()
    _audit(PolicyAction.CREATED, policy, by, title=policy.title)
    _bump(company.pk)
    return policy


@transaction.atomic
def update_policy(policy: Policy, *, by: Membership, **fields) -> Policy:
    """Title, category, who it applies to, whether and how soon people sign, archived or not.
    These apply at once: the people it now applies to are asked, those it no longer applies to
    owe nothing; a new number of days moves the deadlines of everyone still to sign."""
    _ensure_manager(by, policy.company)
    policy = _lock(policy)
    _ensure_covers(policy, by)
    values = _clean_settings({name: fields[name] for name in SETTING_FIELDS if name in fields})
    changed = [name for name, value in values.items() if getattr(policy, name) != value]
    for name in changed:
        setattr(policy, name, values[name])
    if "position_ids" in fields:
        positions = _positions(policy.company, fields["position_ids"])
        if {row.pk for row in positions} != set(queries._ids(policy.positions)):
            policy.positions.set(positions)
            changed.append("positions")
    if "branch_ids" in fields:
        branches = _branches(policy.company, fields["branch_ids"], by)
        if {row.pk for row in branches} != set(queries._ids(policy.branches)):
            policy.branches.set(branches)
            changed.append("branches")
    if not changed:
        return policy
    policy.save()
    if "ack_within_days" in changed:
        _redate(policy)
    if "is_active" in changed:
        action = PolicyAction.RESTORED if policy.is_active else PolicyAction.ARCHIVED
        _audit(action, policy, by, title=policy.title)
    others = [name for name in changed if name != "is_active"]
    if others:
        _audit(PolicyAction.CHANGED, policy, by, title=policy.title, fields=sorted(others))
    if sync(policy):
        _tell_later(policy)
    _bump(policy.company_id)
    return policy


@transaction.atomic
def delete_policy(policy: Policy, *, by: Membership) -> None:
    """Only a policy that was never published goes away; a published one is archived (its
    signatures are records)."""
    _ensure_manager(by, policy.company)
    policy = _lock(policy)
    _ensure_covers(policy, by)
    if policy.current_version_id is not None:
        raise DomainError(_("A published policy can't be deleted. Archive it instead."))
    names = {version.file.name for version in policy.versions.all() if version.file}
    _audit(PolicyAction.REMOVED, policy, by, title=policy.title)
    company_id = policy.company_id
    policy.delete()
    for name in names:
        transaction.on_commit(partial(private_storage.delete, name))
    _bump(company_id)


# Drafts and publishing -----------------------------------------------------------------------


@transaction.atomic
def save_draft(
    policy: Policy,
    *,
    by: Membership,
    body=UNSET,
    file=None,
    remove_file: bool = False,
    change_note=UNSET,
) -> PolicyVersion:
    """The next version's text, file and note, kept as a draft. The first save after a publish
    starts the draft from the version in force."""
    _ensure_manager(by, policy.company)
    policy = _lock(policy)
    _ensure_covers(policy, by)
    draft = queries.draft_of(policy)
    if draft is None:
        base = policy.current_version
        number = (policy.versions.aggregate(top=Max("number"))["top"] or 0) + 1
        draft = PolicyVersion(
            company_id=policy.company_id,
            policy=policy,
            number=number,
            created_by=by.user,
            body=base.body if base else "",
            body_text=base.body_text if base else "",
            file=base.file.name if base and base.file else "",
        )
    old_file = draft.file.name if draft.file else ""
    _write(draft, body=body, file=file, remove_file=remove_file, change_note=change_note)
    draft.save()
    if old_file and old_file != (draft.file.name if draft.file else ""):
        _drop_file(policy, old_file)
    _audit(PolicyAction.DRAFT_SAVED, policy, by, title=policy.title, number=draft.number)
    _bump(policy.company_id)
    return draft


@transaction.atomic
def discard_draft(policy: Policy, *, by: Membership) -> None:
    _ensure_manager(by, policy.company)
    policy = _lock(policy)
    _ensure_covers(policy, by)
    draft = queries.draft_of(policy)
    if draft is None:
        raise DomainError(_("There is no draft to discard."))
    name, number = (draft.file.name if draft.file else ""), draft.number
    draft.delete()
    _drop_file(policy, name)
    _audit(PolicyAction.DRAFT_DISCARDED, policy, by, title=policy.title, number=number)
    _bump(policy.company_id)


@transaction.atomic
def publish(
    policy: Policy, *, by: Membership, asks_again: bool = True, change_note=UNSET
) -> PolicyVersion:
    """The draft becomes the version in force. Asking again (always for the first version)
    makes everyone the policy applies to owe a signature for it, within `ack_within_days`;
    what was still owed for the version before is released. A small edit (`asks_again=False`)
    keeps every signature and asks nobody. People hear after commit, outside quiet hours."""
    _ensure_manager(by, policy.company)
    policy = _lock(policy)
    _ensure_covers(policy, by)
    if not policy.is_active:
        raise DomainError(_("This policy is archived. Restore it first."))
    draft = queries.draft_of(policy)
    if draft is None:
        raise DomainError(_("There is nothing new to publish. Save a draft first."))
    if change_note is not UNSET:
        draft.change_note = _note(change_note)
    if not draft.body_text.strip() and not draft.file:
        raise DomainError(_("Write the text or attach the file before publishing."))
    now = timezone.now()
    asks = bool(asks_again) or policy.ack_version_id is None
    draft.asks_again = asks
    draft.published_at = now
    draft.published_by = by.user
    draft.save()
    policy.current_version = draft
    if asks:
        policy.ack_version = draft
    policy.save(update_fields=["current_version", "ack_version", "updated_at"])
    asked = 0
    if asks:
        # Everyone owes the new version now: what was owed for an older one is released.
        PolicyAcknowledgement.objects.filter(
            version__policy=policy, acknowledged_at__isnull=True
        ).exclude(version=draft).delete()
        asked = sync(policy, now=now)
    _audit(
        PolicyAction.PUBLISHED,
        policy,
        by,
        title=policy.title,
        number=draft.number,
        asks_again=asks,
        asked=asked,
    )
    if asks:
        _tell_later(policy)
    _bump(policy.company_id)
    return draft


# Who owes a signature ------------------------------------------------------------------------


def sync(policy: Policy, *, now=None) -> int:
    """Bring the current request in step with who the policy applies to: a row (owed from
    today) for everyone who has none, and the open rows of people it no longer applies to (or
    who stopped working) released. Nothing is owed by an archived policy, one that asks no
    signature or one never published. Returns how many people were newly asked."""
    now = now or timezone.now()
    open_rows = PolicyAcknowledgement.objects.filter(
        version__policy=policy, acknowledged_at__isnull=True
    )
    if not (
        policy.is_active
        and policy.requires_ack
        and policy.ack_version_id
        and policy.current_version_id
    ):
        released = open_rows.delete()[0]
        if released:
            _bump(policy.company_id)
        return 0
    released = open_rows.exclude(version_id=policy.ack_version_id).delete()[0]
    wanted = set(queries.audience(policy).values_list("pk", flat=True))
    have = dict(
        PolicyAcknowledgement.objects.filter(version_id=policy.ack_version_id).values_list(
            "membership_id", "acknowledged_at"
        )
    )
    gone = [member for member, signed in have.items() if signed is None and member not in wanted]
    if gone:
        released += PolicyAcknowledgement.objects.filter(
            version_id=policy.ack_version_id, membership_id__in=gone
        ).delete()[0]
    due_on = queries.due_from(policy, queries.today(policy.company, now))
    fresh = [
        PolicyAcknowledgement(
            version_id=policy.ack_version_id, membership_id=member, asked_at=now, due_on=due_on
        )
        for member in sorted(wanted - have.keys())
    ]
    PolicyAcknowledgement.objects.bulk_create(fresh, ignore_conflicts=True)
    if fresh or released:
        _bump(policy.company_id)
    return len(fresh)


def sync_company(company, *, now=None) -> int:
    """Every policy of the company that asks for signatures, in step (after someone joins)."""
    asked = 0
    for policy in Policy.objects.filter(
        company=company, is_active=True, requires_ack=True, current_version__isnull=False
    ).prefetch_related("positions", "branches"):
        with transaction.atomic():
            asked += sync(policy, now=now)
    return asked


@transaction.atomic
def acknowledge(version: PolicyVersion, *, by: Membership) -> PolicyAcknowledgement:
    """`by` read the version in force and agrees to it (the mini app's "O‘qidim va roziman").
    Signing again changes nothing."""
    if by.status != Membership.Status.APPROVED:
        raise PermissionDenied(_("Your access is paused, so you can't sign now."))
    policy = (
        Policy.objects.select_for_update(of=("self",))
        .select_related("company")
        .filter(pk=version.policy_id, company_id=by.company_id)
        .first()
    )
    if policy is None or not queries.applies_to(policy, by):
        raise PermissionDenied(_("This policy isn't one of yours."))
    if not policy.is_active or policy.current_version_id is None or version.published_at is None:
        raise DomainError(_("This policy isn't in force."))
    if not policy.requires_ack or queries.is_owner(by):
        raise DomainError(_("This policy asks no signature: reading it is enough."))
    if version.pk != policy.current_version_id:
        raise DomainError(_("A newer version came out. Read it and sign that one."))
    now = timezone.now()
    row = (
        PolicyAcknowledgement.objects.select_for_update()
        .filter(version_id=policy.ack_version_id, membership=by)
        .first()
    )
    if row is None:
        row = PolicyAcknowledgement.objects.create(
            version_id=policy.ack_version_id,
            membership=by,
            asked_at=now,
            due_on=queries.due_from(policy, queries.today(policy.company, now)),
            notified_at=now,
        )
    if row.acknowledged_at is None:
        row.acknowledged_at = now
        row.signed_version = version
        row.save(update_fields=["acknowledged_at", "signed_version"])
        audit.record(
            PolicyAction.SIGNED,
            company_id=policy.company_id,
            actor=by.user,
            target=by,
            required_perm=Perm.HR_VIEW,
            policy=policy.pk,
            title=policy.title,
            number=version.number,
        )
        transaction.on_commit(partial(_read_notices, by.pk, policy.pk))
        _bump(policy.company_id)
    return row


@transaction.atomic
def remind(policy: Policy, *, by: Membership, member_ids=None) -> int:
    """ "Remind now": everyone in `by`'s scope still to sign (or the `member_ids` of them) hears
    again at once, each once in `REMIND_GAP` at most. Returns how many were reminded."""
    _ensure_manager(by, policy.company)
    policy = _lock(policy)
    if not (policy.is_active and policy.requires_ack and policy.ack_version_id):
        raise DomainError(_("Nobody owes a signature for this policy."))
    now = timezone.now()
    day = queries.today(policy.company, now)
    rows = queries.in_scope(queries.requests(policy), scope.branch_ids(by)).filter(
        acknowledged_at__isnull=True, membership__status=Membership.Status.APPROVED
    )
    if member_ids is not None:
        rows = rows.filter(membership_id__in=list(member_ids))
    rows = list(rows.select_related("membership__user", "membership__company", "version__policy"))
    if not rows:
        raise DomainError(_("Everyone here has signed."))
    due = [row for row in rows if row.reminded_at is None or now - row.reminded_at >= REMIND_GAP]
    if not due:
        raise DomainError(_("They were reminded a few hours ago. Give them some time."))
    for row in due:
        notify.remind(row, day, now, manual=True)
    PolicyAcknowledgement.objects.filter(pk__in=[row.pk for row in due]).update(reminded_at=now)
    PolicyAcknowledgement.objects.filter(
        pk__in=[row.pk for row in due], notified_at__isnull=True
    ).update(notified_at=now)
    _audit(PolicyAction.REMINDED, policy, by, title=policy.title, people=len(due))
    _bump(policy.company_id)
    return len(due)


# Helpers -------------------------------------------------------------------------------------


def _clean_settings(values: dict) -> dict:
    out = dict(values)
    if "title" in out:
        title = " ".join(str(out["title"] or "").split())
        if not title:
            raise DomainError(_("Give the policy a title."))
        out["title"] = title[:150]
    if "category" in out and out["category"] not in PolicyCategory.values:
        raise DomainError(_("Pick a category."))
    if "ack_within_days" in out:
        try:
            days = int(out["ack_within_days"])
        except (TypeError, ValueError) as exc:
            raise DomainError(_("Give the number of days to sign in.")) from exc
        if not 1 <= days <= MAX_DAYS:
            raise DomainError(_("People sign within 1 to %(max)d days.") % {"max": MAX_DAYS})
        out["ack_within_days"] = days
    for name in ("requires_ack", "is_active"):
        if name in out:
            out[name] = bool(out[name])
    return out


def _positions(company, ids) -> list[Position]:
    wanted = {int(pk) for pk in ids or ()}
    found = list(Position.objects.filter(company=company, pk__in=wanted))
    if len(found) != len(wanted):
        raise DomainError(_("Pick positions of this company."))
    return found


def _branches(company, ids, by: Membership) -> list[Branch]:
    wanted = {int(pk) for pk in ids or ()}
    found = list(Branch.objects.filter(company=company, pk__in=wanted))
    if len(found) != len(wanted):
        raise DomainError(_("Pick branches of this company."))
    if not queries.covers(scope.branch_ids(by), wanted):
        raise DomainError(_("Pick the branches this policy is for, among the ones you manage."))
    return found


def _write(draft: PolicyVersion, *, body=UNSET, file=None, remove_file=False, change_note=UNSET):
    if body is not UNSET:
        raw = body or ""
        if len(raw) > bodies.MAX_BODY_CHARS:
            raise DomainError(_("The text is too long. Attach a long document as the file."))
        draft.body = bodies.clean_body(raw)
        draft.body_text = bodies.text_of(draft.body)
    if remove_file:
        draft.file = ""
    if file is not None:
        content = uploads.accept_document(file, allowed=FILE_TYPES)
        draft.file.save(content.name, content, save=False)
    if change_note is not UNSET:
        draft.change_note = _note(change_note)


def _note(value) -> str:
    return " ".join(str(value or "").split())[:300]


def _drop_file(policy: Policy, name: str) -> None:
    """Delete a stored file once no version of the policy uses it (a draft starts with the
    file of the version in force)."""
    if name and not PolicyVersion.objects.filter(policy=policy, file=name).exists():
        transaction.on_commit(partial(private_storage.delete, name))


def _redate(policy: Policy) -> None:
    """New deadlines for everyone still to sign: the new number of days from when they were
    asked. Who was late and no longer is may be told about again if they become late."""
    if policy.ack_version_id is None:
        return
    rows = list(
        PolicyAcknowledgement.objects.filter(
            version_id=policy.ack_version_id, acknowledged_at__isnull=True
        )
    )
    for row in rows:
        row.due_on = queries.due_from(policy, queries.today(policy.company, row.asked_at))
        row.late_notified_at = None
    PolicyAcknowledgement.objects.bulk_update(rows, ["due_on", "late_notified_at"])


def _tell_later(policy: Policy) -> None:
    """The people asked hear once this commits (or after the quiet hours, from the beat)."""
    transaction.on_commit(partial(tasks.policy_notices.delay, policy.pk))


def _read_notices(member_id: int, policy_id: int) -> None:
    """Once someone signed, the messages asking them to are read."""
    from apps.inbox import services as inbox
    from apps.inbox.models import Notification

    member = Membership.objects.filter(pk=member_id).first()
    if member is None:
        return
    ids = list(
        Notification.objects.filter(
            recipient=member,
            kind=notify.POLICY,
            target_type="policy",
            target_id=policy_id,
            read_at__isnull=True,
        ).values_list("pk", flat=True)
    )
    if ids:
        inbox.mark_read(member, ids=ids)


def _lock(policy: Policy) -> Policy:
    return (
        Policy.objects.select_for_update(of=("self",)).select_related("company").get(pk=policy.pk)
    )


def _ensure_manager(by: Membership | None, company) -> None:
    if by is None:
        return
    if by.company_id != company.pk or not by.has_perm(Perm.HR_MANAGE):
        raise PermissionDenied(_("You don't have permission to do this."))


def _ensure_covers(policy: Policy, by: Membership | None) -> None:
    """A branch-bound manager changes only the policies of their own branches."""
    if by is not None and not queries.may_change(by, policy):
        raise PermissionDenied(_("This policy reaches branches you don't manage."))


def _audit(action: str, policy: Policy, by: Membership | None, **details) -> None:
    audit.record(
        action,
        company_id=policy.company_id,
        actor=by.user if by else None,
        target=policy,
        required_perm=Perm.HR_VIEW,
        **details,
    )


def _bump(company_id: int) -> None:
    transaction.on_commit(partial(pulse.bump, company_id, PULSE))
