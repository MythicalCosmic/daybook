"""A terminal's post, made by us: the setup card's "Simulate a face" and the demo send what a
MinMoe terminal would (the same multipart body, the same JSON fields), so the whole flow can be
seen before a real terminal is set up. The snapshot is a drawn silhouette, never a face."""

import hashlib
import io
import json

from django.utils import timezone
from PIL import Image, ImageDraw

from apps.attendance import clock
from apps.faceid.models import FaceLink

BOUNDARY = "MIME_boundary"
# Soft backgrounds and the silhouette's colour on each (the dashboard's chart palette, lighter).
PALETTES = (
    ((222, 236, 255), (120, 150, 200)),
    ((226, 245, 236), (105, 160, 130)),
    ((255, 240, 226), (200, 140, 100)),
    ((240, 232, 255), (140, 120, 190)),
    ((255, 233, 240), (190, 110, 140)),
    ((236, 240, 245), (120, 130, 150)),
)


def silhouette(seed: str, size=(240, 300)) -> bytes:
    """A head and shoulders on a pastel background, the same for the same `seed`."""
    digest = hashlib.sha256(seed.encode()).digest()
    background, figure = PALETTES[digest[0] % len(PALETTES)]
    width, height = size
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    head = width * 0.2
    centre_x, centre_y = width / 2, height * 0.4
    draw.ellipse(
        (centre_x - head, centre_y - head * 1.15, centre_x + head, centre_y + head * 1.05),
        fill=figure,
    )
    draw.ellipse(
        (width * 0.14, height * 0.68, width * 0.86, height * 1.25),
        fill=figure,
    )
    out = io.BytesIO()
    image.save(out, "JPEG", quality=82)
    return out.getvalue()


def event_json(device, *, number: str, name: str, serial: int | None, at=None, minor=75) -> dict:
    at = at or timezone.now()
    return {
        "ipAddress": device.ip or "192.168.1.250",
        "portNo": 80,
        "protocol": "HTTP",
        "macAddress": device.mac or "",
        "channelID": 1,
        "dateTime": clock.local(device.company, at).isoformat(timespec="seconds"),
        "activePostCount": 1,
        "eventType": "AccessControllerEvent",
        "eventState": "active",
        "eventDescription": "Access Controller Event",
        "AccessControllerEvent": {
            "deviceName": device.name,
            "majorEventType": 5,
            "subEventType": minor,
            "name": name,
            "employeeNoString": number,
            "serialNo": serial,
            "userType": "normal",
            "currentVerifyMode": "cardOrFaceOrFp",
            "attendanceStatus": "undefined",
            "mask": "no",
            "picturesNumber": 1,
        },
    }


def multipart(data: dict, picture: bytes | None) -> tuple[str, bytes]:
    delimiter = f"--{BOUNDARY}".encode()
    payload = json.dumps(data, indent="\t", ensure_ascii=False).encode()
    lines = [
        delimiter,
        b'Content-Disposition: form-data; name="event_log"',
        b"Content-Type: application/json",
        b"",
        payload,
    ]
    if picture is not None:
        lines += [
            delimiter,
            b'Content-Disposition: form-data; name="Picture"; filename="Picture.jpg"',
            b"Content-Type: image/jpeg",
            b"",
            picture,
        ]
    lines += [delimiter + b"--", b""]
    return f"multipart/form-data; boundary={BOUNDARY}", b"\r\n".join(lines)


def body_for(device, member) -> tuple[str, bytes]:
    """A test scan of `member` at `device`: their number when they have one."""
    link = FaceLink.objects.filter(company_id=device.company_id, membership=member).first()
    number = link.employee_no if link is not None else "TEST"
    name = member.full_name or str(member.user)
    data = event_json(device, number=number, name=name, serial=None)
    return multipart(data, silhouette(f"test:{member.pk}"))
