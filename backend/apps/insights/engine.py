"""Running the detection rules for a company and keeping its insights current.

`run(company)` asks every enabled rule (`detectors.enabled`) what it finds and stores it:

- a finding whose key is new opens an insight;
- one already open (or seen) updates its numbers, words and severity; turning urgent makes it
  notify again;
- one that was resolved (or dismissed and gone since) opens again once a day has passed
  (`COOLDOWN`), so a number swinging around a threshold never flaps;
- a dismissed one that is still true stays dismissed: dismissing silences that occurrence;
- an open insight its rule no longer finds is resolved (a dismissed one records it too), and
  its Telegram buttons go.

A rule that fails is logged and its insights are left as they were. Then the urgent insights
nobody heard about go to the owner bot, outside the company's quiet hours
(`notify_pending`, also run on its own every half hour by the beat).

`tick(now)` is the beat's entry point: each company once per slot of its day (07:00, 13:00 and
19:00 company time), and the pending urgent ones.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone, translation

from apps.console import pulse
from apps.insights import conf, detectors, texts
from apps.insights.models import Insight, InsightSettings

logger = logging.getLogger(__name__)

PULSE = "insights.open"
COOLDOWN = timedelta(hours=24)
RUN_HOURS = (7, 13, 19)  # company-local hours the rules run at
SEVERITY_RANK = {
    Insight.Severity.INFO: 0,
    Insight.Severity.WARNING: 1,
    Insight.Severity.CRITICAL: 2,
}


def local_now(company, now: datetime | None = None) -> datetime:
    return timezone.localtime(now or timezone.now(), ZoneInfo(company.timezone))


def run(company, now: datetime | None = None, *, notify: bool = True) -> dict:
    """Run every enabled rule for `company` (as of `now`) and store what they find. Returns
    {"created", "updated", "reopened", "resolved", "failed", "notified"}."""
    now = now or timezone.now()
    settings_row = conf.get_settings(company)
    ctx = detectors.Context(
        company=company, today=local_now(company, now).date(), now=now, settings=settings_row
    )
    counts = dict.fromkeys(("created", "updated", "reopened", "resolved", "failed"), 0)
    with translation.override(company.default_language):
        for rule in detectors.enabled(company, settings_row):
            try:
                with transaction.atomic():
                    findings = rule.detect(ctx)
                    keys = set()
                    for finding in findings:
                        keys.add(finding.key)
                        counts[_store(company, rule, finding, now)] += 1
                    counts["resolved"] += _resolve_gone(company, rule.kind, keys, now)
            except Exception:  # one rule's trouble never stops the others
                counts["failed"] += 1
                logger.exception("Insight rule %s failed for company %s", rule.kind, company.pk)
    InsightSettings.objects.filter(pk=settings_row.pk).update(last_run_at=now)
    transaction.on_commit(lambda: pulse.bump(company.pk, PULSE))
    counts["notified"] = notify_pending(company, now) if notify else 0
    return counts


def _store(company, rule, finding: detectors.Finding, now: datetime) -> str:
    """Create or update the insight of `finding`; returns which of the counters it moved."""
    words = texts.render(
        rule.kind,
        finding.metrics,
        branch=_branch_name(company, finding.branch_id),
        subject=finding.subject_label,
    )
    values = {
        "kind": rule.kind,
        "domain": rule.domain,
        "severity": finding.severity,
        "branch_id": finding.branch_id,
        "subject_type": finding.subject_type,
        "subject_id": finding.subject_id,
        "subject_label": finding.subject_label[:200],
        "window_start": finding.window_start,
        "window_end": finding.window_end,
        "metrics": finding.metrics,
        "title": words.title[:200],
        "explanation": words.explanation,
        "suggested_action": words.action[:300],
        "explained_by": Insight.ExplainedBy.TEMPLATE,
        "last_seen_at": now,
    }
    insight = (
        Insight.objects.select_for_update().filter(company=company, dedupe_key=finding.key).first()
    )
    if insight is None:
        Insight.objects.create(
            company=company,
            dedupe_key=finding.key,
            status=Insight.Status.OPEN,
            detected_at=now,
            **values,
        )
        return "created"
    if insight.is_live:
        louder = SEVERITY_RANK[finding.severity] > SEVERITY_RANK.get(insight.severity, 0)
        if louder and finding.severity == Insight.Severity.CRITICAL:
            values["notified_at"] = None
        _update(insight, values)
        return "updated"
    gone_since = insight.resolved_at
    if gone_since is not None and now - gone_since >= COOLDOWN:
        # It went away and came back: a new occurrence, heard about afresh.
        _update(
            insight,
            {
                **values,
                "status": Insight.Status.OPEN,
                "detected_at": now,
                "notified_at": None,
                "acknowledged_by": None,
                "acknowledged_at": None,
                "dismissed_by": None,
                "dismissed_at": None,
                "dismissed_reason": "",
                "resolved_at": None,
                "task": None,
            },
        )
        return "reopened"
    # Dismissed and still true, or back within the cooldown: it stays as it is.
    Insight.objects.filter(pk=insight.pk).update(last_seen_at=now)
    return "updated"


def _update(insight: Insight, values: dict) -> None:
    for name, value in values.items():
        setattr(insight, name, value)
    insight.save()


def _resolve_gone(company, kind: str, keys: set[str], now: datetime) -> int:
    """Resolve the insights of `kind` the rule didn't find this time."""
    from apps.inbox import services as inbox

    live = list(
        Insight.objects.select_for_update()
        .filter(company=company, kind=kind, status__in=Insight.LIVE)
        .exclude(dedupe_key__in=keys)
    )
    for insight in live:
        insight.status = Insight.Status.RESOLVED
        insight.resolved_at = now
        insight.save(update_fields=["status", "resolved_at", "updated_at"])
        inbox.settle(insight, outcome=_resolved_text)
    # A dismissed one that is gone: noted, so it can come back as a new occurrence.
    Insight.objects.filter(
        company=company, kind=kind, status=Insight.Status.DISMISSED, resolved_at__isnull=True
    ).exclude(dedupe_key__in=keys).update(resolved_at=now)
    return len(live)


def _resolved_text(person) -> str:
    from django.utils.translation import gettext as _

    return _("No longer the case")


def _branch_name(company, branch_id: int | None) -> str:
    if branch_id is None:
        return ""
    from apps.companies.models import Branch

    return (
        Branch.objects.filter(company=company, pk=branch_id).values_list("name", flat=True).first()
        or ""
    )


# Telegram -----------------------------------------------------------------------------------


def in_quiet_hours(settings_row: InsightSettings, moment: time) -> bool:
    start, end = settings_row.quiet_from, settings_row.quiet_to
    if start == end:
        return False
    if start < end:
        return start <= moment < end
    return moment >= start or moment < end


def notify_pending(company, now: datetime | None = None) -> int:
    """Send the urgent open insights nobody heard about yet, unless it is quiet time or the
    company doesn't want them in Telegram. Returns how many insights went out."""
    from apps.insights import notify

    now = now or timezone.now()
    settings_row = conf.get_settings(company)
    if not settings_row.notify_critical_via_bot:
        return 0
    if in_quiet_hours(settings_row, local_now(company, now).time()):
        return 0
    pending = list(
        Insight.objects.filter(
            company=company,
            status=Insight.Status.OPEN,
            severity=Insight.Severity.CRITICAL,
            notified_at__isnull=True,
        ).select_related("company", "branch")
    )
    sent = 0
    for insight in pending:
        with transaction.atomic():
            notify.critical(insight)
            Insight.objects.filter(pk=insight.pk).update(notified_at=now)
        sent += 1
    return sent


def due(company, settings_row: InsightSettings, now: datetime) -> bool:
    """Whether the rules should run for the company now: a run slot of its day has started
    since the last run."""
    local = local_now(company, now)
    slots = [hour for hour in RUN_HOURS if hour <= local.hour]
    if not slots:
        return False
    slot_start = local.replace(hour=slots[-1], minute=0, second=0, microsecond=0)
    last = settings_row.last_run_at
    return last is None or last < slot_start


def tick(now: datetime | None = None) -> dict:
    """The beat's half-hourly call: run the rules where a slot started, and send what waits."""
    from apps.companies.models import Company

    now = now or timezone.now()
    ran = notified = 0
    for company in Company.objects.filter(is_active=True).order_by("pk"):
        try:
            settings_row = conf.get_settings(company)
            if not detectors.enabled(company, settings_row):
                continue
            if due(company, settings_row, now):
                result = run(company, now)
                ran += 1
                notified += result["notified"]
            else:
                notified += notify_pending(company, now)
        except Exception:  # one company's trouble never stops the others
            logger.exception("Insights failed for company %s", company.pk)
    return {"ran": ran, "notified": notified}
