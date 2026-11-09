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
