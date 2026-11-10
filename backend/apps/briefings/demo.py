"""Demo data of briefings (`make demo`): Maslahatchi's business reviews of Demo Dorixona.

Once every other demo has written its numbers (`finish`), the reviews are written the way the
schedule would have: the weekly ones of the last WEEKS weeks, each on the Monday after its week
at the send time, and the monthly one of last month on the first; each sent to the owner (and
anyone else the settings name) and backdated to that moment, with Maslahatchi's run and its
"sent" line on its own page when it is on. Their words come from the templates (`AI_FAKE` calls
no Claude), their numbers from the finance, sales, stock and attendance demos. The periods are
marked sent, so the beat doesn't send them again after the demo is built.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.briefings import conf, periods, reviews
from apps.briefings.models import Briefing, BriefingDelivery

WEEKS = 3


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships. The reviews wait for the other demos (`finish`)."""


def finish(company, people, now) -> None:
    """The reviews of the last weeks and of last month, as they went out."""
    from apps.core.demo_time import moment

    zone = ZoneInfo(company.timezone)
    today = timezone.localtime(now, zone).date()
    row = conf.get_settings(company)
    monday = today - timedelta(days=today.weekday())
    sent_at = []
    for back in range(WEEKS, 0, -1):
        period = periods.week(monday - timedelta(days=7 * back))
        when = datetime.combine(period.end + timedelta(days=1), row.send_at, zone)
        if when < now:
            sent_at.append((period, when))
    month = periods.latest(Briefing.Kind.MONTHLY, today)
    first = datetime.combine(month.end + timedelta(days=1), row.send_at, zone)
    if first < now:
        sent_at.append((month, first))
    for period, when in sorted(sent_at, key=lambda pair: pair[1]):
        with moment(when):
            outcome = reviews.send(company, period, when, use_ai=False)
        _backdate(company, period, when)
        _advisor_run(company, period, when, outcome)
    weeks = [period for period, _when in sent_at if period.kind == Briefing.Kind.WEEKLY]
    row.weekly_sent_for = weeks[-1].start if weeks else None
    row.monthly_sent_for = month.start if first < now else None
    row.save(update_fields=["weekly_sent_for", "monthly_sent_for", "updated_at"])


def _backdate(company, period, when) -> None:
    rows = Briefing.objects.filter(company=company, day=period.start, kind=period.kind)
    rows.update(written_at=when, created_at=when, updated_at=when)
    BriefingDelivery.objects.filter(briefing__in=rows).update(sent_at=when)


def _advisor_run(company, period, when, outcome) -> None:
    """Maslahatchi's run that sent the review, on its page (when it is on here)."""
    from apps.ai import events
    from apps.ai.agents import advisor
    from apps.ai.models import AgentEvent, AgentRun, AgentState

    if not advisor.is_on(company) or not outcome.sent:
        return
    AgentRun.objects.create(
        company=company,
        key=advisor.KEY,
        started_at=when,
        finished_at=when + timedelta(seconds=4),
        status=AgentRun.Status.OK,
        done=outcome.sent,
    )
    event = events.log(
        company,
        advisor.KEY,
        f"{period.kind}_sent",
        params={"count": outcome.sent},
        dedupe_key=f"advisor:{period.kind}:{period.start.isoformat()}",
        level="success",
    )
    if event is not None:
        AgentEvent.objects.filter(pk=event.pk).update(created_at=when + timedelta(seconds=4))
    AgentState.objects.filter(company=company, key=advisor.KEY).update(
        last_run_at=when, last_status=AgentRun.Status.OK, last_error=""
    )
