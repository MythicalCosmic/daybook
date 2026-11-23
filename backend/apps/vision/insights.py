"""The overview's sentences (docs/KOZ.md §6.1): built by the server from the day's numbers with
fixed templates in the reader's language. Deterministic, no AI: the same numbers always give
the same sentences. At most four, the most important first.

- `lost_peak` (bad): the hour with the most people leaving without buying, when at least 10 did
  and the longest wait that hour reached the company's queue wait;
- `staff_gap` (warn): an hour with two or more people checked in while customers waited with
  nobody at the counter for 3 minutes or more;
- `unattended` (warn, bad from 30): 5 minutes or more of customers waiting and nobody at the
  counter over the day;
- `long_wait` (warn): the day's longest wait reached the queue wait (unless the lost peak is
  that same hour);
- `good_day` (good): conversion 2 points or more above the same weekday a week before.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext as _

from apps.vision.bot_messages import duration

MOST = 4
LOST_AT_LEAST = 10
GAP_MINUTES = 3
GAP_PEOPLE = 2
UNATTENDED_MINUTES = 5
UNATTENDED_BAD = 30
BETTER_BY = 0.02


class Kind(models.TextChoices):
    LOST_PEAK = "lost_peak"
    LONG_WAIT = "long_wait"
    UNATTENDED = "unattended"
    STAFF_GAP = "staff_gap"
    GOOD_DAY = "good_day"


class Severity(models.TextChoices):
    INFO = "info"
    WARN = "warn"
    BAD = "bad"
    GOOD = "good"


ORDER = [Kind.LOST_PEAK, Kind.STAFF_GAP, Kind.UNATTENDED, Kind.LONG_WAIT, Kind.GOOD_DAY]
RANK = {Severity.BAD: 0, Severity.WARN: 1, Severity.GOOD: 2, Severity.INFO: 3}


def span(hour: int) -> dict:
    return {"start": f"{hour:02d}:00", "end": f"{(hour + 1) % 24:02d}:00"}


def percent(value: float) -> str:
    return f"{round(value * 100)}%"


def build(hours: list[dict], totals: dict, settings) -> list[dict]:
    found = []

    def add(kind, severity, hour, text):
        found.append({"kind": kind, "severity": severity, "hour": hour, "text": text})

    lost_hour = None
    known = [row for row in hours if row["visitors"] is not None and row["receipts"] is not None]
    if known:
        peak = max(known, key=lambda row: (row["visitors"] - row["receipts"], -row["hour"]))
        gone = peak["visitors"] - peak["receipts"]
        if gone >= LOST_AT_LEAST and peak["wait_max_s"] >= settings.queue_wait_s:
            lost_hour = peak["hour"]
            add(
                Kind.LOST_PEAK,
                Severity.BAD,
                peak["hour"],
                _(
                    "%(start)s–%(end)s: %(visitors)s people came in, %(receipts)s bought. The "
                    "queue reached %(queue)s and %(left)s people left without buying."
                )
                % {
                    **span(peak["hour"]),
                    "visitors": peak["visitors"],
                    "receipts": peak["receipts"],
                    "queue": peak["queue_max"],
                    "left": gone,
                },
            )

    gaps = [
        row
        for row in hours
        if (row["staff_checked_in"] or 0) >= GAP_PEOPLE and row["unattended_minutes"] >= GAP_MINUTES
    ]
    if gaps:
        gap = max(gaps, key=lambda row: (row["unattended_minutes"], -row["hour"]))
        add(
            Kind.STAFF_GAP,
            Severity.WARN,
            gap["hour"],
            _(
                "%(start)s–%(end)s: %(people)s people were checked in, yet customers waited "
                "%(minutes)s min with nobody at the counter."
            )
            % {
                **span(gap["hour"]),
                "people": gap["staff_checked_in"],
                "minutes": gap["unattended_minutes"],
            },
        )

    alone = totals.get("unattended_minutes") or 0
    if alone >= UNATTENDED_MINUTES:
        worst = max(hours, key=lambda row: (row["unattended_minutes"], -row["hour"]))
        add(
            Kind.UNATTENDED,
            Severity.BAD if alone >= UNATTENDED_BAD else Severity.WARN,
            worst["hour"],
            _(
                "Customers waited with nobody at the counter for %(minutes)s min today, most "
                "at %(start)s–%(end)s."
            )
            % {**span(worst["hour"]), "minutes": alone},
        )

    longest = totals.get("wait_max_s") or 0
    if longest >= settings.queue_wait_s:
        slow = max(hours, key=lambda row: (row["wait_max_s"], -row["hour"]))
        if slow["hour"] != lost_hour:
            add(
                Kind.LONG_WAIT,
                Severity.WARN,
                slow["hour"],
                _("The longest wait was %(wait)s, at %(start)s–%(end)s.")
                % {**span(slow["hour"]), "wait": duration(longest)},
            )

    now, before = totals.get("conversion"), (totals.get("compare") or {}).get("conversion")
    if now is not None and before is not None and now - before >= BETTER_BY:
        add(
            Kind.GOOD_DAY,
            Severity.GOOD,
            None,
            _("Conversion %(now)s, the same day a week ago %(before)s.")
            % {"now": percent(now), "before": percent(before)},
        )

    found.sort(key=lambda item: (RANK[item["severity"]], ORDER.index(item["kind"])))
    return found[:MOST]
