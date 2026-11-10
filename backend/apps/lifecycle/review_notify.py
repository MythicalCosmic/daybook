"""Who hears about performance reviews, and what they read (`apps.inbox.services.notify`
renders each title and body in the reader's language). Plain text, no emoji, days as dd.mm.yyyy,
never an answer, a rating or an amount: the app shows those.

- `lifecycle.review` (the person, the employee bot with a way into the mini app): a round opened
  for them, the day before their self deadline, a nudge from the round page, their review
  published.
- `lifecycle.review_to_write` (the reviewer, the dashboard and the owner bot): their part began,
  the day before their deadline, a nudge from the round page.

Each notice goes once (`dedupe_key`): a round's opening and publishing once a review, a
reminder once a deadline, a nudge once a day.
"""

from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.hr import queries as hr_queries
from apps.inbox import services as inbox
from apps.lifecycle.bot_messages import day
from apps.lifecycle.models import Review, ReviewCycle
from apps.members.models import Membership

REVIEW = "lifecycle.review"
TO_WRITE = "lifecycle.review_to_write"


def review_screen(review: Review) -> str:
    return f"lifecycle.review:{review.pk}"


def round_url(cycle: ReviewCycle, *, mine: bool = False) -> str:
    url = f"/c/{cycle.company_id}/lifecycle/reviews/{cycle.pk}"
    return f"{url}?mine=1" if mine else url


# What they read ------------------------------------------------------------------------------


def opened_title(cycle: ReviewCycle) -> str:
    # Translators: %(name)s is the review round's name, e.g. "2026, 4th quarter".
    return _("Performance review: %(name)s") % {"name": cycle.name}


def opened_body(cycle: ReviewCycle) -> str:
    return _(
        "Please answer a few questions about your work. It takes about five minutes, and you "
        "can stop and go on later. Deadline: %(date)s."
    ) % {"date": day(cycle.self_due_on)}


def reminder_title(cycle: ReviewCycle) -> str:
    return _("Reminder: your self review is waiting")


def reminder_body(cycle: ReviewCycle) -> str:
    return _("%(name)s: a few questions about your work are still waiting. Deadline: %(date)s.") % {
        "name": cycle.name,
        "date": day(cycle.self_due_on),
    }


def published_title(cycle: ReviewCycle) -> str:
    return _("Your performance review is ready")


def published_body(cycle: ReviewCycle) -> str:
    return _("%(name)s: your manager's answers and what follows are in the app.") % {
        "name": cycle.name
    }


def to_write_title(cycle: ReviewCycle) -> str:
    # Translators: %(name)s is the review round's name.
    return _("Reviews to write: %(name)s") % {"name": cycle.name}


def to_write_body(cycle: ReviewCycle, count: int) -> str:
    return ngettext(
        "%(count)s person waits for your review. Deadline: %(date)s.",
        "%(count)s people wait for your review. Deadline: %(date)s.",
        count,
    ) % {"count": count, "date": day(cycle.manager_due_on)}


def to_publish_title(cycle: ReviewCycle) -> str:
    return _("Reminder: reviews to publish")


def to_publish_body(cycle: ReviewCycle, count: int) -> str:
    return ngettext(
        "%(name)s: %(count)s review is still to publish. Deadline: %(date)s.",
        "%(name)s: %(count)s reviews are still to publish. Deadline: %(date)s.",
        count,
    ) % {"name": cycle.name, "count": count, "date": day(cycle.manager_due_on)}


# Sending -------------------------------------------------------------------------------------


def _cycle(cycle_id: int) -> ReviewCycle | None:
    return ReviewCycle.objects.select_related("company").filter(pk=cycle_id).first()


def _reviews(cycle: ReviewCycle):
    return cycle.reviews.select_related(
        "membership__user",
        "membership__company",
        "reviewer__user",
        "reviewer__company",
        "reviewer__role",
    ).order_by("pk")


def _tell(review: Review, *, title, body, dedupe: str) -> None:
    person = review.membership
    if person.status != Membership.Status.APPROVED:
        return  # suspended: the bot leaves them alone; the app still shows it
    inbox.notify(
        [person],
        REVIEW,
        title=title,
        body=body,
        app_screen=review_screen(review),
        target=review,
        dedupe_key=dedupe[:120],
    )


def round_opened(cycle_id: int) -> None:
    cycle = _cycle(cycle_id)
    if cycle is None or cycle.status != ReviewCycle.Status.SELF:
        return
    for review in _reviews(cycle).filter(self_sent_at__isnull=True):
        _tell(
            review,
            title=lambda reader: opened_title(cycle),
            body=lambda reader: opened_body(cycle),
            dedupe=f"lifecycle.review:{review.pk}:opened",
        )


def _waiting_by_reviewer(cycle: ReviewCycle, reviewer_ids=None) -> dict[int, tuple]:
    """{reviewer id: (reviewer, unpublished reviews)} of the round."""
    found: dict[int, tuple] = {}
    rows = _reviews(cycle).filter(published_at__isnull=True, reviewer__isnull=False)
    if reviewer_ids is not None:
        rows = rows.filter(reviewer_id__in=list(reviewer_ids))
    for review in rows:
        reviewer, count = found.get(review.reviewer_id, (review.reviewer, 0))
        found[review.reviewer_id] = (reviewer, count + 1)
    return found


def _tell_reviewer(cycle: ReviewCycle, reviewer, count: int, *, title, body, dedupe: str) -> None:
    inbox.notify(
        [reviewer],
        TO_WRITE,
        title=title,
        body=body,
        url=round_url(cycle, mine=True),
        target=cycle,
        dedupe_key=dedupe[:120],
    )


def reviewers_part(cycle_id: int) -> None:
    cycle = _cycle(cycle_id)
    if cycle is None or cycle.status != ReviewCycle.Status.MANAGER:
        return
    for reviewer_id, (reviewer, count) in _waiting_by_reviewer(cycle).items():
        _tell_reviewer(
            cycle,
            reviewer,
            count,
            title=lambda reader: to_write_title(cycle),
            body=lambda reader, count=count: to_write_body(cycle, count),
            dedupe=f"lifecycle.review_to_write:{cycle.pk}:{reviewer_id}:stage",
        )


def deadline_reminders(cycle_id: int) -> None:
    """The day before the self deadline the people still to answer; before the reviewers'
    deadline the reviewers with reviews to publish."""
    cycle = _cycle(cycle_id)
    if cycle is None:
        return
    if cycle.status == ReviewCycle.Status.SELF:
        rows = _reviews(cycle).filter(self_sent_at__isnull=True, published_at__isnull=True)
        for review in rows:
            _tell(
                review,
                title=lambda reader: reminder_title(cycle),
                body=lambda reader: reminder_body(cycle),
                dedupe=f"lifecycle.review:{review.pk}:remind:{cycle.self_due_on}",
            )
    elif cycle.status == ReviewCycle.Status.MANAGER:
        for reviewer_id, (reviewer, count) in _waiting_by_reviewer(cycle).items():
            _tell_reviewer(
                cycle,
                reviewer,
                count,
                title=lambda reader: to_publish_title(cycle),
                body=lambda reader, count=count: to_publish_body(cycle, count),
                dedupe=(
                    f"lifecycle.review_to_write:{cycle.pk}:{reviewer_id}:"
                    f"remind:{cycle.manager_due_on}"
                ),
            )


def nudge(cycle_id: int, review_ids, reviewer_ids) -> None:
    """The round page's Remind, once a day each."""
    cycle = _cycle(cycle_id)
    if cycle is None or not cycle.is_open:
        return
    today = hr_queries.today(cycle.company, timezone.now())
    rows = _reviews(cycle).filter(
        pk__in=list(review_ids), self_sent_at__isnull=True, published_at__isnull=True
    )
    for review in rows:
        _tell(
            review,
            title=lambda reader: reminder_title(cycle),
            body=lambda reader: reminder_body(cycle),
            dedupe=f"lifecycle.review:{review.pk}:nudge:{today}",
        )
    if cycle.status != ReviewCycle.Status.MANAGER:
        return
    for reviewer_id, (reviewer, count) in _waiting_by_reviewer(cycle, reviewer_ids).items():
        _tell_reviewer(
            cycle,
            reviewer,
            count,
            title=lambda reader: to_publish_title(cycle),
            body=lambda reader, count=count: to_publish_body(cycle, count),
            dedupe=f"lifecycle.review_to_write:{cycle.pk}:{reviewer_id}:nudge:{today}",
        )


def published(review_id: int) -> None:
    review = (
        Review.objects.select_related("cycle", "membership__user", "membership__company")
        .filter(pk=review_id)
        .first()
    )
    if review is None or review.published_at is None:
        return
    cycle = review.cycle
    _tell(
        review,
        title=lambda reader: published_title(cycle),
        body=lambda reader: published_body(cycle),
        dedupe=f"lifecycle.review:{review.pk}:published",
    )
