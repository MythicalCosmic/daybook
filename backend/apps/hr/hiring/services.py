"""Hiring: vacancies, applying in the employee bot, and the pipeline (docs/PLAN-OWNER.md §3.11).

    create_vacancy / update_vacancy / set_status / delete_vacancy     the dashboard (hr.hiring)
    open_link / apply                                                 the employee bot
    move / reject / hire / add_note                                   the pipeline (hr.hiring)

Every change a member makes is checked here too (`hr.hiring`, and the vacancy's branch inside
their scope; a vacancy without a branch is for those who see every branch), audited, and bumps
the `hr.vacancies` and `hr.applicants` pulse keys once it commits.

A new applicant is told to the hiring team through the inbox (`hr.applicant`). What happens to
an application is told to the applicant in the employee bot, in their language: an invitation
to an interview, an offer, a refusal (with a message, or without one when the team prefers),
the hire. Hiring asks to join the company for them (`members.services.request_access`) and
approves that request with the vacancy's position, branch and the position's role (`approve`),
so they get the usual welcome and create their account like anyone the company lets in.
"""

import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from functools import partial
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.core.uploads import sanitize_image
from apps.hr.hiring import bot, queries, questions
from apps.hr.hiring.actions import HiringAction
from apps.hr.models import Applicant, ApplicantEvent, Vacancy
from apps.inbox import services as inbox
from apps.members import scope
from apps.members import services as members
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm
from apps.notifications.tasks import send_telegram_message
from apps.notifications.telegram import BotName

PULSE_VACANCIES = "hr.vacancies"
PULSE_APPLICANTS = "hr.applicants"
# The inbox kind of a new applicant (to the hiring team).
NEW_APPLICANT = "hr.applicant"
# A person may apply for this many vacancies a day, over every company.
MAX_APPLICATIONS_A_DAY = 5
TITLE_MAX = 120
DESCRIPTION_MAX = 2000
NAME_MAX = 150
MESSAGE_MAX = 1000
REASON_MAX = 200
NOTE_MAX = 2000
SALARY_MAX = Decimal("1000000000000")
EDITABLE = (
    "title",
    "position",
    "branch",
    "description",
    "salary_from",
    "salary_to",
    "questions",
    "asks_document",
    "opens_on",
    "closes_on",
)
Stage = Applicant.Stage
# Stages an applicant moves between freely; hired and rejected have their own actions.
PIPELINE = queries.OPEN_STAGES
# Where the applicant is told by default when moved there (with or without a message).
TOLD_BY_DEFAULT = (Stage.INTERVIEW, Stage.OFFER)
# Letters (any script) in words joined by a space, a hyphen, an apostrophe or a dot.
NAME = re.compile(r"^[^\W\d_]+(?:[ \-’‘'`.]{1,2}[^\W\d_]+)*\.?$")


class LinkState(StrEnum):
    """What a vacancy link answers now."""

    OK = "ok"
    GONE = "gone"  # no such vacancy (or its company is closed)
    DRAFT = "draft"
    NOT_YET = "not_yet"  # open, but from a later day
    PAUSED = "paused"
    CLOSED = "closed"  # closed, past its last day, or HR is switched off
    APPLIED = "applied"  # this person applied already: they see where they stand
    MEMBER = "member"  # they already work at this company
    LIMIT = "limit"  # too many applications today


@dataclass(frozen=True)
class Opened:
    state: LinkState
    vacancy: Vacancy | None = None
    applicant: Applicant | None = None
    source: str = Applicant.Source.LINK


# Vacancies ---------------------------------------------------------------------------------


@transaction.atomic
def create_vacancy(company, *, by: Membership, publish: bool = False, **fields) -> Vacancy:
    """A new vacancy, a draft unless `publish` opens it to applicants at once."""
    _ensure_hirer(by, company)
    unknown = set(fields) - set(EDITABLE)
    if unknown:
        raise TypeError(f"create_vacancy: unknown fields {sorted(unknown)}")
    if not fields.get("title"):
        raise DomainError(_("Give the vacancy a title."))
    vacancy = Vacancy(company=company, created_by=by)
    _apply(vacancy, by, fields, creating=True)
    if publish:
        _check_can_open(vacancy)
        vacancy.status = Vacancy.Status.OPEN
        vacancy.published_at = timezone.now()
    vacancy.save()
    audit.record(
        HiringAction.VACANCY_CREATED,
        company_id=company.pk,
        actor=by.user,
        target=vacancy,
        status=vacancy.status,
    )
    _bump(company.pk, PULSE_VACANCIES)
    return vacancy


@transaction.atomic
def update_vacancy(vacancy: Vacancy, *, by: Membership, **fields) -> Vacancy:
    vacancy = _lock_vacancy(vacancy)
    _ensure_may_run(by, vacancy)
    unknown = set(fields) - set(EDITABLE)
    if unknown:
        raise TypeError(f"update_vacancy: unknown fields {sorted(unknown)}")
    changed = _apply(vacancy, by, fields, creating=False)
    if not changed:
        return vacancy
    vacancy.save()
    audit.record(
        HiringAction.VACANCY_CHANGED,
        company_id=vacancy.company_id,
        actor=by.user,
        target=vacancy,
        fields=sorted(changed),
    )
    _bump(vacancy.company_id, PULSE_VACANCIES)
    return vacancy


# What each status may become, and the audit action of getting there.
MOVES = {
    Vacancy.Status.OPEN: (
        {Vacancy.Status.DRAFT, Vacancy.Status.PAUSED, Vacancy.Status.CLOSED},
        HiringAction.VACANCY_OPENED,
    ),
    Vacancy.Status.PAUSED: ({Vacancy.Status.OPEN}, HiringAction.VACANCY_PAUSED),
    Vacancy.Status.CLOSED: (
        {Vacancy.Status.DRAFT, Vacancy.Status.OPEN, Vacancy.Status.PAUSED},
        HiringAction.VACANCY_CLOSED,
    ),
}


@transaction.atomic
def set_status(vacancy: Vacancy, status: str, *, by: Membership) -> Vacancy:
    """Open (also again after a pause or once closed), pause or close a vacancy."""
    vacancy = _lock_vacancy(vacancy)
    _ensure_may_run(by, vacancy)
    if status not in MOVES:
        raise DomainError(_("A vacancy can be opened, paused or closed."))
    if vacancy.status == status:
        return vacancy
    sources, action = MOVES[status]
    if vacancy.status not in sources:
        raise DomainError(_("Only an open vacancy can be paused."))
    now = timezone.now()
    if status == Vacancy.Status.OPEN:
        _check_can_open(vacancy)
        vacancy.published_at = vacancy.published_at or now
        vacancy.closed_at = None
    elif status == Vacancy.Status.CLOSED:
        vacancy.closed_at = now
    previous = vacancy.status
    vacancy.status = status
    vacancy.save(update_fields=["status", "published_at", "closed_at", "updated_at"])
    audit.record(action, company_id=vacancy.company_id, actor=by.user, target=vacancy, was=previous)
    _bump(vacancy.company_id, PULSE_VACANCIES)
    return vacancy


@transaction.atomic
def delete_vacancy(vacancy: Vacancy, *, by: Membership) -> None:
    """Only a vacancy nobody applied for goes; one with applicants is closed instead."""
    vacancy = _lock_vacancy(vacancy)
    _ensure_may_run(by, vacancy)
    if vacancy.applicants.exists():
        raise DomainError(_("People applied for this vacancy. Close it instead."))
    audit.record(
        HiringAction.VACANCY_DELETED,
        company_id=vacancy.company_id,
        actor=by.user,
        target=vacancy,
        title=vacancy.title,
    )
    company_id = vacancy.company_id
    vacancy.delete()
    _bump(company_id, PULSE_VACANCIES)


def _apply(vacancy: Vacancy, by: Membership, fields: dict, *, creating: bool) -> set[str]:
    """Check `fields` and set them on `vacancy`; returns the names that changed."""
    company = vacancy.company
    changed: set[str] = set()
    for name, value in fields.items():
        if name == "title":
            value = " ".join(str(value or "").split())
            if not value:
                raise DomainError(_("Give the vacancy a title."))
            if len(value) > TITLE_MAX:
                raise DomainError(
                    _("A title can be at most %(count)d characters.") % {"count": TITLE_MAX}
                )
        elif name == "description":
            value = str(value or "").strip()
            if len(value) > DESCRIPTION_MAX:
                raise DomainError(
                    _("A description can be at most %(count)d characters.")
                    % {"count": DESCRIPTION_MAX}
                )
        elif name == "position" and value is not None:
            if value.company_id != company.pk or not value.is_active:
                raise DomainError(_("Pick a position of this company."))
        elif name == "branch" and value is not None:
            if value.company_id != company.pk or not value.is_active:
                raise DomainError(_("Pick a branch of this company."))
            if not scope.allows(scope.branch_ids(by), value.pk):
                raise PermissionDenied(_("You can only choose the branches you manage."))
        elif name in ("salary_from", "salary_to") and value is not None:
            value = Decimal(value)
            if value < 0 or value > SALARY_MAX:
                raise DomainError(_("Give the salary as a positive amount."))
        elif name == "questions":
            value = questions.clean(value)
        elif name == "asks_document":
            value = bool(value)
        if name in ("position", "branch"):
            if getattr(vacancy, f"{name}_id") != (value.pk if value is not None else None):
                changed.add(name)
        elif getattr(vacancy, name) != value:
            changed.add(name)
        setattr(vacancy, name, value)

    if vacancy.branch_id is None and scope.branch_ids(by) is not None:
        raise DomainError(_("Choose one of your branches."))
    low, high = vacancy.salary_from, vacancy.salary_to
    if low is not None and high is not None and high < low:
        raise DomainError(_("The salary's upper end can't be below its lower end."))
    if vacancy.opens_on and vacancy.closes_on and vacancy.closes_on < vacancy.opens_on:
        raise DomainError(_("The last day to apply can't come before the first."))
    if "closes_on" in changed and vacancy.closes_on and vacancy.closes_on < _today(company):
        raise DomainError(_("The last day to apply can't be in the past."))
    return changed


def _check_can_open(vacancy: Vacancy) -> None:
    if vacancy.closes_on and vacancy.closes_on < _today(vacancy.company):
        raise DomainError(_("The last day to apply has passed. Change it to open the vacancy."))


# Applying in the bot -----------------------------------------------------------------------


def parse_start(payload: str) -> tuple[str, str]:
    """`<code>` or `<code>-q` (the QR code's link): the code and where the applicant came from."""
    code, separator, tag = (payload or "").partition("-")
    qr = separator and tag == Vacancy.QR_SUFFIX.removeprefix("-")
    return code, Applicant.Source.QR if qr else Applicant.Source.LINK


def link_state(vacancy: Vacancy) -> LinkState:
    """Whether the vacancy takes applications today, and why not."""
    if not vacancy.company.has_feature("hr"):
        return LinkState.CLOSED
    if vacancy.status == Vacancy.Status.DRAFT:
        return LinkState.DRAFT
    if vacancy.status == Vacancy.Status.PAUSED:
        return LinkState.PAUSED
    if vacancy.status == Vacancy.Status.CLOSED:
        return LinkState.CLOSED
    today = _today(vacancy.company)
    if vacancy.closes_on and vacancy.closes_on < today:
        return LinkState.CLOSED
    if vacancy.opens_on and vacancy.opens_on > today:
        return LinkState.NOT_YET
    return LinkState.OK


def accepting(vacancy: Vacancy) -> bool:
    return link_state(vacancy) == LinkState.OK


def open_link(user, payload: str) -> Opened:
    """`/start job_<payload>`: the vacancy for `user`, or why they can't apply."""
    code, source = parse_start(payload)
    vacancy = queries.find_by_code(code)
    if vacancy is None:
        return Opened(LinkState.GONE)
    mine = queries.application_of(vacancy, user)
    if mine is not None:
        return Opened(LinkState.APPLIED, vacancy, mine)
    state = link_state(vacancy)
    if state != LinkState.OK:
        return Opened(state, vacancy)
    if _works_here(vacancy.company, user):
        return Opened(LinkState.MEMBER, vacancy)
    if _over_limit(user):
        return Opened(LinkState.LIMIT, vacancy)
    _count_open(vacancy, user)
    return Opened(LinkState.OK, vacancy, source=source)


def vacancy_for_flow(vacancy_id: int) -> Vacancy | None:
    """The vacancy an application in progress is for (the bot's conversation keeps its id)."""
    return (
        Vacancy.objects.select_related("company", "branch", "position")
        .filter(pk=vacancy_id, company__is_active=True)
        .first()
    )


def clean_name(value: str | None) -> str | None:
    """A person's name as typed, tidied ("aziza  karimova" stays as typed but single-spaced);
    None unless it's at least two words of letters."""
    name = " ".join((value or "").split())
    if not 3 <= len(name) <= NAME_MAX or len(name.split(" ")) < 2 or not NAME.match(name):
        return None
    return name


def suggested_name(user) -> str:
    """The name Telegram knows them by, when it reads like a first and last name."""
    return clean_name(f"{user.first_name} {user.last_name}") or ""


@transaction.atomic
def apply(
    vacancy_id: int,
    user,
    *,
    name: str,
    phone: str,
    answers: list[dict],
    source: str = Applicant.Source.LINK,
    document: bytes | None = None,
) -> Applicant:
    """Send an application. DomainError says why it can't be (in the applicant's language)."""
    vacancy = (
        Vacancy.objects.select_for_update(of=("self",))
        .select_related("company", "branch", "position")
        .filter(pk=vacancy_id, company__is_active=True)
        .first()
    )
    if vacancy is None:
        raise DomainError(bot.unavailable(LinkState.GONE))
    if queries.application_of(vacancy, user) is not None:
        raise DomainError(_("You have already applied for this vacancy."))
    state = link_state(vacancy)
    if state != LinkState.OK:
        raise DomainError(bot.unavailable(state, vacancy))
    if _works_here(vacancy.company, user):
        raise DomainError(bot.unavailable(LinkState.MEMBER, vacancy))
    if _over_limit(user):
        raise DomainError(bot.unavailable(LinkState.LIMIT, vacancy))
    cleaned = clean_name(name)
    if cleaned is None:
        raise DomainError(bot.bad_name())
    now = timezone.now()
    applicant = Applicant(
        company=vacancy.company,
        vacancy=vacancy,
        user=user,
        name=cleaned,
        phone=(phone or "")[:20],
        telegram_username=(user.telegram_username or "")[:64],
        language=user.language,
        answers=_answers(answers),
        source=source if source in Applicant.Source.values else Applicant.Source.LINK,
        stage=Stage.NEW,
        stage_changed_at=now,
    )
    if document and vacancy.asks_document:
        photo = sanitize_image(document, max_side=2048)
        applicant.document.save(photo.name, photo, save=False)
    try:
        with transaction.atomic():
            applicant.save()
    except IntegrityError as exc:  # the same person, twice at once
        raise DomainError(_("You have already applied for this vacancy.")) from exc
    ApplicantEvent.objects.create(
        company=vacancy.company,
        applicant=applicant,
        kind=ApplicantEvent.Kind.APPLIED,
        to_stage=Stage.NEW,
    )
    audit.record(
        HiringAction.APPLIED,
        company_id=vacancy.company_id,
        actor=user,
        target=applicant,
        vacancy=vacancy.pk,
        source=applicant.source,
    )
    _notify_team(applicant)
    _bump(vacancy.company_id, PULSE_APPLICANTS, PULSE_VACANCIES)
    return applicant


def _answers(rows) -> list[dict]:
    """The answers as the bot collected them, kept to their shape and lengths."""
    kept = []
    for row in list(rows or [])[: questions.MAX_QUESTIONS]:
        if not isinstance(row, dict):
            continue
        kept.append(
            {
                "id": str(row.get("id") or "")[:16],
                "text": str(row.get("text") or "")[: questions.TEXT_MAX],
                "kind": str(row.get("kind") or "text")[:8],
                "answer": str(row.get("answer") or "")[: questions.ANSWER_MAX],
            }
        )
    return kept


def _works_here(company, user) -> bool:
    return Membership.objects.filter(
        company=company, user=user, status__in=members.CURRENT
    ).exists()


def _over_limit(user) -> bool:
    since = timezone.now() - timedelta(days=1)
    sent = Applicant.objects.filter(user=user, created_at__gte=since).count()
    return sent >= MAX_APPLICATIONS_A_DAY


def _count_open(vacancy: Vacancy, user) -> None:
    """One more opening of the link, once a day per person."""
    key = f"hr:vacancy-open:{vacancy.pk}:{user.pk}:{_today(vacancy.company).isoformat()}"
    if cache.add(key, 1, timeout=60 * 60 * 24):
        Vacancy.objects.filter(pk=vacancy.pk).update(link_opens=F("link_opens") + 1)
        _bump(vacancy.company_id, PULSE_VACANCIES)


def _team(vacancy: Vacancy) -> list[Membership]:
    """Who hears about a new applicant: everyone with `hr.hiring` who sees the vacancy."""
    people = (
        members_with_perm(vacancy.company, Perm.HR_HIRING)
        .select_related("user", "role", "company")
        .prefetch_related("branches")
    )
    return [
        person for person in people if scope.allows(scope.branch_ids(person), vacancy.branch_id)
    ]


def _notify_team(applicant: Applicant) -> None:
    inbox.notify(
        _team(applicant.vacancy),
        NEW_APPLICANT,
        title=lambda person: bot.new_applicant_title(applicant),
        body=lambda person: bot.new_applicant_body(applicant),
        url=queries.url(applicant),
        target=applicant,
        dedupe_key=f"{NEW_APPLICANT}:{applicant.pk}",
    )


# The pipeline ------------------------------------------------------------------------------


@transaction.atomic
def move(
    applicant: Applicant,
    stage: str,
    *,
    by: Membership,
    message: str = "",
    notify: bool | None = None,
) -> Applicant:
    """Move an applicant to another stage of the pipeline (also back, and back from a refusal).
    The applicant is told when invited to an interview or offered the job, and whenever there's
    a message for them; `notify` decides otherwise."""
    if stage == Stage.HIRED:
        raise DomainError(_("Use Hire to hire someone: it adds them to the team."))
    if stage == Stage.REJECTED:
        raise DomainError(_("Use Reject to turn someone down, with the reason."))
    if stage not in PIPELINE:
        raise DomainError(_("Pick a stage of the pipeline."))
    applicant = _lock_applicant(applicant)
    _ensure_may_run(by, applicant.vacancy)
    if applicant.stage == Stage.HIRED:
        raise DomainError(_("%(name)s is already hired.") % {"name": applicant.name})
    if applicant.stage == stage:
        return applicant
    message = _message(message)
    previous = applicant.stage
    applicant.stage = stage
    applicant.stage_changed_at = timezone.now()
    applicant.rejected_reason = ""
    applicant.save(update_fields=["stage", "stage_changed_at", "rejected_reason", "updated_at"])
    tell = notify if notify is not None else (stage in TOLD_BY_DEFAULT or bool(message))
    told = False
    if tell:
        render = {Stage.INTERVIEW: bot.invited, Stage.OFFER: bot.offered}.get(
            stage, bot.from_company
        )
        if render is bot.from_company and not message:
            told = False  # nothing to say about screening without a message
        else:
            told = _tell(applicant, partial(render, applicant, message))
    _event(applicant, by, previous, stage, message=message if told else "", told=told)
    audit.record(
        HiringAction.APPLICANT_MOVED,
        company_id=applicant.company_id,
        actor=by.user,
        target=applicant,
        stage=stage,
        was=previous,
        told=told,
    )
    _bump(applicant.company_id, PULSE_APPLICANTS, PULSE_VACANCIES)
    return applicant


@transaction.atomic
def reject(
    applicant: Applicant,
    *,
    by: Membership,
    reason: str,
    message: str = "",
    notify: bool = True,
) -> Applicant:
    """Turn an applicant down. `reason` is for the team; the applicant hears a kind refusal
    (with `message` when there is one) unless `notify` is False."""
    applicant = _lock_applicant(applicant)
    _ensure_may_run(by, applicant.vacancy)
    reason = " ".join((reason or "").split())
    if not reason:
        raise DomainError(_("Say why, for the team."))
    if len(reason) > REASON_MAX:
        raise DomainError(
            _("A reason can be at most %(count)d characters.") % {"count": REASON_MAX}
        )
    if applicant.stage == Stage.HIRED:
        raise DomainError(_("%(name)s is already hired.") % {"name": applicant.name})
    if applicant.stage == Stage.REJECTED:
        raise DomainError(_("%(name)s was already turned down.") % {"name": applicant.name})
    message = _message(message)
    previous = applicant.stage
    applicant.stage = Stage.REJECTED
    applicant.stage_changed_at = timezone.now()
    applicant.rejected_reason = reason
    applicant.save(update_fields=["stage", "stage_changed_at", "rejected_reason", "updated_at"])
    told = _tell(applicant, partial(bot.turned_down, applicant, message)) if notify else False
    _event(
        applicant,
        by,
        previous,
        Stage.REJECTED,
        text=reason,
        message=message if told else "",
        told=told,
    )
    audit.record(
        HiringAction.APPLICANT_REJECTED,
        company_id=applicant.company_id,
        actor=by.user,
        target=applicant,
        reason=reason,
        was=previous,
        told=told,
    )
    _bump(applicant.company_id, PULSE_APPLICANTS, PULSE_VACANCIES)
    return applicant


@transaction.atomic
def hire(applicant: Applicant, *, by: Membership, branch=None, message: str = "") -> Applicant:
    """Hire an applicant in one step: their join request, approved at once with the vacancy's
    position, its branch (or `branch`, when the vacancy has none) and the position's role. They
    are told in the bot, then get the usual welcome and create their account."""
    applicant = _lock_applicant(applicant)
    vacancy = applicant.vacancy
    company = vacancy.company
    _ensure_may_run(by, vacancy)
    if blocker := hire_blocker(by, vacancy):
        raise PermissionDenied(blocker)
    names = {"name": applicant.name}
    if applicant.stage == Stage.HIRED or applicant.membership_id is not None:
        raise DomainError(_("%(name)s is already hired.") % names)
    if applicant.stage == Stage.REJECTED:
        raise DomainError(
            _("%(name)s was turned down. Move them back to the pipeline first.") % names
        )
    user = applicant.user
    if user is None:
        raise DomainError(_("%(name)s's Telegram account is gone, so they can't join.") % names)
    position = vacancy.position
    if position is not None and not position.is_active:
        raise DomainError(_("The vacancy's position is no longer used. Choose another one first."))
    branch = branch or vacancy.branch
    if branch is not None:
        if branch.company_id != company.pk or not branch.is_active:
            raise DomainError(_("Pick a branch of this company."))
        if not scope.allows(scope.branch_ids(by), branch.pk):
            raise PermissionDenied(_("You can only choose the branches you manage."))
    elif company.branches.filter(is_active=True).count() > 1:
        raise DomainError(_("Choose the branch where %(name)s will work.") % names)
    if _works_here(company, user):
        raise DomainError(_("%(name)s already works here.") % names)

    membership, _created = members.request_access(user, company)
    if membership.status != Membership.Status.PENDING:
        if membership.status == Membership.Status.BLOCKED:
            raise DomainError(_("%(name)s is blocked in this company.") % names)
        raise DomainError(
            _("%(name)s was turned down as a member recently and can join again later.") % names
        )
    if not (membership.first_name or membership.last_name):
        first, _space, last = applicant.name.partition(" ")
        membership.first_name, membership.last_name = first[:100], last[:100]
        membership.save(update_fields=["first_name", "last_name", "updated_at"])
    message = _message(message)
    # Told before the approval queues its welcome, so the two messages come in that order.
    told = _tell(applicant, partial(bot.hired, applicant, message))
    role = members.title_role(position, company) if position is not None else None
    membership = members.approve(
        membership,
        by=by.user,
        role=role,
        position=position,
        branches=[branch] if branch is not None else None,
        home_branch=branch,
    )
    previous = applicant.stage
    now = timezone.now()
    applicant.stage = Stage.HIRED
    applicant.stage_changed_at = now
    applicant.hired_at = now
    applicant.membership = membership
    applicant.save(
        update_fields=["stage", "stage_changed_at", "hired_at", "membership", "updated_at"]
    )
    _event(applicant, by, previous, Stage.HIRED, message=message if told else "", told=told)
    audit.record(
        HiringAction.APPLICANT_HIRED,
        company_id=company.pk,
        actor=by.user,
        target=applicant,
        member=membership.pk,
        position=position.name if position is not None else "",
        branch=branch.name if branch is not None else "",
    )
    _bump(company.pk, PULSE_APPLICANTS, PULSE_VACANCIES)
    return applicant


def hire_blocker(by: Membership, vacancy: Vacancy) -> str | None:
    """Why `by` can't hire for `vacancy` (no right to let people in, or the position's role is
    one they may not give), or None; the dashboard shows it on the Hire button."""
    if not by.has_perm(Perm.MEMBERS_APPROVE):
        return _(
            "Hiring adds a person to the team, which needs the right to approve join requests."
        )
    if vacancy.position is not None:
        role = members.title_role(vacancy.position, vacancy.company)
        if role is not None and not members.may_assign_role(by, role):
            return _(
                "This position comes with the «%(role)s» access, which only someone holding all "
                "of its permissions can give. Ask an owner to hire."
            ) % {"role": role.name}
    return None


@transaction.atomic
def add_note(applicant: Applicant, *, by: Membership, text: str) -> ApplicantEvent:
    applicant = _lock_applicant(applicant)
    _ensure_may_run(by, applicant.vacancy)
    text = (text or "").strip()
    if not text:
        raise DomainError(_("Write the note first."))
    if len(text) > NOTE_MAX:
        raise DomainError(_("A note can be at most %(count)d characters.") % {"count": NOTE_MAX})
    event = ApplicantEvent.objects.create(
        company_id=applicant.company_id,
        applicant=applicant,
        kind=ApplicantEvent.Kind.NOTE,
        text=text,
        by=by,
    )
    audit.record(
        HiringAction.APPLICANT_NOTED,
        company_id=applicant.company_id,
        actor=by.user,
        target=applicant,
        note=event.pk,
    )
    _bump(applicant.company_id, PULSE_APPLICANTS)
    return event


def _event(applicant, by, previous, stage, *, text="", message="", told=False) -> ApplicantEvent:
    return ApplicantEvent.objects.create(
        company_id=applicant.company_id,
        applicant=applicant,
        kind=ApplicantEvent.Kind.MOVED,
        from_stage=previous,
        to_stage=stage,
        text=text,
        message=message,
        notified=told,
        by=by,
    )


def _message(value: str | None) -> str:
    message = (value or "").strip()
    if len(message) > MESSAGE_MAX:
        raise DomainError(
            _("A message can be at most %(count)d characters.") % {"count": MESSAGE_MAX}
        )
    return message


def _tell(applicant: Applicant, render) -> bool:
    """Send the applicant `render()` in the employee bot once this commits, in their language.
    False when there's nobody to send it to."""
    user = applicant.user
    if user is None or not user.telegram_id:
        return False
    with translation.override(user.language or applicant.language):
        text = render()
    chat_id = user.telegram_id
    transaction.on_commit(
        lambda: send_telegram_message.delay(BotName.EMPLOYEE, chat_id, text, None)
    )
    return True


# Checks and small helpers ------------------------------------------------------------------


def _ensure_hirer(by: Membership, company) -> None:
    if by.company_id != company.pk or not by.has_perm(Perm.HR_HIRING):
        raise PermissionDenied(_("You don't have permission to do this."))


def _ensure_may_run(by: Membership, vacancy: Vacancy) -> None:
    """`by` runs hiring and sees the vacancy's branch."""
    _ensure_hirer(by, vacancy.company)
    if not scope.allows(scope.branch_ids(by), vacancy.branch_id):
        raise PermissionDenied(_("You don't have permission to do this."))


def _lock_vacancy(vacancy: Vacancy) -> Vacancy:
    return (
        Vacancy.objects.select_for_update(of=("self",))
        .select_related("company", "branch", "position")
        .get(pk=vacancy.pk)
    )


def _lock_applicant(applicant: Applicant) -> Applicant:
    return (
        Applicant.objects.select_for_update(of=("self",))
        .select_related(
            "company", "vacancy__company", "vacancy__branch", "vacancy__position__role", "user"
        )
        .get(pk=applicant.pk)
    )


def _today(company):
    return timezone.localtime(timezone.now(), ZoneInfo(company.timezone)).date()


def _bump(company_id: int, *keys: str) -> None:
    transaction.on_commit(partial(pulse.bump, company_id, *keys))
