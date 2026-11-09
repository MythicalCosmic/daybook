"""Golden payloads of a Hikvision MinMoe terminal (DS-K1T341AMF, firmware V3.2.x), the way its
HTTP Listening posts them: a multipart body with the event JSON (tab-indented, as the
firmware writes it) and the snapshot, the bare JSON, and the older ISAPI XML."""

import io
import json

from PIL import Image

BOUNDARY = "MIME_boundary"


def jpeg(size=(64, 80), color=(200, 160, 140)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


def event(
    *,
    minor=75,
    number="12",
    name="Alisher Valiyev",
    serial=1234,
    at="2026-10-21T08:57:12+05:00",
    status="undefined",
    mode="cardOrFaceOrFp",
    major=5,
    **extra,
) -> dict:
    inner = {
        "deviceName": "Access Controller",
        "majorEventType": major,
        "subEventType": minor,
        "name": name,
        "cardReaderKind": 1,
        "cardReaderNo": 1,
        "verifyNo": 133,
        "employeeNoString": number,
        "serialNo": serial,
        "userType": "normal",
        "currentVerifyMode": mode,
        "frontSerialNo": serial - 1 if serial else 0,
        "attendanceStatus": status,
        "label": "",
        "statusValue": 0,
        "mask": "no",
        "helmet": "unknown",
        "picturesNumber": 1,
        "purePwdVerifyEnable": True,
        "FaceRect": {"height": 0.31, "width": 0.22, "x": 0.39, "y": 0.18},
    }
    inner.update(extra)
    if number is None:
        inner.pop("employeeNoString")
    return {
        "ipAddress": "192.168.1.250",
        "portNo": 80,
        "protocol": "HTTP",
        "macAddress": "e8:a0:ed:12:34:56",
        "channelID": 1,
        "dateTime": at,
        "activePostCount": 1,
        "eventType": "AccessControllerEvent",
        "eventState": "active",
        "eventDescription": "Access Controller Event",
        "AccessControllerEvent": inner,
    }


def heartbeat(at="2026-10-21T08:57:12+05:00") -> dict:
    return {
        "ipAddress": "192.168.1.250",
        "portNo": 80,
        "protocol": "HTTP",
        "macAddress": "e8:a0:ed:12:34:56",
        "channelID": 1,
        "dateTime": at,
        "activePostCount": 1,
        "eventType": "heartBeat",
        "eventState": "active",
        "eventDescription": "heartBeat",
    }


def tabbed(data: dict) -> bytes:
    """The firmware's own JSON layout: tabs, a tab after each colon."""
    return json.dumps(data, indent="\t", ensure_ascii=False).replace('": ', '":\t').encode()


def multipart(
    data: dict | bytes | None,
    *,
    part="AccessControllerEvent",
    part_type="application/json",
    picture: bytes | None = None,
    boundary=BOUNDARY,
    newline=b"\r\n",
) -> tuple[str, bytes]:
    """(content type, body) of a multipart event, the JSON part first, then the picture."""
    lines = []
    delimiter = f"--{boundary}".encode()
    if data is not None:
        payload = data if isinstance(data, bytes) else tabbed(data)
        lines.append(delimiter)
        lines.append(f'Content-Disposition: form-data; name="{part}"'.encode())
        if part_type:
            lines.append(f"Content-Type: {part_type}".encode())
        lines.append(f"Content-Length: {len(payload)}".encode())
        lines.append(b"")
        lines.append(payload)
    if picture is not None:
        lines.append(delimiter)
        lines.append(b'Content-Disposition: form-data; name="Picture"; filename="Picture.jpg"')
        lines.append(b"Content-Type: image/jpeg")
        lines.append(f"Content-Length: {len(picture)}".encode())
        lines.append(b"")
        lines.append(picture)
    lines.append(delimiter + b"--")
    lines.append(b"")
    return f"multipart/form-data; boundary={boundary}", newline.join(lines)


def xml(*, minor=75, number="12", name="Alisher Valiyev", serial=1234, at=None) -> bytes:
    at = at or "2026-10-21T08:57:12+05:00"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<EventNotificationAlert version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">
<ipAddress>192.168.1.250</ipAddress>
<portNo>80</portNo>
<protocol>HTTP</protocol>
<macAddress>e8:a0:ed:12:34:56</macAddress>
<channelID>1</channelID>
<dateTime>{at}</dateTime>
<activePostCount>1</activePostCount>
<eventType>AccessControllerEvent</eventType>
<eventState>active</eventState>
<eventDescription>Access Controller Event</eventDescription>
<AccessControllerEvent>
<deviceName>Access Controller</deviceName>
<majorEventType>5</majorEventType>
<subEventType>{minor}</subEventType>
<name>{name}</name>
<employeeNoString>{number}</employeeNoString>
<serialNo>{serial}</serialNo>
<currentVerifyMode>face</currentVerifyMode>
<attendanceStatus>checkIn</attendanceStatus>
</AccessControllerEvent>
</EventNotificationAlert>""".encode()
