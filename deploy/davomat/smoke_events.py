"""Terminal events for deploy/davomat/smoke.sh, made inside the Davomat image from the golden
payloads of `apps/faceid/tests/samples.py`: the owner's DS-K1T341AMF as its HTTP Listening posts
them (multipart, the event JSON tab-indented as the firmware writes it, a zero-padded Employee
No, a first name in Cyrillic, the snapshot), and a heartbeat.

    docker run --rm -v <checkout>/deploy/davomat:/davomat:ro --entrypoint python davomat:latest \
        /davomat/smoke_events.py

Prints `{"at": ..., "<name>": {"content_type": ..., "body": <base64>}, ...}`. The scans are dated
now in Tashkent's time (the smoke organization's zone), a few seconds apart.
"""

import base64
import json
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/backend")

from apps.faceid.tests import samples

TASHKENT = timezone(timedelta(hours=5))


def pack(content_type: str, body: bytes) -> dict:
    return {"content_type": content_type, "body": base64.b64encode(body).decode()}


def main() -> None:
    now = datetime.now(TASHKENT).replace(microsecond=0) - timedelta(seconds=30)
    first = samples.k1t341amf(number="00000002", name="Гулирано", serial=40585, at=now.isoformat())
    second = samples.k1t341amf(
        number="00000004",
        name="Zulfiya",
        serial=40586,
        at=(now + timedelta(seconds=20)).isoformat(),
    )
    heartbeat = json.dumps(samples.heartbeat(at=now.isoformat())).encode()
    events = {
        "at": now.isoformat(),
        "heartbeat": pack("application/json", heartbeat),
        "first": pack(*samples.multipart(first, picture=samples.jpeg())),
        "second": pack(*samples.multipart(second, picture=samples.jpeg(color=(120, 140, 170)))),
    }
    json.dump(events, sys.stdout)


if __name__ == "__main__":
    main()
