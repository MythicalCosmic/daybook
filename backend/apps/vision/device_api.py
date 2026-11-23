"""The device API of the Ko‘z boxes, mounted at `/api/v1/devices/koz/` (docs/KOZ.md §5).

Every call but `pair/` carries `Authorization: Bearer koz_…`; a wrong or revoked token answers
401 `revoked` (the box then tries every 10 minutes), a box of a company whose Ko‘z is off 403
`module_off`. Errors are `{"detail": "...", "code": "..."}`. Bodies are JSON, or multipart where
a picture or a video comes along (JPEG ≤ 1.5 MB, a live frame ≤ 400 KB, MP4 ≤ 40 MB). No
session, no CSRF, no throttle but pairing's (10 tries per address per 10 minutes). Not in the
API schemas: the boxes are no dashboard client.
"""

from __future__ import annotations

import json
from datetime import UTC

from django.core.cache import cache
from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework import exceptions, status
from rest_framework.authentication import BaseAuthentication
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from apps.core.exceptions import DomainError
from apps.vision import conf, queries, services
from apps.vision.device_serializers import (
    MAX_STAT_ROWS,
    ClipFailureSerializer,
    ClipMetaSerializer,
    EventSerializer,
    FrameMetaSerializer,
    InventorySerializer,
    LiveSerializer,
    PairSerializer,
    StatsSerializer,
)
from apps.vision.errors import VisionError
from apps.vision.models import Agent

PAIR_TRIES = 10
PAIR_WINDOW = 10 * 60


class Box:
    """`request.user` of a box's call: a box, not a person."""

    is_authenticated = True
    is_active = True
    is_staff = False
    pk = None

    def __init__(self, agent: Agent):
        self.agent = agent


class BoxToken(BaseAuthentication):
    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header:
            return None
        scheme, _space, token = header.partition(" ")
        agent = services.authenticate(token.strip()) if scheme.lower() == "bearer" else None
        if agent is None:
            raise exceptions.AuthenticationFailed(
                _("This box isn't paired any more. Pair it again."), code="revoked"
            )
        return Box(agent), agent

    def authenticate_header(self, request):
        return 'Bearer realm="koz"'


class IsBox(BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.auth, Agent)


def answer(detail: str, code: str, status_code: int, headers: dict | None = None) -> Response:
    return Response({"detail": detail, "code": code}, status=status_code, headers=headers)


def first_message(detail) -> str:
    """The first message of a validation error, wherever it sits."""
    if isinstance(detail, dict):
        for value in detail.values():
            return first_message(value)
    if isinstance(detail, list) and detail:
        return first_message(detail[0])
    return str(detail)


def device_errors(exc, context) -> Response | None:
    """Every refusal as `{"detail", "code"}` (§3)."""
    if isinstance(exc, VisionError):
        return answer(str(exc), exc.code, exc.status)
    if isinstance(exc, exceptions.NotAuthenticated | exceptions.AuthenticationFailed):
        detail = (
            exc.detail
            if isinstance(exc, exceptions.AuthenticationFailed)
            else _("This box isn't paired any more. Pair it again.")
        )
        return answer(
            str(detail), "revoked", status.HTTP_401_UNAUTHORIZED, {"WWW-Authenticate": "Bearer"}
        )
    if isinstance(exc, exceptions.ValidationError):
        response = answer(first_message(exc.detail), "invalid", status.HTTP_400_BAD_REQUEST)
        response.data["errors"] = exc.detail
        return response
    if isinstance(exc, exceptions.Throttled):
        wait = int(exc.wait or PAIR_WINDOW)
        return answer(
            _("Too many tries. Wait a few minutes and try again."),
            "throttled",
            status.HTTP_429_TOO_MANY_REQUESTS,
            {"Retry-After": str(wait)},
        )
    if isinstance(exc, exceptions.APIException):
        codes = exc.get_codes()
        return answer(
            str(exc.detail), codes if isinstance(codes, str) else "error", exc.status_code
        )
    if isinstance(exc, Http404):
        return answer(_("Not found."), "not_found", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, DomainError):
        return answer(str(exc), "invalid", status.HTTP_400_BAD_REQUEST)
    return None


class DeviceView(APIView):
    authentication_classes = (BoxToken,)
    permission_classes = (IsBox,)
    throttle_classes = ()
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    schema = None  # not in the dashboard's or the mini app's schema

    agent: Agent

    def get_exception_handler(self):
        return device_errors

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.agent = request.auth
        if not conf.is_on(self.agent.company):
            raise VisionError(
                _("Ko‘z is switched off for this company."), code="module_off", status=403
            )

    def valid(self, serializer_class, data) -> dict:
        serializer = serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def json_field(self, request, name: str) -> dict:
        """A multipart field holding a JSON object (`meta`, `event`)."""
        raw = request.data.get(name)
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise VisionError(
                _("%(field)s must be JSON.") % {"field": name}, code="invalid"
            ) from exc
        if not isinstance(value, dict):
            raise VisionError(_("%(field)s must be JSON.") % {"field": name}, code="invalid")
        return value


class PairThrottle(BaseThrottle):
    """10 tries per address per 10 minutes, every try counted (a fixed window)."""

    def allow_request(self, request, view):
        window = int(timezone.now().timestamp() // PAIR_WINDOW)
        key = f"vision:pair:{self.get_ident(request)}:{window}"
        if cache.add(key, 1, PAIR_WINDOW + 1):
            return True
        try:
            return cache.incr(key) <= PAIR_TRIES
        except ValueError:
            cache.set(key, 1, PAIR_WINDOW + 1)
            return True

    def wait(self):
        return PAIR_WINDOW - int(timezone.now().timestamp()) % PAIR_WINDOW


class PairView(DeviceView):
    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (PairThrottle,)

    def initial(self, request, *args, **kwargs):
        APIView.initial(self, request, *args, **kwargs)

    def post(self, request):
        data = self.valid(PairSerializer, request.data)
        agent, token = services.pair(data["code"], host=data.get("host") or {})
        return Response(
            {
                "token": token,
                "agent": {
                    "id": agent.pk,
                    "name": agent.name,
                    "company": {"id": agent.company_id, "name": agent.company.name},
                    "branch": {"id": agent.branch_id, "name": agent.branch.name},
                },
                "server_time": queries.iso(timezone.now()),
            }
        )


class ConfigView(DeviceView):
    def get(self, request):
        return Response(queries.config(self.agent))


class CamerasView(DeviceView):
    def post(self, request):
        data = self.valid(InventorySerializer, request.data)
        return Response({"cameras": services.inventory(self.agent, data["cameras"])})


class SnapshotView(DeviceView):
    def post(self, request, key: str):
        services.store_snapshot(self.agent, key, request.FILES.get("image"))
        return Response(status=status.HTTP_204_NO_CONTENT)


class LiveView(DeviceView):
    def post(self, request):
        data = self.valid(LiveSerializer, request.data)
        return Response(services.receive_live(self.agent, data))


class FrameView(DeviceView):
    def post(self, request, key: str):
        meta = self.valid(FrameMetaSerializer, self.json_field(request, "meta"))
        at = meta["at"].astimezone(UTC)
        meta["at"] = at.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        services.receive_frame(self.agent, key, request.FILES.get("image"), meta)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StatsView(DeviceView):
    def post(self, request):
        rows = request.data.get("minutes") if hasattr(request.data, "get") else None
        if isinstance(rows, list) and len(rows) > MAX_STAT_ROWS:
            raise VisionError(
                _("Send at most %(count)d minutes a call.") % {"count": MAX_STAT_ROWS},
                code="too_large",
                status=413,
            )
        data = self.valid(StatsSerializer, request.data)
        return Response(services.store_stats(self.agent, data["minutes"]))


class EventsView(DeviceView):
    def post(self, request):
        raw = self.json_field(request, "event") if "event" in request.data else request.data
        event = self.valid(EventSerializer, raw)
        image = request.FILES.get("image") if event["phase"] == "start" else None
        return Response(services.receive_event(self.agent, event, image))


class JobsView(DeviceView):
    def get(self, request):
        return Response(services.take_jobs(self.agent))


class ClipView(DeviceView):
    def post(self, request, clip_id: int):
        if "failed" in request.data:
            data = self.valid(ClipFailureSerializer, request.data)
            services.fail_clip(self.agent, clip_id, failure=data["failed"], detail=data["detail"])
            return Response(status=status.HTTP_204_NO_CONTENT)
        meta = self.valid(ClipMetaSerializer, self.json_field(request, "meta"))
        services.store_clip(
            self.agent,
            clip_id,
            video=request.FILES.get("video"),
            poster=request.FILES.get("poster"),
            meta=meta,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
