"""Small things the Ko‘z tests share: pictures, a box's calls, a moment on the reference day."""

import io
import json
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

DEVICE = "/api/v1/devices/koz/"


def jpeg(width: int = 640, height: int = 360, color=(40, 90, 160)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, "JPEG", quality=80)
    return out.getvalue()


def upload(data: bytes, name: str = "frame.jpg", content_type: str = "image/jpeg"):
    return SimpleUploadedFile(name, data, content_type=content_type)


def mp4(size: int = 4096) -> bytes:
    """Bytes that start like an MP4 file (an `ftyp` box), padded to `size`."""
    head = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
    return head + b"\x00" * max(size - len(head), 0)


def owner_url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/vision/{path}"


def event(**fields) -> dict:
    values = {
        "event_id": str(uuid.uuid4()),
        "incident_id": str(uuid.uuid4()),
        "kind": "queue",
        "phase": "start",
        "key": "nvr:3",
        "at": "2026-10-21T13:31:05Z",
        "started_at": "2026-10-21T13:31:05Z",
        "queue": 3,
        "wait_s": 130,
        "staff": 1,
        "peak_queue": 3,
        "peak_wait_s": 130,
    }
    values.update(fields)
    return values


def post_event(client, values: dict, picture: bytes | None = None):
    data = {"event": json.dumps(values)}
    if picture is not None:
        data["image"] = upload(picture)
    return client.post(f"{DEVICE}events/", data, format="multipart")
