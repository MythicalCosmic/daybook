"""'Draft my summary' (docs/PLAN-OWNER.md §13.4 "Reviews"): Claude Haiku 5.5 suggests a review's
summary to its reviewer from the round's questions, the person's own answers, the reviewer's
answers and the person's numbers for the period, and nothing else: no name, no pay, no outcome.
It is only ever a suggestion in the reviewer's summary box: they read it and change it, it is
saved like their own words, and it never picks a rating or what follows.

The call goes through `apps.ai.client.structured` (the company's budget, an AIUsage row, the
circuit breaker), with the effort set, thinking left adaptive, no temperature and the stop reason
checked there. It is offered only while Claude is available to the company (the AI module on
with an owner's consent, the month's budget not spent) to a reviewer who may use AI (ai.use);
with AI_FAKE a canned draft from the reviewer's ratings answers instead. A few drafts a review a
day, so a stuck button can't spend the month's budget.
"""

from xml.sax.saxutils import escape, quoteattr

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _
from pydantic import BaseModel

from apps.core.exceptions import DomainError
from apps.hr import queries as hr_queries
from apps.lifecycle import reviews
from apps.lifecycle.models import Review
from apps.members.models import Membership
from apps.members.permissions import Perm

FEATURE = "review_summary"
DRAFTS_A_DAY = 10
MAX_TOKENS = 4000
ENGINES = ("claude", "fake")
LANGUAGE_NAMES = {"uz": "Uzbek (Latin script)", "ru": "Russian", "en": "English"}

SYSTEM = """You draft the short summary of an employee's performance review at a pharmacy, for \
their manager, who reads it and changes it before the employee sees it. You get the review's \
questions with the employee's own answers and the manager's answers (ratings from 1 to 5, where 5 \
is excellent, and comments), and the employee's numbers for the period.

Write two to four plain sentences addressed to the employee (the polite "you"), in the language \
asked: what went well in the period and what to work on next. Use only what you are given; where \
the employee and the manager see something differently, follow the manager. Never give a rating \
or a score, never mention pay, a raise, a bonus, a promotion or any other decision, and never \
promise anything. No emoji, lists, headings, greeting or sign-off."""


class SummaryDraft(BaseModel):
    summary: str


def available(review: Review, member: Membership) -> bool:
    """The reviewer may ask Claude for a draft now."""
    from apps.ai import availability

    return (
        reviews.may_write(member, review)
        and member.has_perm(Perm.AI_USE)
        and availability.status(review.company, membership=member).available
    )


def draft(review: Review, *, by: Membership, language: str) -> tuple[str, str]:
    """A suggested summary in `language` and who wrote it ("claude", or "fake" with AI_FAKE).
    Nothing is saved: the reviewer keeps it by saving their draft."""
    from apps.ai import availability, client

    if not reviews.may_write(by, review):
        raise PermissionDenied(_("Only the person's reviewer writes this review."))
    if not by.has_perm(Perm.AI_USE):
        raise PermissionDenied(_("You may not use AI in this company."))
    if not availability.status(review.company, membership=by).available:
        raise DomainError(_("AI isn't available for this company right now. Write it yourself."))
    if not review.manager_answers:
        raise DomainError(_("Answer a few questions first: the draft follows your answers."))
    _count(review)
    if availability.fake():
        return canned(review), "fake"
    try:
        result, _call = client.structured(
            FEATURE,
            company=review.company,
            membership=by,
            model=settings.AI_MODEL_FAST,
            schema=SummaryDraft,
            effort="low",
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            user=[{"type": "text", "text": prompt(review, language=language, viewer=by)}],
        )
    except client.ClaudeError:
        raise DomainError(
            _("Claude couldn't write a draft just now. Try again, or write it yourself.")
        ) from None
    summary = " ".join(result.summary.split())[: reviews.MAX_SUMMARY]
    if not summary:
        raise DomainError(
            _("Claude couldn't write a draft just now. Try again, or write it yourself.")
        )
    return summary, "claude"


def _count(review: Review) -> None:
    today = hr_queries.today(review.company)
    key = f"lifecycle:review-summary:{review.pk}:{today.isoformat()}"
    cache.add(key, 0, timeout=26 * 3600)
    try:
        used = cache.incr(key)
    except ValueError:  # gone between add and incr
        cache.set(key, 1, timeout=26 * 3600)
        used = 1
    if used > DRAFTS_A_DAY:
        raise DomainError(_("That's enough drafts for this review today. Write it yourself."))


def prompt(review: Review, *, language: str, viewer: Membership) -> str:
    """The review as Claude reads it: the questions with both sides' answers, then the numbers.
    The person's own answers only once they sent them (as their reviewer sees them)."""
    cycle = review.cycle
    sent = review.self_sent_at is not None and reviews.self_visible(review)
    own = (review.self_answers or {}) if sent else {}
    theirs = review.manager_answers or {}
    code = (language or "").split("-")[0].lower()
    lines = [
        f"<language>{LANGUAGE_NAMES.get(code, LANGUAGE_NAMES['uz'])}</language>",
        f"<period>{cycle.period_start.isoformat()} to {cycle.period_end.isoformat()}</period>",
        "<questions>",
    ]
    for number, question in enumerate(reviews.shown_questions(cycle), start=1):
        lines.append(f'<question number="{number}" kind="{question["kind"]}">')
        lines.append(f"<text>{escape(question['text'])}</text>")
        for tag, answers in (("employee", own), ("manager", theirs)):
            answer = answers.get(question["id"]) or {}
            rating = answer.get("rating")
            text = escape(" ".join(str(answer.get("text") or "").split()))
            attribute = f" rating={quoteattr(str(rating))}" if rating else ""
            if rating or text:
                lines.append(f"<{tag}{attribute}>{text}</{tag}>")
            else:
                lines.append(f"<{tag}>no answer</{tag}>")
        lines.append("</question>")
    lines.append("</questions>")
    numbers = _numbers(review.kpis or {}, sales=viewer.has_perm(Perm.SALES_VIEW))
    if numbers:
        lines += ["<numbers>", *numbers, "</numbers>"]
    return "\n".join(lines)


def _numbers(kpis: dict, *, sales: bool) -> list[str]:
    """The snapshot in plain lines: counts and percentages only (no money)."""
    found = []
    tasks = kpis.get("tasks")
    if tasks and tasks.get("total"):
        percent = tasks.get("on_time_percent")
        found.append(
            f"Shared tasks: {tasks['total']}, on time {tasks['on_time']}, late {tasks['late']}, "
            f"missed {tasks['missed']}" + (f" ({percent}% on time)." if percent else ".")
        )
    attendance = kpis.get("attendance")
    if attendance and attendance.get("scheduled_days"):
        found.append(
            f"Attendance: {attendance['scheduled_days']} days scheduled, "
            f"{attendance['attended_days']} worked, {attendance['absent_days']} absent, "
            f"{attendance['late_arrivals']} late arrivals, "
            f"{attendance.get('leave_days', 0)} days of leave."
        )
    discipline = kpis.get("discipline")
    if discipline is not None:
        found.append(f"Disciplinary records in the period: {discipline.get('records', 0)}.")
    till = kpis.get("sales") if sales else None
    if till and till.get("shifts"):
        accuracy = till.get("accuracy")
        found.append(
            f"Till: {till['shifts']} shifts, {till['receipts']} receipts, "
            f"{till['shortages']} cash shortages"
            + (f", the cash matched {accuracy}% of the time." if accuracy else ".")
        )
    learning = kpis.get("learning")
    if learning and (learning.get("completed") or learning.get("open")):
        found.append(
            f"Training: {learning['completed']} completed, {learning['open']} open, "
            f"{learning['late']} overdue."
        )
    goals = kpis.get("goals")
    if goals and any(goals.values()):
        found.append(
            f"Goals from earlier reviews: {goals['done']} reached, {goals['missed']} not "
            f"reached, {goals['open']} open."
        )
    return found


def canned(review: Review) -> str:
    """AI_FAKE's draft (development and demos): the reviewer's best and weakest rated
    questions, in the reader's language."""
    cycle = review.cycle
    answers = review.manager_answers or {}
    rated = [
        (answers.get(question["id"], {}).get("rating"), index, question)
        for index, question in enumerate(reviews.shown_questions(cycle))
        if question["kind"] == reviews.RATING and answers.get(question["id"], {}).get("rating")
    ]
    if not rated:
        return _("Thank you for your work in this period.")
    best = max(rated, key=lambda item: (item[0], -item[1]))
    weakest = min(rated, key=lambda item: (item[0], item[1]))
    parts = [_("What went best in this period: %(topic)s.") % {"topic": _topic(best[2])}]
    if weakest[0] < best[0]:
        parts.append(_("To work on next: %(topic)s.") % {"topic": _topic(weakest[2])})
    return " ".join(parts)


def _topic(question: dict) -> str:
    """A question's subject: the words before its colon ("Cash discipline: the till…")."""
    text = question["text"].split(":", 1)[0].strip().rstrip(".?")
    return text[:1].lower() + text[1:] if text[:2] != text[:2].upper() else text
