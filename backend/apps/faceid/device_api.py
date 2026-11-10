"""The address Face ID terminals post their events to: `/api/v1/devices/hik/<code>/`.

A terminal's HTTP Listening (Configuration > Network > Advanced Settings > HTTP Listening on a
MinMoe DS-K1T341AMF) posts every event here, over plain HTTP on firmware without HTTPS, and
retries whatever wasn't answered with 200 (stored events come in a burst after an outage). So:

* any request with a known code answers **200** quickly, even an event we ignore or can't read
  (the reason is logged and the body kept); an unknown code answers 404; a GET answers 200 (the
  terminal's "Test" button) with how far the terminal's upload of its stored history has come:
  counts and a date only (`deploy/faceid/catchup.py` stops by it);
* no session, token or CSRF (the code in the path is the secret: 144 random bits), a throttle per
  code, bodies up to 8 MB (Caddy has the same limit);
* the body is read here (multipart, JSON or XML: `hikvision.parse`), then `services.receive`.
"""

import logging

from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.attendance import clock
from apps.faceid import hikvision, services
from apps.faceid.models import FaceDevice

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 8 * 1024 * 1024
# Requests per code per minute: a burst after an outage goes at the terminal's own pace (it
# waits for each answer), and a 429 only slows it down: it retries what wasn't answered with 200.
RATE_PER_MINUTE = 1200
OK = {"statusCode": 200, "statusString": "OK", "subStatusCode": "ok"}


def _allowed(token: str) -> bool:
    """A fixed one-minute window per code, counted with one atomic increment."""
    window = int(timezone.now().timestamp() // 60)
    key = f"faceid:throttle:{token}:{window}"
    if cache.add(key, 1, 61):
        return True
    try:
        return cache.incr(key) <= RATE_PER_MINUTE
    except ValueError:  # expired in between
        cache.set(key, 1, 61)
        return True


def history(device: FaceDevice) -> dict:
    """The terminal's upload of its stored history: still coming (`active`: some came in the last
    10 minutes), how many old scans were skipped, the newest one's time in the company's zone.
    Nothing personal: the code in the URL is the secret, and this is all it tells."""
    until = device.history_until
    return {
        "active": services.history_active(device),
        "skipped": device.history_skipped,
        "until": clock.local(device.company, until).isoformat() if until else None,
    }


def _read_body(request) -> bytes | None:
    """The raw body, at most MAX_BODY_BYTES (None when bigger). Read from the stream, so
    Django's form limits never refuse a snapshot; a chunked body (no Content-Length) is read
    from the server's input directly."""
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > MAX_BODY_BYTES:
        return None
    if length:
        return request.read(MAX_BODY_BYTES + 1)
    stream = request.META.get("wsgi.input")
    if stream is None or "chunked" not in request.META.get("HTTP_TRANSFER_ENCODING", "").lower():
        return b""
    data = stream.read(MAX_BODY_BYTES + 1)
    return None if len(data) > MAX_BODY_BYTES else data


@method_decorator(csrf_exempt, name="dispatch")
class HikvisionView(View):
    http_method_names = ["get", "post", "put", "head"]

    def device(self, token: str) -> FaceDevice | None:
        return FaceDevice.objects.select_related("company", "branch").filter(token=token).first()

    def get(self, request, token: str):
        device = self.device(token)
        if device is None:
            return HttpResponse(status=404)
        return JsonResponse(OK | {"history": history(device)})

    def head(self, request, token: str):
        return self.get(request, token)

    def post(self, request, token: str):
        if not _allowed(token):
            return HttpResponse(status=429, headers={"Retry-After": "5"})
        device = self.device(token)
        if device is None:
            return HttpResponse(status=404)
        body = _read_body(request)
        if body is None:
            return HttpResponse(status=413)
        received_at = timezone.now()
        parsed = hikvision.parse(request.META.get("CONTENT_TYPE", ""), body)
        try:
            services.receive(device, parsed, received_at=received_at)
        except Exception:
            # A terminal retries a refused event forever and holds back the ones after it:
            # one we couldn't handle is logged and answered like the others.
            logger.exception("Face ID terminal %s: an event couldn't be handled", device.pk)
        return JsonResponse(OK)

    def put(self, request, token: str):
        return self.post(request, token)
