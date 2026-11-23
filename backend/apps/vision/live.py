"""The boxes' live state, in the Django cache (Redis) and never in the database (docs/KOZ.md
§5.5, §5.6, §6.3, §8):

    put_reports(agent_id, agent, cameras)  the latest live report: 30 s
    reports(camera_ids)                    {camera_id: report} of those still fresh
    agent_report(agent_id)                 the box's own numbers (version, fps, cpu) or None
    put_frame(camera_id, frame)            the latest frame of a watched camera: 10 s
    frame(camera_id)                       {at, w, h, people, jpeg} or None
    watch(camera_id) / watched(ids)        someone watches the camera live: 15 s
    seen_due(agent_id)                     True at most once a minute: time to write last_seen_at
    first_view(member_id, camera_id)       True once per person and camera per 10 minutes
"""

from django.core.cache import cache

LIVE_TTL = 30
FRAME_TTL = 10
WATCH_TTL = 15
SEEN_EVERY = 60
VIEW_AUDIT_EVERY = 10 * 60


def _key(*parts) -> str:
    return "vision:" + ":".join(str(part) for part in parts)


def put_reports(agent_id: int, agent: dict, cameras: dict[int, dict]) -> None:
    values = {_key("live", camera_id): report for camera_id, report in cameras.items()}
    values[_key("agent", agent_id)] = agent
    cache.set_many(values, LIVE_TTL)


def reports(camera_ids) -> dict[int, dict]:
    ids = list(camera_ids)
    if not ids:
        return {}
    found = cache.get_many([_key("live", camera_id) for camera_id in ids])
    return {
        camera_id: found[_key("live", camera_id)]
        for camera_id in ids
        if _key("live", camera_id) in found
    }


def agent_report(agent_id: int) -> dict | None:
    return cache.get(_key("agent", agent_id))


def put_frame(camera_id: int, frame: dict) -> None:
    cache.set(_key("frame", camera_id), frame, FRAME_TTL)


def frame(camera_id: int) -> dict | None:
    return cache.get(_key("frame", camera_id))


def watch(camera_id: int) -> None:
    cache.set(_key("watch", camera_id), 1, WATCH_TTL)


def watched(camera_ids) -> set[int]:
    ids = list(camera_ids)
    if not ids:
        return set()
    found = cache.get_many([_key("watch", camera_id) for camera_id in ids])
    return {camera_id for camera_id in ids if _key("watch", camera_id) in found}


def seen_due(agent_id: int) -> bool:
    return cache.add(_key("seen", agent_id), 1, SEEN_EVERY)


def first_view(member_id: int, camera_id: int) -> bool:
    return cache.add(_key("viewed", member_id, camera_id), 1, VIEW_AUDIT_EVERY)


def forget_seen(agent_id: int) -> None:
    """The next report writes last_seen_at at once (after pairing again, say)."""
    cache.delete(_key("seen", agent_id))
