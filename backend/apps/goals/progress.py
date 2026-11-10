"""Where a goal stands on a day: its value so far, the forecast to the period's end, how much of
the way it has come and its state.

- Before the period: `not_started`. After it: `achieved` or `missed`, by the whole period's
  value (a level metric: its level on the last day).
- `sum` and `rate` metrics forecast the pace so far to the end (the value times the period's
  days over the days passed); `ratio` metrics forecast their value so far. The state compares
  the forecast with
  the target: meeting it is `on_track`, within 10 % of it (a percent metric: within 1 point at
  least) `at_risk`, further `off_track`. In the first week a forecast is too young to call a
  goal off track: it is at risk at worst.
- `level` metrics (branches, headcount, training) compare how far they came from day one with
  how much of the period has passed: on track while at most a quarter of the time is ahead of
  them, at risk up to a half, off track beyond. Reached early is on track.
- Without data (a module off, nobody to count): `no_data`.

`progress` is the percent shown in the ring: of the target so far (`sum`, `ratio` up), of the
way from day one (`level`), or how close the forecast stays under the ceiling (`down` metrics:
100 while it does).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.goals.metrics import METRICS, MetricSpec
from apps.goals.models import Goal

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)
NEAR = Decimal("0.10")
EARLY_DAYS = 7
LEVEL_SLACK = Decimal("0.25")
LEVEL_RISK = Decimal("0.50")
MAX_PROGRESS = Decimal("999.9")
State = Goal.State


@dataclass(frozen=True)
class Evaluation:
    as_of: date
    value: Decimal | None
    forecast: Decimal | None
    baseline: Decimal | None
    progress: Decimal | None
    state: str
    elapsed_days: int
    total_days: int
    days_left: int

    @property
    def time_share(self) -> Decimal:
        """How much of the period has passed, 0 to 1."""
        if not self.total_days:
            return ONE
        share = min(Decimal(self.elapsed_days) / Decimal(self.total_days), ONE)
        return share.quantize(Decimal("0.0001"))


def branch_ids(goal: Goal) -> list[int] | None:
    return [goal.branch_id] if goal.branch_id else None


def baseline_of(goal: Goal) -> Decimal | None:
    """Where a level metric stood on the goal's first day."""
    metric = METRICS[goal.metric]
    if metric.kind != "level":
        return None
    return metric.measure(goal.company, goal.starts_on, goal.starts_on, branch_ids(goal))


def evaluate(goal: Goal, today: date, *, baseline: Decimal | None = None) -> Evaluation:
    """The goal as of `today` (company-local)."""
    metric = METRICS[goal.metric]
    total = (goal.ends_on - goal.starts_on).days + 1
    if today < goal.starts_on:
        return Evaluation(today, None, None, None, None, State.NOT_STARTED, 0, total, total)
    finished = today > goal.ends_on
    until = min(today, goal.ends_on)
    elapsed = (until - goal.starts_on).days + 1
    days_left = max((goal.ends_on - today).days, 0)
    if not metric.available(goal.company):
        return Evaluation(today, None, None, None, None, State.NO_DATA, elapsed, total, days_left)
    value = metric.measure(goal.company, goal.starts_on, until, branch_ids(goal))
    if metric.kind == "level" and baseline is None:
        baseline = goal.baseline if goal.baseline is not None else baseline_of(goal)
    if value is None:
        return Evaluation(
            today, None, None, baseline, None, State.NO_DATA, elapsed, total, days_left
        )
    forecast = _forecast(metric, value, elapsed, total)
    target = goal.target
    if finished:
        state = State.ACHIEVED if meets(metric, value, target) else State.MISSED
    elif metric.kind == "level":
        state = _level_state(metric, value, baseline, target, Decimal(elapsed) / Decimal(total))
    else:
        state = _pace_state(metric, forecast, target, elapsed)
    return Evaluation(
        today,
        value,
        forecast,
        baseline,
        _progress(metric, value, forecast, baseline, target),
        state,
        elapsed,
        total,
        days_left,
    )


def evaluate_level(goal: Goal, today: date, value: Decimal) -> str:
    """The state a level goal would have on `today` at `value` (series of known levels)."""
    metric = METRICS[goal.metric]
    if today < goal.starts_on:
        return State.NOT_STARTED
    if today > goal.ends_on:
        return State.ACHIEVED if meets(metric, value, goal.target) else State.MISSED
    total = (goal.ends_on - goal.starts_on).days + 1
    elapsed = (today - goal.starts_on).days + 1
    return _level_state(metric, value, goal.baseline, goal.target, Decimal(elapsed) / total)


def meets(metric: MetricSpec, value: Decimal, target: Decimal) -> bool:
    return value >= target if metric.better == "up" else value <= target


def _forecast(metric: MetricSpec, value: Decimal, elapsed: int, total: int) -> Decimal:
    if metric.kind in ("sum", "rate") and elapsed:
        return (value * Decimal(total) / Decimal(elapsed)).quantize(Decimal("0.01"))
    return value


def _tolerance(metric: MetricSpec, target: Decimal) -> Decimal:
    near = target * NEAR
    if metric.unit == "percent":
        return max(near, ONE)
    return near


def _pace_state(metric: MetricSpec, forecast: Decimal, target: Decimal, elapsed: int) -> str:
    if meets(metric, forecast, target):
        return State.ON_TRACK
    tolerance = _tolerance(metric, target)
    close = (
        forecast >= target - tolerance if metric.better == "up" else forecast <= target + tolerance
    )
    if close or elapsed < EARLY_DAYS:
        return State.AT_RISK
    return State.OFF_TRACK


def _way(metric: MetricSpec, value: Decimal, baseline: Decimal | None, target: Decimal):
    """How much of the way from day one to the target is behind (0 to 1, more once past it);
    None when the target was met on day one already."""
    start = baseline if baseline is not None else value
    distance = target - start if metric.better == "up" else start - target
    if distance <= 0:
        return None
    done = value - start if metric.better == "up" else start - value
    return max(done / distance, ZERO)


def _level_state(metric, value, baseline, target, time_share: Decimal) -> str:
    if meets(metric, value, target):
        return State.ON_TRACK
    way = _way(metric, value, baseline, target)
    if way is None:  # met on day one, lost since
        return State.AT_RISK
    if way >= time_share - LEVEL_SLACK:
        return State.ON_TRACK
    if way >= time_share - LEVEL_RISK:
        return State.AT_RISK
    return State.OFF_TRACK


def _progress(metric, value, forecast, baseline, target) -> Decimal:
    if metric.better == "down":
        if forecast <= target:
            share = ONE
        elif forecast > 0:
            share = target / forecast
        else:
            share = ZERO
    elif metric.kind == "level":
        way = _way(metric, value, baseline, target)
        share = ONE if way is None else way
    else:
        share = value / target if target else ONE
    percent = (max(share, ZERO) * HUNDRED).quantize(Decimal("0.1"))
    return min(percent, MAX_PROGRESS)
