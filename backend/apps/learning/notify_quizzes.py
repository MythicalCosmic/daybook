"""Who hears about checks and the tutor, through the inbox (`apps.inbox.services.notify`).

To the person (the staff bot, with a way into the app): a check round to answer, a reminder,
the tutor's nudge after a hard test. To managers (the dashboard, the owner bot for owners and
top managers): a check round's results, the tutor's weekly report. Each one once: the
`dedupe_key` names the round, the entry or the week.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.inbox import services as inbox
from apps.learning.models import CheckEntry, CheckRound

CHECK_STARTED = "learning.check_started"
CHECK_REMINDER = "learning.check_reminder"
CHECK_RESULTS = "learning.check_results"
TUTOR_REPORT = "learning.tutor_report"
NUDGE = "learning.nudge"
# Names a digest lists before it says "and N more".
NAMES = 5


def when(moment: datetime, company) -> str:
    """A moment as the person reads it: the company's day and time, "12.11 10:00"."""
    return timezone.localtime(moment, ZoneInfo(company.timezone)).strftime("%d.%m %H:%M")


def check_screen(entry: CheckEntry) -> str:
    return f"check:{entry.pk}"


def check_started(entry: CheckEntry, questions: int) -> int:
    round_ = entry.check_round
    check = round_.regular_check
    due = when(round_.due_at, entry.company)
    sent = inbox.notify(
        [entry.membership],
        CHECK_STARTED,
        title=lambda person: _("Regular check: %(title)s") % {"title": check.title},
        body=lambda person: (
            ngettext(
                "%(count)s question, to answer by %(due)s.",
                "%(count)s questions, to answer by %(due)s.",
                questions,
            )
            % {"count": questions, "due": due}
        ),
        app_screen=check_screen(entry),
        target=entry,
        dedupe_key=f"{CHECK_STARTED}:{entry.pk}",
    )
    return len(sent)


def check_reminder(entry: CheckEntry, step: str) -> int:
    """`step`: "half" (half the time gone) or "last" (two hours left)."""
    round_ = entry.check_round
    check = round_.regular_check
    due = when(round_.due_at, entry.company)

    def body(person):
        if step == "last":
            return _("Two hours left: answer by %(due)s.") % {"due": due}
        return _("Half the time is gone: answer by %(due)s.") % {"due": due}

    sent = inbox.notify(
        [entry.membership],
        CHECK_REMINDER,
        title=lambda person: _("Reminder: %(title)s") % {"title": check.title},
        body=body,
        app_screen=check_screen(entry),
        target=entry,
        severity="warning" if step == "last" else None,
        dedupe_key=f"{CHECK_REMINDER}:{entry.pk}:{step}",
    )
    return len(sent)


def check_results(round_: CheckRound, reader, facts: dict) -> int:
    """The closed round's digest for one manager, about the people they see (`facts`)."""
    check = round_.regular_check

    def body(person):
        lines = [
            _("Answered: %(done)s of %(people)s. Passed: %(passed)s.")
            % {"done": facts["done"], "people": facts["people"], "passed": facts["passed"]}
        ]
        if facts.get("weakest"):
            weakest = facts["weakest"]
            lines.append(
                _("Hardest question: «%(text)s» (%(percent)s %% right).")
                % {"text": weakest["text"], "percent": weakest["percent"]}
            )
        missing = facts.get("missing") or []
        if missing:
            shown = ", ".join(missing[:NAMES])
            more = len(missing) - NAMES
            if more > 0:
                shown = ngettext(
                    "%(names)s and %(count)s more", "%(names)s and %(count)s more", more
                ) % {"names": shown, "count": more}
            lines.append(_("Didn't answer: %(names)s.") % {"names": shown})
        return "\n".join(lines)

    sent = inbox.notify(
        [reader],
        CHECK_RESULTS,
        title=lambda person: _("Check results: %(title)s") % {"title": check.title},
        body=body,
        url=f"/c/{round_.company_id}/learning/checks/{check.pk}",
        target=round_,
        data={"round": round_.pk, **{k: v for k, v in facts.items() if k != "missing"}},
        dedupe_key=f"{CHECK_RESULTS}:{round_.pk}",
    )
    return len(sent)


# The tutor --------------------------------------------------------------------------------


def report_lines(facts: dict) -> list[str]:
    """The weekly report's body as plain lines (the template), from `facts`."""
    lines = []
    mandatory = facts.get("mandatory") or {}
    if mandatory.get("people"):
        lines.append(
            _("Mandatory training: %(done)s of %(people)s people finished, %(late)s late.")
            % {
                "done": mandatory["completed"],
                "people": mandatory["people"],
                "late": mandatory["late"],
            }
        )
        if mandatory.get("late_names"):
            lines.append(_("Late: %(names)s.") % {"names": ", ".join(mandatory["late_names"])})
    tests = facts.get("tests") or {}
    if tests.get("count"):
        lines.append(
            ngettext(
                "This week: %(count)s test, %(average)s %% on average.",
                "This week: %(count)s tests, %(average)s %% on average.",
                tests["count"],
            )
            % {"count": tests["count"], "average": tests["average"]}
        )
    else:
        lines.append(_("No tests were taken this week."))
    weakest = facts.get("weakest_topic")
    if weakest:
        lines.append(
            _("Weakest topic: %(topic)s (%(average)s %%).")
            % {"topic": weakest["name"], "average": weakest["average"]}
        )
    top = facts.get("top") or []
    if top:
        names = ", ".join(f"{row['name']} ({row['points']})" for row in top)
        lines.append(_("Most points this week: %(names)s.") % {"names": names})
    help_rows = facts.get("help") or []
    if help_rows:
        shown = []
        for row in help_rows[:NAMES]:
            why = row["topics"] or ([_("late with training")] if row.get("late") else [])
            shown.append(f"{row['name']} ({', '.join(why)})" if why else row["name"])
        lines.append(_("Needs help: %(names)s.") % {"names": "; ".join(shown)})
    open_count = (facts.get("suggestions") or {}).get("open", 0)
    if open_count:
        lines.append(
            ngettext(
                "%(count)s suggestion waits for you on the tutor's page.",
                "%(count)s suggestions wait for you on the tutor's page.",
                open_count,
            )
            % {"count": open_count}
        )
    return lines


def tutor_report(reader, facts: dict, *, opening: str, week: str, actions) -> int:
    """The weekly training report for one manager about the people they see."""
    company_id = reader.company_id

    def body(person):
        lines = [opening] if opening else []
        return "\n".join(lines + report_lines(facts))

    sent = inbox.notify(
        [reader],
        TUTOR_REPORT,
        title=lambda person: _("Weekly training report"),
        body=body,
        url=f"/c/{company_id}/learning/tutor",
        actions=actions,
        data={"facts": facts, "opening": opening, "week": week},
        dedupe_key=f"{TUTOR_REPORT}:{reader.pk}:{week}",
    )
    return len(sent)


def nudge(member, *, topic: str, lesson, attempt_id: int) -> int:
    """The day after a hard test: the lesson that helps."""
    sent = inbox.notify(
        [member],
        NUDGE,
        title=lambda person: _("Yesterday's test on %(topic)s was hard") % {"topic": topic},
        body=lambda person: _("This lesson helps: %(lesson)s.") % {"lesson": lesson.title},
        app_screen=f"lesson:{lesson.pk}",
        dedupe_key=f"{NUDGE}:{attempt_id}",
    )
    return len(sent)
