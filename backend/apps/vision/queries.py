"""Reads of Ko‘z: what a box is told (`config`), the shapes the owner endpoints answer with
(cameras, boxes, alerts, clips, docs/KOZ.md §6) and the live page. The numbers of a day are in
`apps.vision.analytics`, the review list in `apps.vision.review`.

A function returning branch-bound data takes `branch_ids: list[int] | None`
(`apps.members.scope.branch_ids(member)`), as everywhere.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from django.db.models import QuerySet
from django.utils import timezone

from apps.core.files import signed_url
from apps.members import scope
from apps.vision import conf, demo_live, live
from apps.vision.models import Agent, Alert, Camera, Clip

# A snapshot someone asked for is asked of the box for this long.
SNAPSHOT_ASK = timedelta(minutes=10)
# No live report for this long: the camera's numbers are stale (§6.2).
STALE_AFTER = timedelta(seconds=live.LIVE_TTL)
# Links to files live this long (the dashboard asks again when it needs them later).
LINK_TTL = 600


def iso(moment: datetime | None) -> str | None:
    """UTC with Z, as the wire rules say (§3)."""
    if moment is None:
        return None
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ref(row) -> dict | None:
    return {"id": row.pk, "name": str(row)} if row is not None else None


def person(member) -> dict | None:
    if member is None:
        return None
    return {"id": member.pk, "name": member.full_name or str(member.user)}


# Boxes and cameras -------------------------------------------------------------------------


def agents(company, *, branch_ids) -> QuerySet[Agent]:
    """The company's boxes (not removed) in the scope."""
    rows = Agent.objects.filter(company=company, removed_at__isnull=True).select_related("branch")
    return scope.restrict(rows, branch_ids)


def cameras(company, *, branch_ids) -> QuerySet[Camera]:
    rows = Camera.objects.filter(company=company).select_related("branch", "agent", "register")
    return scope.restrict(rows, branch_ids)


def online(agent: Agent, now: datetime | None = None) -> bool:
    """A box is online while its live reports keep coming (the cache has one for 30 s)."""
    if agent.demo:
        return True
    return live.agent_report(agent.pk) is not None


def snapshot_pending(camera: Camera, now: datetime) -> bool:
    asked = camera.snapshot_requested_at
    return (
        asked is not None
        and asked > now - SNAPSHOT_ASK
        and (camera.snapshot_at is None or camera.snapshot_at < asked)
    )


def snapshot_keys(agent: Agent, now: datetime) -> list[str]:
    return sorted(
        camera.key
        for camera in agent.cameras.filter(snapshot_requested_at__gt=now - SNAPSHOT_ASK)
        if snapshot_pending(camera, now)
    )


def config(agent: Agent, now: datetime | None = None) -> dict:
    """GET config/ (§5.2). `config_version` is a short hash of everything else, so the box
    reads it again only when something changed."""
    now = now or timezone.now()
    settings = conf.get_settings(agent.company)
    body = {
        "agent": {
            "id": agent.pk,
            "name": agent.name,
            "branch": {"id": agent.branch_id, "name": agent.branch.name},
            "timezone": agent.company.timezone,
        },
        "rules": {
            "queue_people": settings.queue_people,
            "queue_wait_s": settings.queue_wait_s,
            "unattended_s": settings.unattended_s,
            "clear_after_s": settings.clear_after_s,
            "analysis_fps": settings.analysis_fps,
            "live_fps": settings.live_fps,
            "privacy_blur": settings.privacy_blur,
            "alert_photo": settings.alert_photo,
            "record_counter": settings.record_counter,
            "record_hours": settings.record_hours,
        },
        "cameras": [
            {
                "id": camera.pk,
                "key": camera.key,
                "name": camera.name,
                "role": camera.role,
                "enabled": camera.enabled,
                "zones": camera.zones or [],
                "register_id": camera.register_id,
            }
            for camera in agent.cameras.order_by("key")
        ],
        "snapshot_requested": snapshot_keys(agent, now),
    }
    return {"config_version": config_version(body), **body}


def config_version(body: dict) -> str:
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def pending_jobs(agent: Agent, now: datetime) -> int:
    """How many things the box should fetch from jobs/ now (§5.5)."""
    clips = Clip.objects.filter(camera__agent=agent, state=Clip.State.PENDING).count()
    return clips + len(snapshot_keys(agent, now))


# Owner shapes (§6) ---------------------------------------------------------------------------


def agent_row(agent: Agent, *, cameras: int | None = None, now=None) -> dict:
    return {
        "id": agent.pk,
        "name": agent.name,
        "branch": ref(agent.branch),
        "online": online(agent, now),
        "last_seen_at": iso(agent.last_seen_at),
        "version": agent.version or None,
        "host": {"hostname": agent.hostname, "os": agent.os}
        if (agent.hostname or agent.os)
        else None,
        "paired": agent.paired,
        "cameras": cameras if cameras is not None else agent.cameras.count(),
        "created_at": iso(agent.created_at),
    }


def agent_brief(agent: Agent) -> dict:
    """What the overview says about a box."""
    return {
        "id": agent.pk,
        "name": agent.name,
        "branch_id": agent.branch_id,
        "online": online(agent),
        "last_seen_at": iso(agent.last_seen_at),
        "version": agent.version or None,
    }


def camera_row(camera: Camera, *, user) -> dict:
    return {
        "id": camera.pk,
        "key": camera.key,
        "name": camera.name,
        "role": camera.role,
        "enabled": camera.enabled,
        "branch": ref(camera.branch),
        "agent_id": camera.agent_id,
        "source": camera.source or None,
        "channel": camera.channel,
        "w": camera.width,
        "h": camera.height,
        "online": camera.online,
        "last_seen_at": iso(camera.last_seen_at),
        "zones": camera.zones or [],
        "register": {"id": camera.register_id, "name": camera.register.name}
        if camera.register_id
        else None,
        "snapshot_url": signed_url(
            camera.snapshot,
            user=user,
            company_id=camera.company_id,
            check=f"vision.snapshot:{camera.pk}",
            ttl=LINK_TTL,
        )
        if camera.snapshot
        else None,
        "snapshot_at": iso(camera.snapshot_at),
    }


def alert_row(alert: Alert, *, user) -> dict:
    clip = _latest_clip(alert)
    return {
        "id": alert.pk,
        "kind": alert.kind,
        "state": alert.state,
        "branch": ref(alert.branch),
        "camera": ref(alert.camera),
        "started_at": iso(alert.started_at),
        "resolved_at": iso(alert.resolved_at),
        "duration_s": alert.duration_s,
        "peak_queue": alert.peak_queue,
        "peak_wait_s": alert.peak_wait_s,
        "acknowledged_by": person(alert.acknowledged_by),
        "acknowledged_at": iso(alert.acknowledged_at),
        "photo_url": signed_url(
            alert.photo,
            user=user,
            company_id=alert.company_id,
            check=f"vision.photo:{alert.pk}",
            ttl=LINK_TTL,
        )
        if alert.photo
        else None,
        "clip": {"id": clip.pk, "state": clip.state} if clip else None,
    }


def _latest_clip(alert: Alert) -> Clip | None:
    cache = getattr(alert, "_prefetched_objects_cache", {}).get("clips")
    if cache is not None:
        return max(cache, key=lambda clip: (clip.created_at, clip.pk), default=None)
    return alert.clips.order_by("-created_at", "-pk").first()


def alerts(company, *, branch_ids) -> QuerySet[Alert]:
    rows = Alert.objects.filter(company=company).select_related(
        "branch", "camera", "acknowledged_by__user"
    )
    return scope.restrict(rows, branch_ids).prefetch_related("clips")


def open_alerts(company, *, branch_ids, user) -> list[dict]:
    rows = alerts(company, branch_ids=branch_ids).filter(state=Alert.State.OPEN)
    return [alert_row(alert, user=user) for alert in rows[:50]]


def clip_row(clip: Clip, *, user) -> dict:
    def link(field) -> str | None:
        if not field:
            return None
        return signed_url(
            field,
            user=user,
            company_id=clip.company_id,
            check=f"vision.clip:{clip.pk}",
            ttl=LINK_TTL,
        )

    return {
        "id": clip.pk,
        "state": clip.state,
        "reason": clip.reason,
        "camera": ref(clip.camera),
        "start": iso(clip.start),
        "end": iso(clip.end),
        "sale_id": clip.sale_id,
        "alert_id": clip.alert_id,
        "video_url": link(clip.video),
        "poster_url": link(clip.poster),
        "duration_s": clip.duration_s,
        "failure": clip.failure or None,
        "failure_text": str(Clip.Failure(clip.failure).label) if clip.failure else None,
        "created_at": iso(clip.created_at),
    }


# The live page (§6.2) ------------------------------------------------------------------------


def live_page(company, *, branch_ids, user, now: datetime | None = None) -> dict:
    from apps.vision import analytics

    now = now or timezone.now()
    rows = list(
        cameras(company, branch_ids=branch_ids)
        .filter(agent__removed_at__isnull=True)
        .select_related("branch__company")
    )
    reports = live.reports(camera.pk for camera in rows if not camera.agent.demo)
    found = []
    for camera in rows:
        if camera.agent.demo:
            report = demo_live.camera_report(camera, now)
        else:
            report = reports.get(camera.pk)
        found.append(
            {
                "id": camera.pk,
                "name": camera.name,
                "role": camera.role,
                "branch_id": camera.branch_id,
                "online": bool(report and report.get("online")),
                "stale": report is None,
                "people": report.get("people") if report else None,
                "queue": report.get("queue") if report else None,
                "staff": report.get("staff") if report else None,
                "wait_s": report.get("wait_s") if report else None,
                "fps": report.get("fps") if report else None,
            }
        )
    return {
        "at": iso(now),
        "today": analytics.today_counts(company, branch_ids=branch_ids, now=now),
        "cameras": found,
        "open_alerts": open_alerts(company, branch_ids=branch_ids, user=user),
    }


def camera_in(company, pk, *, branch_ids) -> Camera | None:
    return cameras(company, branch_ids=branch_ids).filter(pk=pk).first()


def branch_cameras(branch_id: int) -> QuerySet[Camera]:
    return Camera.objects.filter(branch_id=branch_id, agent__removed_at__isnull=True)


def counter_camera(sale) -> Camera | None:
    """The camera that films a sale's till: the one mapped to its register, else the branch's
    first enabled counter camera (§6.6)."""
    if sale.register_id:
        mapped = (
            Camera.objects.filter(company_id=sale.company_id, register_id=sale.register_id)
            .order_by("-enabled", "pk")
            .first()
        )
        if mapped is not None:
            return mapped
    return (
        Camera.objects.filter(
            company_id=sale.company_id,
            branch_id=sale.branch_id,
            role=Camera.Role.COUNTER,
            enabled=True,
        )
        .order_by("pk")
        .first()
    )


def clip_like(camera: Camera, start: datetime, end: datetime) -> Clip | None:
    """A clip of the same camera and window (±2 s) that isn't a failure (§6.6)."""
    slack = timedelta(seconds=2)
    return (
        Clip.objects.filter(
            camera=camera,
            start__range=(start - slack, start + slack),
            end__range=(end - slack, end + slack),
        )
        .exclude(state=Clip.State.FAILED)
        .order_by("-created_at", "-pk")
        .first()
    )
