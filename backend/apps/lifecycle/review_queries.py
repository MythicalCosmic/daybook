"""Read functions of performance reviews: the rounds and reviews a member may see, a round's
progress and results, the reviews waiting for a reviewer, the company calendar's deadlines and
the export (docs/PLAN-OWNER.md §13.4 "Reviews").

A round's runner (`reviews.may_run`) sees the reviews of everyone in it inside their branch
scope, and the ones they give; any other reviewer only the ones they give. Pay (the cost of the
raises, a bonus) shows only with payroll.view.
"""

from collections import Counter
from datetime import date
from decimal import Decimal

from django.db.models import Q, QuerySet
from django.utils.translation import gettext as _

from apps.console.registry import CalendarItem
from apps.hr import queries as hr_queries
from apps.lifecycle import reviews
from apps.lifecycle.models import JobChange, Review, ReviewCycle, ReviewGoal
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

REVIEW_RELATIONS = (
    "cycle__company",
    "company",
    "membership__user",
    "membership__company",
    "membership__role",
    "membership__position",
    "membership__home_branch",
    "reviewer__user",
    "reviewer__role",
    "reviewer__company",
    "promotion_position",
    "job_change",
)


def cycles_for(member: Membership) -> QuerySet[ReviewCycle]:
    """The rounds of `member`'s company for someone who runs reviews: drafts only their own
    (or every one, for whoever may run anyone's), open and closed ones all."""
    rows = ReviewCycle.objects.for_company(member.company)
    if not member.has_perm(Perm.REVIEWS_MANAGE):
        return rows.none()
    runs_all = scope.branch_ids(member) is None or reviews._is_owner(member)
    if not runs_all:
        rows = rows.filter(~Q(status=ReviewCycle.Status.DRAFT) | Q(created_by=member))
    return rows


def visible_reviews(member: Membership, cycle: ReviewCycle) -> QuerySet[Review]:
    """The reviews of `cycle` on `member`'s round page."""
    rows = Review.objects.filter(cycle=cycle)
    if reviews.may_run(member, cycle):
        branch_ids = scope.branch_ids(member)
        if branch_ids is None:
            return rows
        people = hr_queries.people(
            cycle.company, branch_ids=branch_ids, statuses=hr_queries.EMPLOYED
        ).values("pk")
        return rows.filter(Q(membership_id__in=people) | Q(reviewer=member))
    return rows.filter(reviewer=member)


def progress(cycle: ReviewCycle, rows, *, today: date) -> dict:
    """How far `rows` (reviews of `cycle`) have got: people, self answers sent, published,
    acknowledged, late (either part) and waiting for their reviewer."""
    rows = list(rows)
    late = reviews.late(cycle, rows, today=today)
    return {
        "people": len(rows),
        "self_sent": sum(1 for review in rows if review.self_sent_at is not None),
        "published": sum(1 for review in rows if review.published_at is not None),
        "acknowledged": sum(1 for review in rows if review.acknowledged_at is not None),
        "late": len(late),
        "self_late": sum(1 for parts in late.values() if "self" in parts),
        "manager_late": sum(1 for parts in late.values() if "manager" in parts),
    }


def to_write(member: Membership) -> QuerySet[Review]:
    """Reviews waiting for `member` as their reviewer (the reviewers' part, unpublished)."""
    return Review.objects.filter(
        company_id=member.company_id,
        reviewer=member,
        published_at__isnull=True,
        cycle__status=ReviewCycle.Status.MANAGER,
    )


def to_write_count(member: Membership) -> int:
    if not member.has_perm(Perm.REVIEWS_MANAGE):
        return 0
    return to_write(member).count()


# Outcome states ------------------------------------------------------------------------------


def adjustments(company, ids) -> dict[int, dict]:
    """{adjustment id: {id, amount, currency, status, period}} of review bonuses in payroll."""
    ids = [pk for pk in ids if pk]
    if not ids or not company.has_feature("payroll"):
        return {}
    from apps.payroll.models import Adjustment

    return {
        row.pk: {
            "id": row.pk,
            "amount": f"{row.amount:.2f}",
            "currency": row.currency,
            "status": row.status,
            "period": row.period.isoformat(),
        }
        for row in Adjustment.objects.filter(company=company, pk__in=ids)
    }


def outcome_state(review: Review, bonuses: dict[int, dict]) -> str | None:
    """Where the outcome stands: "waiting" (for approval), "approved", "applied", "rejected", or
    None (nothing to approve)."""
    if review.outcome in reviews.CHANGE_OUTCOMES and review.job_change is not None:
        status = review.job_change.status
        if status == JobChange.Status.PROPOSED:
            return "waiting"
        if status == JobChange.Status.APPROVED:
            return "approved"
        if status == JobChange.Status.APPLIED:
            return "applied"
        return "rejected"
    if review.outcome == Review.Outcome.BONUS and review.bonus_id:
        bonus = bonuses.get(review.bonus_id)
        if bonus is None:
            return None
        return {"proposed": "waiting", "approved": "approved"}.get(bonus["status"], "rejected")
    return None


# Results -------------------------------------------------------------------------------------


def _raise_cost(review: Review) -> Decimal | None:
    """What a raise adds to the monthly pay (monthly pay only), from its job change."""
    change = review.job_change
    if change is None or "pay" not in (change.parts or []):
        return None
    before = (change.before or {}).get("pay") or {}
    after = (change.after or {}).get("pay") or {}
    if not before or not after or after.get("pay_type") != "monthly":
        return None
    return Decimal(after["amount"]) - Decimal(before["amount"])


def results(cycle: ReviewCycle, rows, *, member: Membership) -> dict:
    """What the published reviews of `rows` came to: the rating spread and average, the
    outcomes, per question the people's and the reviewers' average, by branch; the cost of the
    raises (a month) and the bonuses for payroll.view."""
    published = [review for review in rows if review.published_at is not None]
    pay = member.has_perm(Perm.PAYROLL_VIEW)
    bonuses = adjustments(cycle.company, [review.bonus_id for review in published])
    spread = Counter(review.rating for review in published if review.rating)
    ratings = [review.rating for review in published if review.rating]
    outcomes = Counter(review.outcome for review in published)
    questions = []
    for question in reviews.shown_questions(cycle):
        if question["kind"] != reviews.RATING:
            continue
        mine = [
            (review.self_answers or {}).get(question["id"], {}).get("rating")
            for review in published
            if review.self_sent_at is not None
        ]
        theirs = [
            (review.manager_answers or {}).get(question["id"], {}).get("rating")
            for review in published
        ]
        questions.append(
            {
                "id": question["id"],
                "text": question["text"],
                "self_average": _mean(mine),
                "manager_average": _mean(theirs),
            }
        )
    branches: dict[int | None, dict] = {}
    raises = {"approved": Decimal(0), "waiting": Decimal(0)}
    bonus_total = {"approved": Decimal(0), "waiting": Decimal(0)}
    currency = cycle.company.base_currency
    for review in published:
        branch = review.membership.home_branch
        key = branch.pk if branch else None
        row = branches.setdefault(
            key,
            {
                "branch": {"id": branch.pk, "name": branch.name} if branch else None,
                "people": 0,
                "ratings": [],
                "raises": 0,
                "bonuses": 0,
                "promotions": 0,
                "plans": 0,
                "raise_cost": Decimal(0),
                "bonus_total": Decimal(0),
            },
        )
        row["people"] += 1
        if review.rating:
            row["ratings"].append(review.rating)
        state = outcome_state(review, bonuses)
        counted = state in ("waiting", "approved", "applied")
        side = "waiting" if state == "waiting" else "approved"
        if review.outcome == Review.Outcome.RAISE:
            row["raises"] += 1
        elif review.outcome == Review.Outcome.PROMOTION:
            row["promotions"] += 1
        elif review.outcome == Review.Outcome.BONUS:
            row["bonuses"] += 1
        elif review.outcome == Review.Outcome.PLAN:
            row["plans"] += 1
        cost = _raise_cost(review) if counted else None
        if cost is not None:
            raises[side] += cost
            row["raise_cost"] += cost
        bonus = bonuses.get(review.bonus_id) if review.bonus_id else None
        if bonus is not None and counted:
            amount = Decimal(bonus["amount"])
            bonus_total[side] += amount
            row["bonus_total"] += amount
            currency = bonus["currency"]
    by_branch = []
    for row in sorted(
        branches.values(),
        key=lambda item: (item["branch"] is None, (item["branch"] or {}).get("name", "")),
    ):
        by_branch.append(
            {
                "branch": row["branch"],
                "people": row["people"],
                "average": _mean(row["ratings"]),
                "raises": row["raises"],
                "bonuses": row["bonuses"],
                "promotions": row["promotions"],
                "plans": row["plans"],
                "raise_cost": f"{row['raise_cost']:.2f}" if pay else None,
                "bonus_total": f"{row['bonus_total']:.2f}" if pay else None,
            }
        )
    return {
        "people": len(list(rows)),
        "published": len(published),
        "average": _mean(ratings),
        "spread": {str(value): spread.get(value, 0) for value in reviews.RATINGS},
        "outcomes": {value: outcomes.get(value, 0) for value in Review.Outcome.values},
        "questions": questions,
        "by_branch": by_branch,
        "cost": (
            {
                "currency": currency,
                "raises_monthly": f"{raises['approved']:.2f}",
                "raises_waiting": f"{raises['waiting']:.2f}",
                "bonuses": f"{bonus_total['approved']:.2f}",
                "bonuses_waiting": f"{bonus_total['waiting']:.2f}",
            }
            if pay
            else None
        ),
    }


def _mean(values) -> str | None:
    values = [value for value in values if value]
    if not values:
        return None
    return str((Decimal(sum(values)) / Decimal(len(values))).quantize(Decimal("0.1")))


# The person's history ------------------------------------------------------------------------


def published_for(membership: Membership) -> list[Review]:
    """The person's published reviews, newest first (Person 360's career line)."""
    return list(
        Review.objects.filter(membership=membership, published_at__isnull=False)
        .select_related(*REVIEW_RELATIONS)
        .order_by("-published_at", "-pk")
    )


def open_goals(membership: Membership) -> QuerySet[ReviewGoal]:
    return ReviewGoal.objects.filter(
        membership=membership,
        review__published_at__isnull=False,
        status=ReviewGoal.Status.OPEN,
    ).order_by("due_on", "pk")


# The company calendar ------------------------------------------------------------------------


def calendar_deadlines(company, start: date, end: date, member: Membership) -> list[CalendarItem]:
    """The self and the reviewers' deadlines of the rounds `member` sees (drafts aside)."""
    rows = (
        cycles_for(member)
        .exclude(status=ReviewCycle.Status.DRAFT)
        .filter(Q(self_due_on__range=(start, end)) | Q(manager_due_on__range=(start, end)))
        .order_by("self_due_on", "pk")
    )
    items = []
    for cycle in rows:
        url = f"lifecycle/reviews/{cycle.pk}"
        if start <= cycle.self_due_on <= end:
            items.append(
                CalendarItem(
                    id=f"lifecycle.review_self:{cycle.pk}",
                    kind="lifecycle.review_deadlines",
                    # Translators: %(name)s is a review round's name; it stands after the colon.
                    title=_("Self reviews due: %(name)s") % {"name": cycle.name},
                    start=cycle.self_due_on,
                    end=cycle.self_due_on,
                    all_day=True,
                    color="chart-4",
                    url=url,
                )
            )
        if start <= cycle.manager_due_on <= end:
            items.append(
                CalendarItem(
                    id=f"lifecycle.review_manager:{cycle.pk}",
                    kind="lifecycle.review_deadlines",
                    title=_("Reviewers' deadline: %(name)s") % {"name": cycle.name},
                    start=cycle.manager_due_on,
                    end=cycle.manager_due_on,
                    all_day=True,
                    color="chart-5",
                    url=url,
                )
            )
    return items


# The export ----------------------------------------------------------------------------------


def export_rows(member: Membership, params: dict):
    """Published reviews `member` may read (inside their branch scope), one row each; a round's
    id in `params["round"]` narrows it. Bonus amounts only with payroll.view."""
    rows = Review.objects.filter(
        company_id=member.company_id, published_at__isnull=False
    ).select_related(*REVIEW_RELATIONS)
    cycle_id = params.get("round")
    if cycle_id not in (None, ""):
        try:
            rows = rows.filter(cycle_id=int(cycle_id))
        except TypeError, ValueError:
            rows = rows.none()
    branch_ids = scope.branch_ids(member)
    if branch_ids is not None:
        rows = rows.filter(
            membership_id__in=hr_queries.people(
                member.company, branch_ids=branch_ids, statuses=hr_queries.EMPLOYED
            ).values("pk")
        )
    rows = [
        review for review in rows.order_by("cycle_id", "pk") if reviews.may_read(member, review)
    ]
    pay = member.has_perm(Perm.PAYROLL_VIEW)
    bonuses = adjustments(member.company, [review.bonus_id for review in rows])
    outcome_labels = dict(Review.Outcome.choices)
    states = {
        "waiting": _("Waiting for approval"),
        "approved": _("Approved"),
        "applied": _("Applied"),
        "rejected": _("Not approved"),
    }
    for review in rows:
        person = review.membership
        state = outcome_state(review, bonuses)
        bonus = bonuses.get(review.bonus_id) if pay and review.bonus_id else None
        yield {
            "round": review.cycle.name,
            "person": str(person),
            "position": person.position.name if person.position_id else "",
            "branch": person.home_branch.name if person.home_branch_id else "",
            "reviewer": str(review.reviewer) if review.reviewer_id else "",
            "self_sent_at": review.self_sent_at,
            "self_average": reviews.average(review.cycle, review.self_answers)
            if review.self_sent_at
            else None,
            "manager_average": reviews.average(review.cycle, review.manager_answers),
            "rating": review.rating,
            "outcome": str(outcome_labels.get(review.outcome, review.outcome)),
            "raise_percent": review.raise_percent,
            "promotion": review.promotion_position.name if review.promotion_position_id else "",
            "bonus": Decimal(bonus["amount"]) if bonus else None,
            "effective_on": review.effective_on,
            "state": str(states.get(state, "")) if state else "",
            "published_at": review.published_at,
            "acknowledged_at": review.acknowledged_at,
        }
