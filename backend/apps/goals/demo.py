"""Demo Dorixona's business goals (v11), set in `finish` once every app has booked its rows, so
each goal measures the real demo numbers: this quarter's revenue (on track), the Sergeli
pharmacy opening (a third branch: at risk), late arrivals at Chilonzor this month (off track)
and last month's average check (achieved). Targets and periods are picked from the numbers
themselves, so each goal lands in its state whatever the demo's sums and today's date are; each
has its weekly points since it started, and the owners have the note about the goals that
turned for the worse (the weekly beat's own, run once).
"""

from datetime import date, datetime, time, timedelta
from decimal import ROUND_FLOOR, Decimal
from zoneinfo import ZoneInfo

from apps.core import demo_plan
from apps.core.demo_time import moment
from apps.goals import progress, services
from apps.goals.metrics import METRICS
from apps.goals.models import Goal, GoalPoint, Metric

D = Decimal
ROMAN = ("I", "II", "III", "IV")


def finish(company, people, now) -> None:
    if company.slug == demo_plan.DISTRIBUTOR:
        return
    owner, manager = people["owner"], people["manager"]
    today = services.local_today(company, now)
    zone = ZoneInfo(company.timezone)
    branches = list(company.branches.filter(is_active=True).order_by("order", "pk"))
    quarter = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    quarter_end = _months_later(quarter, 3) - timedelta(days=1)
    month = today.replace(day=1)

    def at(day: date) -> datetime:
        return datetime.combine(day, time(9, 30), tzinfo=zone)

    made = []
    if company.has_feature("finance"):
        forecast = _measure(company, Metric.REVENUE, quarter, quarter_end, None, today).forecast
        if forecast:
            target = _round(forecast * D("0.93"))
            made.append(
                _goal(
                    company,
                    owner,
                    at(quarter),
                    title=f"{ROMAN[(quarter.month - 1) // 3]} chorak tushumi: {_short(target)}",
                    metric=Metric.REVENUE,
                    target=target,
                    starts_on=quarter,
                    ends_on=quarter_end,
                    owner_member=owner,
                    note="Ikkala dorixona birgalikda.",
                )
            )
    count = D(len([branch for branch in branches if branch.kind != "office"]))
    start, end = _at_risk_period(today, quarter, quarter_end)
    made.append(
        _goal(
            company,
            owner,
            at(start),
            title="Uchinchi dorixona: Sergeli",
            metric=Metric.BRANCHES,
            target=count + 1,
            starts_on=start,
            ends_on=end,
            owner_member=owner,
            note="Litsenziya, ta’mir va muzlatgich: «Sergeli dorixonasini ochish» loyihasi.",
            baseline=count,
        )
    )
    off = _late_goal(company, owner, manager, branches, today, month, at)
    if off is None and company.has_feature("finance"):
        off = _margin_goal(company, owner, today, quarter, quarter_end, at)
    if off is not None:
        made.append(off)
    last_month = _months_later(month, -1)
    if company.has_feature("sales"):
        check = _measure(
            company, Metric.AVERAGE_CHECK, last_month, month - timedelta(days=1), None, today
        )
        if check.value:
            target = _round(check.value * D("0.96"), step=D(1000))
            made.append(
                _goal(
                    company,
                    owner,
                    at(last_month),
                    title=f"O‘rtacha chek: {_thousands(target)} so‘m",
                    metric=Metric.AVERAGE_CHECK,
                    target=target,
                    starts_on=last_month,
                    ends_on=month - timedelta(days=1),
                    owner_member=manager,
                    note="Kassada qo‘shimcha tavsiya: vitaminlar va gigiena.",
                )
            )
    for goal in made:
        _backfill(goal, today)
    # The weekly beat once: today's point and the note for each goal that turned for the worse.
    with moment(now):
        services.weekly(now)


def _at_risk_period(today: date, quarter: date, quarter_end: date) -> tuple[date, date]:
    """A period a quarter to a half of which has passed (a level goal with no progress is at
    risk then): this quarter, or the one from last month to next, or the half year."""
    half = date(today.year, 1 if today.month <= 6 else 7, 1)
    candidates = [
        (quarter, quarter_end),
        (_months_later(today.replace(day=1), -1), _months_later(today.replace(day=1), 2)),
        (half, _months_later(half, 6) - timedelta(days=1)),
        (today - timedelta(days=30), _months_later(today.replace(day=1), 3) - timedelta(days=1)),
    ]
    for start, end in candidates:
        end = end if end.day != 1 else end - timedelta(days=1)
        share = D((today - start).days + 1) / D((end - start).days + 1)
        if D("0.27") <= share <= D("0.48"):
            return start, end
    return quarter, quarter_end


def _late_goal(company, owner, manager, branches, today, month, at) -> Goal | None:
    """Late arrivals at the first pharmacy, with a ceiling well under what it is (off track)."""
    if not company.has_feature("attendance") or not branches:
        return None
    home = branches[0]
    # Early in a month the forecast is too young to be off track: then since last month.
    start = month if today.day > 8 else _months_later(month, -1)
    end = _months_later(month, 1) - timedelta(days=1)
    late = _measure(company, Metric.LATE_ARRIVALS, start, end, home, today).value
    if late is None or late < D(3):
        return None
    target = max((late / 2).quantize(D("1"), rounding=ROUND_FLOOR), D(1))
    return _goal(
        company,
        owner,
        at(start),
        title=f"Kechikishlar ko‘pi bilan {target}\u00a0%: {home.name}",
        metric=Metric.LATE_ARRIVALS,
        target=target,
        starts_on=start,
        ends_on=end,
        branch=home,
        owner_member=manager,
        note="Smenaga 10 daqiqa oldin kelish qoidasi.",
    )


def _margin_goal(company, owner, today, quarter, quarter_end, at) -> Goal | None:
    """Without attendance: a net margin far above this quarter's (off track)."""
    margin = _measure(company, Metric.MARGIN, quarter, quarter_end, None, today).value
    if margin is None:
        return None
    target = min(max(margin, D(0)).quantize(D("1"), rounding=ROUND_FLOOR) + D(10), D(60))
    return _goal(
        company,
        owner,
        at(quarter),
        title=f"Sof rentabellik: {target}\u00a0%",
        metric=Metric.MARGIN,
        target=target,
        starts_on=quarter,
        ends_on=quarter_end,
        owner_member=owner,
    )


def _goal(company, by, when: datetime, *, owner_member=None, baseline=None, **fields) -> Goal:
    with moment(when):
        goal = services.create_goal(company, by=by, owner=owner_member, **fields)
    if baseline is not None:
        Goal.objects.filter(pk=goal.pk).update(baseline=baseline)
        goal.baseline = baseline
    return goal


def _measure(company, metric: str, start: date, end: date, branch, today: date):
    draft = Goal(
        company=company,
        title="",
        metric=metric,
        target=D(1),
        starts_on=start,
        ends_on=end,
        branch=branch,
    )
    return progress.evaluate(draft, today)


def _backfill(goal: Goal, today: date) -> None:
    """A point each Monday since the goal's start, as the weekly beat would have left them."""
    day = goal.starts_on + timedelta(days=(7 - goal.starts_on.weekday()) % 7)
    last = min(today - timedelta(days=1), goal.ends_on + timedelta(days=7))
    while day <= last:
        result = progress.evaluate(goal, day)
        value, forecast, state = result.value, result.forecast, result.state
        if goal.metric == Metric.BRANCHES:
            # The demo's branches are made today; they were open all along.
            value = forecast = goal.baseline
            state = progress.evaluate_level(goal, day, value)
        GoalPoint.objects.update_or_create(
            goal=goal, on=day, defaults={"value": value, "forecast": forecast, "state": state}
        )
        day += timedelta(days=7)
    services.refresh(goal, today)


def _months_later(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


TEN_MILLION = D(10_000_000)


def _round(value: Decimal, step: Decimal = TEN_MILLION) -> Decimal:
    """Down to a round target (10 mln so‘m by default)."""
    if value < step:
        return value.quantize(D("1"), rounding=ROUND_FLOOR)
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def _short(amount: Decimal) -> str:
    """1 500 000 000 as "1,5 mlrd", 750 000 000 as "750 mln" (the Uzbek way)."""
    if amount >= 1_000_000_000:
        text = f"{(amount / D(1_000_000_000)).quantize(D('0.1')):f}".replace(".", ",")
        return f"{text.removesuffix(',0')}\u00a0mlrd so‘m"
    return f"{int(amount // 1_000_000)}\u00a0mln so‘m"


def _thousands(amount: Decimal) -> str:
    return f"{int(amount):,}".replace(",", "\u00a0")


__all__ = ["METRICS", "finish"]
