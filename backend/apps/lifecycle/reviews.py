"""Performance reviews (docs/PLAN-OWNER.md §13.4 "Reviews"): review rounds, the person's own
answers, their reviewer's part and the outcome.

- **A round** (`ReviewCycle`, reviews.manage) is a draft until it opens: a name, a period, who is
  in it (everyone, or some positions and/or branches, inside the opener's branch scope), 3-10
  questions (a rating from 1 to 5 or a text answer; `TEMPLATE` is a pharmacy's) and two
  deadlines.
- **Opening it** (`open_cycle`) makes a `Review` for everyone in it with their reviewer
  (`reviewer_for`: the nearest head above them who runs reviews, else their pharmacy's manager,
  else an owner) and tells each of them in the employee bot. The day before the self deadline
  whoever hasn't answered hears again; the day after it the reviewers' part begins (`advance`,
  also by hand), and the reviewers hear how many wait for them.
- **Self review**: `save_self` keeps the person's draft as they go, `send_self` sends it (every
  rating answered). Their answers stay hidden from the reviewer until the reviewers' part.
- **The reviewer's part**: `open_for_reviewer` takes the person's numbers for the period once
  (`review_kpis.snapshot`), so they never change later; `save_manager` keeps the draft (answers,
  rating, summary, outcome); `publish` checks it and turns the outcome into proposals that wait
  for the usual approval, then tells the person:
  - a raise: a pay job change from a day (apps.lifecycle.job_changes), the new pay counted from
    the pay in force and rounded like payroll rounds pay;
  - a promotion: a position job change (with a raise when one is given);
  - a bonus: a payroll adjustment on a month's payslip (`payroll.services.propose`);
  - an improvement plan: 1-3 goals (`ReviewGoal`) with their days.
  Nothing changes pay here: a raise and a bonus need someone who may propose pay
  (payroll.propose or payroll.manage), and everything waits for the approvals that already exist.
- The person reads the published review in the mini app and acknowledges it; the reviewer marks
  the goals as they go. `close_cycle` ends the round; what wasn't published stays unpublished.

Who sees what: rounds are for reviews.manage; a round's runner (whoever made it, an owner, or
someone with every branch in sight) sees everyone in it inside their branch scope, any other
reviewer only the people they review; a review's answers are read by its reviewer and owners.
"""

from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import partial
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.hr import queries as hr_queries
from apps.lifecycle import integrations, job_changes, review_kpis, tasks
from apps.lifecycle.audit_actions import LifecycleAction
from apps.lifecycle.models import Review, ReviewCycle, ReviewGoal, Termination
from apps.members import departments, scope
from apps.members.models import Membership, Position
from apps.members.permissions import Perm

Status = ReviewCycle.Status
Outcome = Review.Outcome
OPEN = (Status.SELF, Status.MANAGER)
PULSE = "lifecycle.reviews"
TO_WRITE = "lifecycle.reviews_to_write"
RATING, TEXT = "rating", "text"
KINDS = (RATING, TEXT)
RATINGS = range(1, 6)
MIN_QUESTIONS, MAX_QUESTIONS = 3, 10
MAX_NAME = 120
MAX_QUESTION = 300
MAX_ANSWER = 2000
MAX_SUMMARY = 2000
MAX_GOALS = 3
MAX_PERIOD_DAYS = 366
RAISE_MIN, RAISE_MAX = Decimal("0.5"), Decimal("50")
PAY_OUTCOMES = (Outcome.RAISE, Outcome.BONUS)
CHANGE_OUTCOMES = (Outcome.RAISE, Outcome.PROMOTION)
# The day-before reminders go out from this hour, in the company's time.
REMIND_AT = time(10, 0)
UNSET = object()

# A pharmacy's questions, ready to use (`key` keeps one in each reader's language until its
# words are changed). Never medical advice: these ask how the work was done.
TEMPLATE = (
    (
        "dispensing",
        RATING,
        gettext_lazy(
            "Dispensing and storage rules: prescriptions, expiry dates, the fridge and its log"
        ),
    ),
    (
        "customers",
        RATING,
        gettext_lazy("Customer care: polite and patient, clear answers at the counter"),
    ),
    (
        "cash",
        RATING,
        gettext_lazy("Cash discipline: the till balances and every sale gets its receipt"),
    ),
    (
        "teamwork",
        RATING,
        gettext_lazy("Teamwork: helping colleagues and handing over the shift properly"),
    ),
    (
        "learning",
        RATING,
        gettext_lazy("Learning: new medicines, the courses and the rules"),
    ),
    ("best", TEXT, gettext_lazy("What went best in this period?")),
    ("next", TEXT, gettext_lazy("What should get better next, and what help would it take?")),
)
TEMPLATE_TEXT = {key: text for key, _kind, text in TEMPLATE}
TEMPLATE_KIND = {key: kind for key, kind, _text in TEMPLATE}


# Questions -----------------------------------------------------------------------------------


def template() -> list[dict]:
    """The pharmacy's ready questions in the current language."""
    return [
        {"id": f"q{number}", "kind": kind, "text": str(text), "key": key}
        for number, (key, kind, text) in enumerate(TEMPLATE, start=1)
    ]


def question_text(question: dict) -> str:
    """A question's words for the reader: a template question in their language."""
    key = question.get("key") or ""
    if key in TEMPLATE_TEXT:
        return str(TEMPLATE_TEXT[key])
    return question.get("text") or ""


def shown_questions(cycle: ReviewCycle) -> list[dict]:
    return [
        {
            "id": question["id"],
            "kind": question["kind"],
            "text": question_text(question),
            "key": question.get("key") or "",
        }
        for question in cycle.questions or []
    ]


def _plain(text) -> str:
    return " ".join(str(text or "").split())


def clean_questions(raw) -> list[dict]:
    """3-10 questions, each a rating or a text, numbered q1…qN in order. A template question
    keeps its key only while its words and kind are the template's."""
    if not isinstance(raw, list) or not raw:
        raise DomainError(_("Add the questions."))
    if not MIN_QUESTIONS <= len(raw) <= MAX_QUESTIONS:
        raise DomainError(_("A round asks 3 to 10 questions."))
    found = []
    for number, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise DomainError(_("Add the questions."))
        kind = item.get("kind")
        if kind not in KINDS:
            raise DomainError(_("A question is a rating from 1 to 5 or a text answer."))
        text = _plain(item.get("text"))
        if not text:
            raise DomainError(_("Write every question."))
        if len(text) > MAX_QUESTION:
            raise DomainError(
                _("Keep each question under %(limit)s characters.") % {"limit": MAX_QUESTION}
            )
        key = str(item.get("key") or "")
        if (
            key not in TEMPLATE_TEXT
            or TEMPLATE_KIND[key] != kind
            or text != _plain(TEMPLATE_TEXT[key])
        ):
            key = ""
        found.append({"id": f"q{number}", "kind": kind, "text": text, "key": key})
    return found


def rating_ids(cycle: ReviewCycle) -> list[str]:
    return [question["id"] for question in cycle.questions or [] if question["kind"] == RATING]


def clean_answers(cycle: ReviewCycle, raw) -> dict:
    """{question id: {"rating", "text"}} of the round's questions (others are dropped): a rating
    is 1-5 (rating questions only), a text at most 2000 characters; empty answers are left out."""
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        raise DomainError(_("Answer the questions."))
    known = {question["id"]: question for question in cycle.questions or []}
    found = {}
    for question_id, value in raw.items():
        question = known.get(question_id)
        if question is None or not isinstance(value, dict):
            continue
        rating = value.get("rating")
        if rating in (None, "") or question["kind"] != RATING:
            rating = None
        else:
            try:
                rating = int(rating)
            except TypeError, ValueError:
                raise DomainError(_("A rating is a whole number from 1 to 5.")) from None
            if rating not in RATINGS:
                raise DomainError(_("A rating is a whole number from 1 to 5."))
        text = str(value.get("text") or "").strip()
        if len(text) > MAX_ANSWER:
            raise DomainError(
                _("Keep each answer under %(limit)s characters.") % {"limit": MAX_ANSWER}
            )
        if rating is None and not text:
            continue
        found[question_id] = {"rating": rating, "text": text}
    return found


def unanswered(cycle: ReviewCycle, answers: dict) -> list[str]:
    """The rating questions still without a rating."""
    return [
        question_id
        for question_id in rating_ids(cycle)
        if not (answers or {}).get(question_id, {}).get("rating")
    ]


def average(cycle: ReviewCycle, answers: dict) -> Decimal | None:
    """The mean of the ratings given, one decimal; None without any."""
    ratings = [
        (answers or {}).get(question_id, {}).get("rating") for question_id in rating_ids(cycle)
    ]
    ratings = [rating for rating in ratings if rating]
    if not ratings:
        return None
    return (Decimal(sum(ratings)) / Decimal(len(ratings))).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )


# Who may -------------------------------------------------------------------------------------


def _approved(member: Membership | None) -> bool:
    return member is not None and member.status == Membership.Status.APPROVED


def _is_owner(member: Membership | None) -> bool:
    return member is not None and member.role is not None and member.role.is_owner


def may_review(member: Membership | None) -> bool:
    """Gives reviews: approved, runs reviews and opens the dashboard."""
    return (
        _approved(member)
        and member.has_perm(Perm.REVIEWS_MANAGE)
        and member.has_perm(Perm.DASHBOARD_ACCESS)
    )


def may_run(member: Membership, cycle: ReviewCycle | None = None) -> bool:
    """Makes, opens, moves on, closes and reminds a round: reviews.manage; someone else's round
    only an owner or someone with every branch in sight."""
    if not _approved(member) or not member.has_perm(Perm.REVIEWS_MANAGE):
        return False
    if cycle is None or cycle.created_by_id == member.pk:
        return True
    return _is_owner(member) or scope.branch_ids(member) is None


def may_read(member: Membership, review: Review) -> bool:
    """A review's answers and outcome in the dashboard: its reviewer (who runs reviews) and
    owners; never one's own."""
    if not _approved(member) or member.company_id != review.company_id:
        return False
    if member.pk == review.membership_id:
        return False
    if _is_owner(member):
        return True
    return review.reviewer_id == member.pk and member.has_perm(Perm.REVIEWS_MANAGE)


def may_write(member: Membership, review: Review) -> bool:
    """The reviewer's part: its reviewer, while the round is in the reviewers' part and it isn't
    published."""
    return (
        review.reviewer_id == member.pk
        and may_read(member, review)
        and review.cycle.status == Status.MANAGER
        and review.published_at is None
    )


def may_propose_pay(member: Membership) -> bool:
    """Gives a raise or a bonus: someone who may propose pay, with payroll on."""
    return integrations.payroll_on(member.company) and (
        member.has_perm(Perm.PAYROLL_PROPOSE) or member.has_perm(Perm.PAYROLL_MANAGE)
    )


def self_visible(review: Review) -> bool:
    """The person's own answers reach their reviewer once the reviewers' part has begun."""
    return review.cycle.status in (Status.MANAGER, Status.CLOSED) or review.published_at is not None


def sees(member: Membership, person: Membership) -> bool:
    """Whether `member` may see `person`: inside their branch scope, or they manage them."""
    allowed = scope.branch_ids(member)
    if allowed is None:
        return True
    if person.branches.filter(pk__in=allowed).exists():
        return True
    return departments.manages(member, person)


def _ensure_run(cycle: ReviewCycle | None, by: Membership) -> None:
    if not may_run(by, cycle):
        raise PermissionDenied(_("You don't have permission to do this."))


# Who is in it and who reviews whom -----------------------------------------------------------


def audience(
    company,
    *,
    positions=(),
    branches=(),
    branch_ids: list[int] | None,
) -> QuerySet[Membership]:
    """Who a round takes in: approved people who finished joining, in `positions` and/or
    `branches` (none of either: everyone), inside `branch_ids`; owners and people whose last
    day is already agreed are left out."""
    rows = hr_queries.people(
        company, branch_ids=branch_ids, statuses=(Membership.Status.APPROVED,)
    ).filter(onboarded_at__isnull=False)
    rows = rows.exclude(role__is_owner=True)
    position_ids = [getattr(position, "pk", position) for position in positions]
    if position_ids:
        rows = rows.filter(position_id__in=position_ids)
    branch_list = [getattr(branch, "pk", branch) for branch in branches]
    if branch_list:
        rows = rows.filter(
            pk__in=Membership.objects.filter(company=company, branches__in=branch_list).values("pk")
        )
    leaving = Termination.objects.filter(company=company, status=Termination.Status.AGREED).values(
        "membership_id"
    )
    return rows.exclude(pk__in=leaving).order_by("first_name", "last_name", "pk")


def audience_of(cycle: ReviewCycle, *, branch_ids: list[int] | None) -> QuerySet[Membership]:
    return audience(
        cycle.company,
        positions=list(cycle.positions.values_list("pk", flat=True)),
        branches=list(cycle.branches.values_list("pk", flat=True)),
        branch_ids=branch_ids,
    )


def owners_of(company) -> list[Membership]:
    return list(
        Membership.objects.for_company(company)
        .filter(status=Membership.Status.APPROVED, role__is_owner=True)
        .select_related("role", "user", "company")
        .order_by("pk")
    )


def reviewer_for(
    person: Membership, *, org: departments.Org, owners: list[Membership]
) -> Membership | None:
    """Who reviews `person`: the nearest head above them (`departments.manager_of`) who runs
    reviews, else their home pharmacy's manager when they do, else the first owner."""
    head = departments.manager_of(person, org) if org else None
    seen: set[int] = set()
    while head is not None and head.pk not in seen:
        seen.add(head.pk)
        if head.pk != person.pk and may_review(head):
            return head
        head = org.head_above(head)
    branch = person.home_branch
    manager = branch.manager if branch is not None else None
    if manager is not None and manager.pk != person.pk and may_review(manager):
        return manager
    return next((owner for owner in owners if owner.pk != person.pk), None)


def preview(
    company, *, by: Membership, positions=(), branches=()
) -> list[tuple[Membership, Membership | None]]:
    """(person, their reviewer) for a round with these filters, as `by` would open it."""
    people = list(
        audience(company, positions=positions, branches=branches, branch_ids=scope.branch_ids(by))
        .select_related("user", "role", "position", "home_branch__manager__role", "company")
        .prefetch_related("branches")
    )
    org = departments.Org(company.pk)
    owners = owners_of(company)
    return [(person, reviewer_for(person, org=org, owners=owners)) for person in people]


# Rounds --------------------------------------------------------------------------------------


def _clean_name(value) -> str:
    name = _plain(value)
    if not name:
        raise DomainError(_("Name the round."))
    if len(name) > MAX_NAME:
        raise DomainError(_("Keep the name under %(limit)s characters.") % {"limit": MAX_NAME})
    return name


def _check_dates(cycle: ReviewCycle, *, today: date, opening: bool) -> None:
    if cycle.period_end < cycle.period_start:
        raise DomainError(_("The period has to end after it starts."))
    if (cycle.period_end - cycle.period_start).days > MAX_PERIOD_DAYS:
        raise DomainError(_("Keep the period within a year."))
    if cycle.manager_due_on < cycle.self_due_on:
        raise DomainError(_("The reviewers' deadline comes on or after the self-review deadline."))
    if opening and cycle.self_due_on < today:
        raise DomainError(_("The self-review deadline has passed: pick a later day."))
    if opening and cycle.self_due_on > today + timedelta(days=90):
        raise DomainError(_("Pick a self-review deadline within three months."))


def _positions(company, values) -> list[Position]:
    ids = [getattr(value, "pk", value) for value in values or []]
    found = list(Position.objects.filter(company=company, pk__in=ids))
    if len(found) != len(set(ids)):
        raise DomainError(_("Pick positions of this company."))
    return found


def _branches(company, values, *, by: Membership) -> list:
    from apps.companies.models import Branch

    ids = [getattr(value, "pk", value) for value in values or []]
    found = list(Branch.objects.filter(company=company, pk__in=ids))
    if len(found) != len(set(ids)):
        raise DomainError(_("Pick branches of this company."))
    allowed = scope.branch_ids(by)
    if allowed is not None and any(branch.pk not in allowed for branch in found):
        raise PermissionDenied(_("You can only take in the branches you manage."))
    return found


@transaction.atomic
def create_cycle(
    company,
    *,
    by: Membership,
    name: str,
    period_start: date,
    period_end: date,
    self_due_on: date,
    manager_due_on: date,
    questions,
    positions=(),
    branches=(),
) -> ReviewCycle:
    """A draft round; nobody hears of it until it opens."""
    _ensure_run(None, by)
    cycle = ReviewCycle(
        company=company,
        name=_clean_name(name),
        period_start=period_start,
        period_end=period_end,
        self_due_on=self_due_on,
        manager_due_on=manager_due_on,
        questions=clean_questions(questions),
        created_by=by,
    )
    _check_dates(cycle, today=hr_queries.today(company), opening=False)
    found_positions = _positions(company, positions)
    found_branches = _branches(company, branches, by=by)
    cycle.save()
    cycle.positions.set(found_positions)
    cycle.branches.set(found_branches)
    _audit_round(LifecycleAction.ROUND_CREATED, cycle, by)
    bump(company.pk)
    return cycle


@transaction.atomic
def update_cycle(cycle: ReviewCycle, *, by: Membership, **fields) -> ReviewCycle:
    """A draft changes freely; an open round only its name and deadlines (the self deadline
    while people still answer); a closed one not at all."""
    cycle = _lock_cycle(cycle)
    _ensure_run(cycle, by)
    if cycle.status == Status.CLOSED:
        raise DomainError(_("This review round is closed."))
    draft = cycle.status == Status.DRAFT
    allowed = {"name", "manager_due_on"}
    if draft:
        allowed |= {"period_start", "period_end", "self_due_on", "questions", "positions"}
        allowed |= {"branches"}
    elif cycle.status == Status.SELF:
        allowed.add("self_due_on")
    refused = set(fields) - allowed
    if refused:
        raise DomainError(_("Only the name and the deadlines change once a round is open."))
    changed = sorted(fields)
    if "name" in fields:
        cycle.name = _clean_name(fields["name"])
    for name in ("period_start", "period_end", "self_due_on", "manager_due_on"):
        if name in fields:
            setattr(cycle, name, fields[name])
    if "questions" in fields:
        cycle.questions = clean_questions(fields["questions"])
    today = hr_queries.today(cycle.company)
    _check_dates(cycle, today=today, opening=False)
    if not draft and "self_due_on" in fields and cycle.self_due_on < today:
        raise DomainError(_("The self-review deadline has passed: pick a later day."))
    if not draft and "manager_due_on" in fields and cycle.manager_due_on < today:
        raise DomainError(_("Pick a reviewers' deadline from today on."))
    if "self_due_on" in fields:
        cycle.self_reminded_on = None
    if "manager_due_on" in fields:
        cycle.manager_reminded_on = None
    cycle.save()
    if "positions" in fields:
        cycle.positions.set(_positions(cycle.company, fields["positions"]))
    if "branches" in fields:
        cycle.branches.set(_branches(cycle.company, fields["branches"], by=by))
    _audit_round(LifecycleAction.ROUND_CHANGED, cycle, by, fields=changed)
    bump(cycle.company_id)
    return cycle


@transaction.atomic
def delete_cycle(cycle: ReviewCycle, *, by: Membership) -> None:
    cycle = _lock_cycle(cycle)
    _ensure_run(cycle, by)
    if cycle.status != Status.DRAFT:
        raise DomainError(_("Only a draft round can be deleted; close an open one instead."))
    _audit_round(LifecycleAction.ROUND_REMOVED, cycle, by)
    company_id = cycle.company_id
    cycle.delete()
    bump(company_id)


@transaction.atomic
def open_cycle(cycle: ReviewCycle, *, by: Membership) -> ReviewCycle:
    """Open a draft: a review for everyone in it (inside `by`'s branch scope) with their
    reviewer, and each person hears in the employee bot."""
    cycle = _lock_cycle(cycle)
    _ensure_run(cycle, by)
    if cycle.status != Status.DRAFT:
        raise DomainError(_("This round is already open."))
    company = cycle.company
    _check_dates(cycle, today=hr_queries.today(company), opening=True)
    if not MIN_QUESTIONS <= len(cycle.questions or []) <= MAX_QUESTIONS:
        raise DomainError(_("A round asks 3 to 10 questions."))
    people = list(
        audience_of(cycle, branch_ids=scope.branch_ids(by)).select_related(
            "user", "role", "company", "home_branch__manager__role"
        )
    )
    if not people:
        raise DomainError(_("Nobody is in this round: pick other positions or branches."))
    org = departments.Org(company.pk)
    owners = owners_of(company)
    Review.objects.bulk_create(
        [
            Review(
                company=company,
                cycle=cycle,
                membership=person,
                reviewer=reviewer_for(person, org=org, owners=owners),
                bonus_currency=company.base_currency,
            )
            for person in people
        ]
    )
    cycle.status = Status.SELF
    cycle.opened_at = timezone.now()
    cycle.opened_by = by
    cycle.save(update_fields=["status", "opened_at", "opened_by", "updated_at"])
    _audit_round(LifecycleAction.ROUND_OPENED, cycle, by, people=len(people))
    transaction.on_commit(partial(tasks.notify_review_round_opened.delay, cycle.pk))
    bump(company.pk, to_write=True)
    return cycle


@transaction.atomic
def advance(cycle: ReviewCycle, *, by: Membership | None = None) -> ReviewCycle:
    """The reviewers' part begins (by hand, or the day after the self deadline): the people's
    answers reach their reviewers, who hear how many reviews wait for them."""
    cycle = _lock_cycle(cycle)
    if by is not None:
        _ensure_run(cycle, by)
    if cycle.status != Status.SELF:
        raise DomainError(_("Only a round in its self-review part can move on."))
    cycle.status = Status.MANAGER
    cycle.manager_at = timezone.now()
    cycle.save(update_fields=["status", "manager_at", "updated_at"])
    _audit_round(LifecycleAction.ROUND_ADVANCED, cycle, by)
    transaction.on_commit(partial(tasks.notify_review_stage.delay, cycle.pk))
    bump(cycle.company_id, to_write=True)
    return cycle


@transaction.atomic
def close_cycle(cycle: ReviewCycle, *, by: Membership) -> ReviewCycle:
    """End an open round: published reviews stay as they are, the others stay unpublished."""
    cycle = _lock_cycle(cycle)
    _ensure_run(cycle, by)
    if cycle.status not in OPEN:
        raise DomainError(_("Only an open round can be closed."))
    unpublished = cycle.reviews.filter(published_at__isnull=True).count()
    cycle.status = Status.CLOSED
    cycle.closed_at = timezone.now()
    cycle.closed_by = by
    cycle.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
    _audit_round(LifecycleAction.ROUND_CLOSED, cycle, by, unpublished=unpublished)
    bump(cycle.company_id, to_write=True)
    return cycle


def late(cycle: ReviewCycle, rows, *, today: date) -> dict[int, list[str]]:
    """{review id: what is late}: "self" past the self deadline without the person's answers,
    "manager" past the reviewers' deadline unpublished."""
    found: dict[int, list[str]] = {}
    self_over = cycle.status != Status.DRAFT and today > cycle.self_due_on
    manager_over = cycle.status == Status.MANAGER and today > cycle.manager_due_on
    for review in rows:
        if review.published_at is not None:
            continue
        parts = []
        if self_over and review.self_sent_at is None:
            parts.append("self")
        if manager_over:
            parts.append("manager")
        if parts:
            found[review.pk] = parts
    return found


def remind(cycle: ReviewCycle, *, by: Membership, rows=None) -> dict:
    """Nudge whoever is behind, once a day each: in the self part the people who haven't sent
    their answers; in the reviewers' part those people still, and the reviewers with reviews
    to publish. `rows` narrows it to the reviews the runner sees. Returns how many heard."""
    _ensure_run(cycle, by)
    if cycle.status not in OPEN:
        raise DomainError(_("Only an open round sends reminders."))
    rows = rows if rows is not None else cycle.reviews.all()
    waiting = list(rows.filter(published_at__isnull=True))
    people = [review.pk for review in waiting if review.self_sent_at is None]
    reviewers = sorted(
        {
            review.reviewer_id
            for review in waiting
            if review.reviewer_id and cycle.status == Status.MANAGER
        }
    )
    if not people and not reviewers:
        raise DomainError(_("Nobody is behind: there is nobody to remind."))
    now = timezone.now()
    Review.objects.filter(pk__in=[review.pk for review in waiting]).update(
        reminded_at=now, updated_at=now
    )
    _audit_round(
        LifecycleAction.ROUND_CHANGED,
        cycle,
        by,
        reminded=len(people),
        reviewers=len(reviewers),
    )
    transaction.on_commit(partial(tasks.notify_review_nudge.delay, cycle.pk, people, reviewers))
    bump(cycle.company_id)
    return {"people": len(people), "reviewers": len(reviewers)}


def run_due(now: datetime | None = None) -> int:
    """The job (every 15 minutes, in each company's time): the day-before reminders from 10:00,
    and the reviewers' part from the day after the self deadline. Idempotent: each reminder
    goes out once (the day is kept on the round), a round moves on once. Returns how many
    rounds it touched."""
    now = now or timezone.now()
    touched = 0
    rows = ReviewCycle.objects.filter(status__in=OPEN, company__is_active=True).select_related(
        "company"
    )
    for cycle in rows:
        company = cycle.company
        if not company.has_feature("hr"):
            continue
        local = timezone.localtime(now, ZoneInfo(company.timezone))
        today = local.date()
        if cycle.status == Status.SELF:
            if today > cycle.self_due_on:
                advance(cycle)
                touched += 1
                continue
            field = "self_reminded_on"
            due = _remind_now(cycle.self_reminded_on, cycle.self_due_on, cycle.opened_at, local)
        else:
            field = "manager_reminded_on"
            due = _remind_now(
                cycle.manager_reminded_on, cycle.manager_due_on, cycle.manager_at, local
            )
        if due and _mark(cycle, field, today):
            transaction.on_commit(partial(tasks.notify_review_reminders.delay, cycle.pk))
            touched += 1
    return touched


def _remind_now(sent_on: date | None, deadline: date, began: datetime | None, local) -> bool:
    """A part's day-before reminder is due: not sent yet, from 10:00 the day before its
    deadline until the deadline, and the part didn't begin that day or later (they just
    heard)."""
    today = local.date()
    eve = deadline - timedelta(days=1)
    if sent_on is not None or today > deadline or today < eve:
        return False
    if today == eve and local.time() < REMIND_AT:
        return False
    began_on = timezone.localtime(began, local.tzinfo).date() if began else today
    return began_on < eve


def _mark(cycle: ReviewCycle, field: str, day: date) -> bool:
    """Set the reminder day once (another run may have done it meanwhile)."""
    return bool(
        ReviewCycle.objects.filter(pk=cycle.pk, **{f"{field}__isnull": True}).update(
            **{field: day, "updated_at": timezone.now()}
        )
    )


# The person's part ---------------------------------------------------------------------------


def _ensure_self(review: Review, by: Membership) -> None:
    if by.pk != review.membership_id:
        raise PermissionDenied(_("You don't have permission to do this."))
    if by.status != Membership.Status.APPROVED:
        raise DomainError(_("Your access is paused, so this can't change now."))
    if review.cycle.status not in OPEN:
        raise DomainError(_("This review round is closed."))
    if review.published_at is not None:
        raise DomainError(_("Your review is already published."))
    if review.self_sent_at is not None:
        raise DomainError(_("You have already sent your answers."))


@transaction.atomic
def save_self(review: Review, *, by: Membership, answers) -> Review:
    """Keep the person's answers as they go (a draft only they see)."""
    review = _lock(review)
    _ensure_self(review, by)
    review.self_answers = clean_answers(review.cycle, answers)
    review.self_saved_at = timezone.now()
    review.save(update_fields=["self_answers", "self_saved_at", "updated_at"])
    return review


@transaction.atomic
def send_self(review: Review, *, by: Membership, answers=None) -> Review:
    """Send the person's answers: every rating given. They can't change after that."""
    review = _lock(review)
    _ensure_self(review, by)
    if answers is not None:
        review.self_answers = clean_answers(review.cycle, answers)
    if unanswered(review.cycle, review.self_answers):
        raise DomainError(_("Give every rating before you send."))
    now = timezone.now()
    review.self_saved_at = now
    review.self_sent_at = now
    review.save(update_fields=["self_answers", "self_saved_at", "self_sent_at", "updated_at"])
    late = hr_queries.today(review.company) > review.cycle.self_due_on
    _audit(LifecycleAction.REVIEW_SENT, review, by, late=late)
    bump(review.company_id)
    return review


@transaction.atomic
def acknowledge(review: Review, *, by: Membership) -> Review:
    """The person has read their published review."""
    review = _lock(review)
    if by.pk != review.membership_id:
        raise PermissionDenied(_("You don't have permission to do this."))
    if by.status != Membership.Status.APPROVED:
        raise DomainError(_("Your access is paused, so this can't change now."))
    if review.published_at is None:
        raise DomainError(_("Your review isn't published yet."))
    if review.acknowledged_at is None:
        review.acknowledged_at = timezone.now()
        review.save(update_fields=["acknowledged_at", "updated_at"])
        _audit(LifecycleAction.REVIEW_ACKNOWLEDGED, review, by)
        bump(review.company_id)
    return review


# The reviewer's part -------------------------------------------------------------------------


def open_for_reviewer(review: Review, *, by: Membership) -> Review:
    """The reviewer opens the review in the reviewers' part: the person's numbers for the period
    are taken now, once, and kept on it."""
    if review.kpis_at is not None or not may_write(by, review):
        return review
    with transaction.atomic():
        review = _lock(review)
        if review.kpis_at is None:
            _take_kpis(review)
            review.save(update_fields=["kpis", "kpis_at", "updated_at"])
    return review


def _take_kpis(review: Review) -> None:
    now = timezone.now()
    review.kpis = review_kpis.snapshot(review, now)
    review.kpis_at = now


def _ensure_write(review: Review, by: Membership) -> None:
    if not may_read(by, review) or review.reviewer_id != by.pk:
        raise PermissionDenied(_("Only the person's reviewer writes this review."))
    if review.published_at is not None:
        raise DomainError(_("This review is published, so it can't change."))
    status = review.cycle.status
    if status == Status.SELF:
        raise DomainError(_("Your part opens once the self reviews are in."))
    if status != Status.MANAGER:
        raise DomainError(_("This review round is closed."))


def _percent(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        percent = Decimal(str(value).strip().replace(",", ".")).quantize(Decimal("0.01"))
    except InvalidOperation, ValueError:
        raise DomainError(_("Give the raise as a percentage.")) from None
    if not percent.is_finite() or not RAISE_MIN <= percent <= RAISE_MAX:
        raise DomainError(_("A raise is from 0.5 to 50 percent."))
    return percent


def _money(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value).strip().replace(" ", "").replace(",", ".")).quantize(
            Decimal("0.01")
        )
    except InvalidOperation, ValueError:
        raise DomainError(_("Enter an amount of money.")) from None
    if not amount.is_finite() or amount <= 0:
        raise DomainError(_("Enter an amount of money."))
    return amount


def _clean_goals(review: Review, raw) -> list[dict]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise DomainError(_("Add the goals."))
    if len(raw) > MAX_GOALS:
        raise DomainError(_("An improvement plan has at most three goals."))
    found = []
    for item in raw:
        if not isinstance(item, dict):
            raise DomainError(_("Add the goals."))
        title = _plain(item.get("title"))
        due_on = item.get("due_on")
        if isinstance(due_on, str) and due_on:
            try:
                due_on = date.fromisoformat(due_on)
            except ValueError:
                raise DomainError(_("Give a day as YYYY-MM-DD.")) from None
        if not title and not due_on:
            continue
        if len(title) > 200:
            raise DomainError(_("Keep each goal under 200 characters."))
        target = item.get("target")
        try:
            target = (
                None
                if target in (None, "")
                else Decimal(str(target).replace(",", ".")).quantize(Decimal("0.01"))
            )
        except InvalidOperation, ValueError:
            raise DomainError(_("A goal's target is a number.")) from None
        found.append(
            {
                "title": title,
                "due_on": due_on or None,
                "target": target,
                "unit": _plain(item.get("unit"))[:30],
            }
        )
    return found


@transaction.atomic
def save_manager(review: Review, *, by: Membership, **fields) -> Review:
    """Keep the reviewer's draft: `answers`, `rating` (1-5), `summary`, `outcome` with its
    details (`raise_percent`, `bonus_amount`, `promotion_position`, `effective_on`) and the
    plan's `goals`. Checked fully only when published."""
    review = _lock(review)
    _ensure_write(review, by)
    if review.kpis_at is None:
        _take_kpis(review)
    if "answers" in fields:
        review.manager_answers = clean_answers(review.cycle, fields["answers"])
    if "rating" in fields:
        rating = fields["rating"]
        if rating in (None, ""):
            review.rating = None
        else:
            try:
                rating = int(rating)
            except TypeError, ValueError:
                raise DomainError(_("A rating is a whole number from 1 to 5.")) from None
            if rating not in RATINGS:
                raise DomainError(_("A rating is a whole number from 1 to 5."))
            review.rating = rating
    if "summary" in fields:
        summary = str(fields["summary"] or "").strip()
        if len(summary) > MAX_SUMMARY:
            raise DomainError(
                _("Keep the summary under %(limit)s characters.") % {"limit": MAX_SUMMARY}
            )
        review.summary = summary
    if "outcome" in fields:
        outcome = fields["outcome"] or Outcome.NONE
        if outcome not in Outcome.values:
            raise DomainError(_("Pick what follows from the review."))
        if outcome in PAY_OUTCOMES and not may_propose_pay(by):
            raise PermissionDenied(
                _("Only people who may propose pay can give a raise or a bonus.")
            )
        review.outcome = outcome
    if "raise_percent" in fields:
        review.raise_percent = _percent(fields["raise_percent"])
        if review.raise_percent is not None and not may_propose_pay(by):
            raise PermissionDenied(
                _("Only people who may propose pay can give a raise or a bonus.")
            )
    if "bonus_amount" in fields:
        review.bonus_amount = _money(fields["bonus_amount"])
    if "promotion_position" in fields:
        position = fields["promotion_position"]
        if position is not None and (
            position.company_id != review.company_id or not position.is_active
        ):
            raise DomainError(_("Pick a position of this company."))
        review.promotion_position = position
    if "effective_on" in fields:
        review.effective_on = fields["effective_on"] or None
    if "goals" in fields:
        goals = _clean_goals(review, fields["goals"])
        review.goals.all().delete()
        ReviewGoal.objects.bulk_create(
            [
                ReviewGoal(
                    company_id=review.company_id,
                    membership_id=review.membership_id,
                    review=review,
                    title=goal["title"],
                    due_on=goal["due_on"] or review.cycle.manager_due_on,
                    target=goal["target"],
                    unit=goal["unit"],
                    order=order,
                )
                for order, goal in enumerate(goals)
            ]
        )
    review.manager_saved_at = timezone.now()
    review.save()
    bump(review.company_id)
    return review


def new_pay(person: Membership, percent: Decimal, *, on: date) -> dict:
    """The pay after a raise of `percent` on the pay in force on `on`, rounded to payroll's
    rounding step: {"now", "after", "currency", "pay_type"} (amounts as Decimals)."""
    current = integrations.current_pay(person, on=on)
    if current is None:
        raise DomainError(
            _(
                "%(name)s has no pay set in Payroll, so a raise can't be counted: set their pay "
                "first, or give a bonus."
            )
            % {"name": person}
        )
    now = Decimal(current["amount"])
    after = round_pay(person.company, now * (Decimal(100) + percent) / Decimal(100))
    return {
        "now": now,
        "after": after,
        "currency": current["currency"],
        "pay_type": current["pay_type"],
    }


def rounding_step(company) -> Decimal:
    from apps.payroll import conf

    step = conf.get_settings(company).rounding_step or Decimal(0)
    return step if step > 0 else Decimal("0.01")


def round_pay(company, amount: Decimal) -> Decimal:
    step = rounding_step(company)
    return ((amount / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step).quantize(
        Decimal("0.01")
    )


def _reason(review: Review) -> str:
    """Why the job change or the bonus is proposed, for whoever approves it."""
    values = {"name": review.cycle.name, "rating": review.rating}
    return _("Performance review «%(name)s»: rated %(rating)s of 5.") % values


def _check_outcome(review: Review, by: Membership, *, today: date) -> None:
    outcome = review.outcome
    touches_pay = outcome in PAY_OUTCOMES or (outcome == Outcome.PROMOTION and review.raise_percent)
    if touches_pay and not may_propose_pay(by):
        raise PermissionDenied(_("Only people who may propose pay can give a raise or a bonus."))
    if outcome == Outcome.RAISE and review.raise_percent is None:
        raise DomainError(_("Give the raise as a percentage."))
    if outcome == Outcome.PROMOTION and review.promotion_position_id is None:
        raise DomainError(_("Pick the position they are promoted to."))
    if (
        outcome == Outcome.PROMOTION
        and review.promotion_position_id == review.membership.position_id
    ):
        raise DomainError(_("They already hold this position: pick another one."))
    if outcome in CHANGE_OUTCOMES:
        if review.effective_on is None:
            raise DomainError(_("Pick the day it starts."))
        if review.effective_on < today:
            raise DomainError(_("A change starts today or later."))
    if outcome == Outcome.BONUS and review.bonus_amount is None:
        raise DomainError(_("Enter the bonus."))
    if outcome == Outcome.PLAN:
        goals = list(review.goals.all())
        if not goals:
            raise DomainError(_("An improvement plan needs one to three goals."))
        for goal in goals:
            if not goal.title:
                raise DomainError(_("Name every goal."))
            if goal.due_on < today:
                raise DomainError(_("A goal's day is today or later."))


def _propose(review: Review, by: Membership, *, today: date) -> None:
    """Turn the outcome into what waits for approval: a job change or a payroll bonus."""
    person = review.membership
    reason = _reason(review)
    outcome = review.outcome
    if outcome in CHANGE_OUTCOMES:
        fields = {}
        if outcome == Outcome.PROMOTION:
            fields["position"] = review.promotion_position
        if review.raise_percent:
            pay = new_pay(person, review.raise_percent, on=review.effective_on)
            fields["pay_amount"] = pay["after"]
        review.job_change = job_changes.propose(
            person,
            by=by,
            effective_on=review.effective_on,
            reason=reason,
            review=True,
            **fields,
        )
    elif outcome == Outcome.BONUS:
        from apps.payroll import services as payroll

        month = (review.effective_on or today).replace(day=1)
        adjustment = payroll.propose(
            person,
            by=by,
            kind="bonus",
            amount=review.bonus_amount,
            reason=reason[:300],
            period=month,
        )
        review.bonus_id = adjustment.pk
        review.effective_on = month


@transaction.atomic
def publish(review: Review, *, by: Membership) -> Review:
    """The reviewer is done: every question rated, the overall rating given and the outcome
    complete. The outcome becomes its proposals (waiting for approval), the person hears, and
    the review can't change any more."""
    review = _lock(review)
    _ensure_write(review, by)
    cycle = review.cycle
    if unanswered(cycle, review.manager_answers):
        raise DomainError(_("Rate every question first."))
    if review.rating is None:
        raise DomainError(_("Give the overall rating."))
    today = hr_queries.today(review.company)
    # What another outcome left behind in the draft goes.
    if review.outcome != Outcome.PROMOTION:
        review.promotion_position = None
    if review.outcome not in CHANGE_OUTCOMES:
        review.raise_percent = None
    if review.outcome != Outcome.BONUS:
        review.bonus_amount = None
    if review.outcome in (Outcome.NONE, Outcome.PLAN):
        review.effective_on = None
    _check_outcome(review, by, today=today)
    if review.outcome != Outcome.PLAN:
        review.goals.all().delete()
    if review.kpis_at is None:
        _take_kpis(review)
    _propose(review, by, today=today)
    review.published_at = timezone.now()
    review.published_by = by
    review.save()
    _audit(
        LifecycleAction.REVIEW_PUBLISHED,
        review,
        by,
        rating=review.rating,
        outcome=review.outcome,
    )
    transaction.on_commit(partial(tasks.notify_review_published.delay, review.pk))
    bump(review.company_id, to_write=True)
    return review


# A round's runner: who gives a review, who is in it --------------------------------------------


@transaction.atomic
def reassign(review: Review, *, by: Membership, reviewer: Membership) -> Review:
    """Someone else gives this review (it isn't published yet)."""
    review = _lock(review)
    _ensure_run(review.cycle, by)
    if review.published_at is not None:
        raise DomainError(_("This review is published, so it can't change."))
    if review.cycle.status == Status.CLOSED:
        raise DomainError(_("This review round is closed."))
    person = review.membership
    if reviewer.company_id != review.company_id or not may_review(reviewer):
        raise DomainError(_("Pick someone who runs reviews."))
    if reviewer.pk == person.pk:
        raise DomainError(_("Nobody reviews themselves."))
    if not sees(reviewer, person):
        raise DomainError(_("%(name)s doesn't see this person's branch.") % {"name": reviewer})
    was = review.reviewer
    review.reviewer = reviewer
    review.save(update_fields=["reviewer", "updated_at"])
    _audit(
        LifecycleAction.REVIEW_REASSIGNED,
        review,
        by,
        reviewer=[str(was) if was else None, str(reviewer)],
    )
    bump(review.company_id, to_write=True)
    return review


@transaction.atomic
def remove(review: Review, *, by: Membership) -> None:
    """Take someone out of a round (before their review is published)."""
    review = _lock(review)
    _ensure_run(review.cycle, by)
    if review.published_at is not None:
        raise DomainError(_("This review is published, so it can't change."))
    if review.cycle.status == Status.CLOSED:
        raise DomainError(_("This review round is closed."))
    _audit(LifecycleAction.REVIEW_REMOVED, review, by)
    company_id = review.company_id
    review.delete()
    bump(company_id, to_write=True)


# Goals ---------------------------------------------------------------------------------------


@transaction.atomic
def update_goal(goal: ReviewGoal, *, by: Membership, **fields) -> ReviewGoal:
    """The reviewer (or an owner) marks a published plan's goal: `progress`, `status`, `note`."""
    goal = (
        ReviewGoal.objects.select_for_update(of=("self",))
        .select_related("review__cycle", "review__membership", "company")
        .get(pk=goal.pk)
    )
    review = goal.review
    if not may_read(by, review):
        raise PermissionDenied(_("You don't have permission to do this."))
    if review.published_at is None:
        raise DomainError(_("Goals are marked once the review is published."))
    changed = []
    if "progress" in fields:
        value = fields["progress"]
        try:
            goal.progress = (
                None
                if value in (None, "")
                else Decimal(str(value).replace(",", ".")).quantize(Decimal("0.01"))
            )
        except InvalidOperation, ValueError:
            raise DomainError(_("Progress is a number.")) from None
        changed.append("progress")
    if "status" in fields:
        status = fields["status"]
        if status not in ReviewGoal.Status.values:
            raise DomainError(_("Pick how the goal went."))
        if status != goal.status:
            goal.status = status
            goal.closed_at = None if status == ReviewGoal.Status.OPEN else timezone.now()
            changed.append("status")
    if "note" in fields:
        goal.note = _plain(fields["note"])[:300]
        changed.append("note")
    goal.save()
    _audit(LifecycleAction.GOAL_CHANGED, review, by, goal=goal.pk, status=goal.status)
    bump(goal.company_id)
    return goal


# Shared --------------------------------------------------------------------------------------


def _lock_cycle(cycle: ReviewCycle) -> ReviewCycle:
    return (
        ReviewCycle.objects.select_for_update(of=("self",))
        .select_related("company", "created_by")
        .get(pk=cycle.pk)
    )


def _lock(review: Review) -> Review:
    return (
        Review.objects.select_for_update(of=("self",))
        .select_related(
            "company",
            "cycle__company",
            "membership__company",
            "membership__role",
            "membership__user",
            "membership__position",
            "membership__home_branch",
            "reviewer__role",
            "reviewer__user",
            "reviewer__company",
            "promotion_position",
        )
        .get(pk=review.pk)
    )


def _audit(action: str, review: Review, by: Membership | None, /, **details) -> None:
    """On the person (their history), for people who run reviews; never an answer."""
    details.setdefault("review", review.pk)
    details.setdefault("round", review.cycle_id)
    audit.record(
        action,
        company_id=review.company_id,
        actor=by.user if by is not None else None,
        target=review.membership,
        required_perm=Perm.REVIEWS_MANAGE,
        **details,
    )


def _audit_round(action: str, cycle: ReviewCycle, by: Membership | None, /, **details) -> None:
    details.setdefault("round", cycle.pk)
    audit.record(
        action,
        company_id=cycle.company_id,
        actor=by.user if by is not None else None,
        target=cycle,
        required_perm=Perm.REVIEWS_MANAGE,
        **details,
    )


def bump(company_id: int, *, to_write: bool = False) -> None:
    keys = (PULSE, TO_WRITE) if to_write else (PULSE,)
    transaction.on_commit(partial(pulse.bump, company_id, *keys))
