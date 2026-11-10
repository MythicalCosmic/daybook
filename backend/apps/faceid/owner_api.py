"""Owner endpoints of Face ID (`faceid/…`, rule 21): the live feed, everyone the terminals know,
the terminals with their setup (and the catch-up helper, filled in), the links and the settings.

Company- and branch-scoped (a terminal belongs to a branch; an id outside the caller's branches
answers 404, like another company's), `attendance.view` for the feed, the people and the
terminals' status, `attendance.manage` for terminals, links and settings. Writes go through
`services` (audited, pulse after commit). Everything answers 404 while the `face_id` module is
off.
"""

import json
from collections import defaultdict
from datetime import datetime, time, timedelta
from difflib import SequenceMatcher

from django.db.models import Count, Max, Min
from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response

from apps.attendance import clock
from apps.attendance import queries as attendance_queries
from apps.companies.models import Branch
from apps.console.base import OwnerAPIView, OwnerViewSet
from apps.core.files import signed_url
from apps.faceid import bot, conf, hikvision, services
from apps.faceid import serializers as s
from apps.faceid.models import FaceDevice, FaceEvent, FaceIdSettings, FaceLink
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

VIEW, MANAGE = Perm.ATTENDANCE_VIEW, Perm.ATTENDANCE_MANAGE
# A terminal heard from within this long is online; longer, it's quiet.
ONLINE_WITHIN = timedelta(hours=24)
# A terminal that sends heartbeats (every 1 to 30 minutes) is quiet sooner.
HEARTBEAT_GRACE = timedelta(minutes=35)
PHOTO_TTL = 600
# How far back the People list looks.
PEOPLE_DAYS = 90
BRANCH_PARAM = OpenApiParameter("branch", int, many=True, description="Branch ids.")


def device_status(device: FaceDevice, now: datetime) -> str:
    """online · quiet · never (no request yet) · disabled. Quiet: nothing for a day, or, from a
    terminal that sends heartbeats, nothing for 35 minutes."""
    if not device.enabled:
        return "disabled"
    if device.last_seen_at is None:
        return "never"
    beats = device.last_heartbeat_at is not None and now - device.last_heartbeat_at <= ONLINE_WITHIN
    window = HEARTBEAT_GRACE if beats else ONLINE_WITHIN
    return "online" if now - device.last_seen_at <= window else "quiet"


def _iso(company, moment):
    return clock.local(company, moment).isoformat() if moment else None


def _branch(branch) -> dict:
    return {"id": branch.pk, "name": branch.name, "code": branch.code}


def _ints(values, name: str) -> list[int]:
    try:
        return [int(value) for value in values if str(value).strip()]
    except ValueError as exc:
        raise ValidationError({name: [_("Give a number.")]}) from exc


def _id(value, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: [_("Give a number.")]}) from exc


def _day(value: str, name: str):
    from datetime import date

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({name: [_("Give a day as YYYY-MM-DD.")]}) from exc


class FaceIdOn:
    """404 while Face ID is switched off for the company."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not conf.is_on(self.company):
            raise NotFound


class Scoped:
    def one_branch(self, value) -> Branch:
        branch_id = _id(value, "branch_id")
        branch = Branch.objects.filter(company=self.company, pk=branch_id).first()
        if branch is None or not scope.allows(self.branch_scope, branch.pk):
            raise NotFound
        return branch

    def people(self):
        people = Membership.objects.for_company(self.company).filter(
            status__in=(Membership.Status.APPROVED, Membership.Status.SUSPENDED)
        )
        return scope.restrict(people, self.branch_scope, field="branches")

    def staff_member(self, member_id) -> Membership:
        member = (
            self.people()
            .filter(pk=member_id)
            .select_related("user", "position", "home_branch", "company")
            .first()
        )
        if member is None:
            raise NotFound
        return member

    def devices(self):
        return scope.restrict(FaceDevice.objects.for_company(self.company), self.branch_scope)

    def events(self):
        return scope.restrict(
            FaceEvent.objects.for_company(self.company), self.branch_scope, field="device__branch"
        )


def photo_url(event: FaceEvent | None, request, company) -> str | None:
    if event is None or not event.photo:
        return None
    return signed_url(
        event.photo,
        user=request.user,
        company_id=company.pk,
        check=f"faceid.photo:{event.pk}",
        ttl=PHOTO_TTL,
    )


def person(member: Membership | None) -> dict | None:
    return attendance_queries.person_card(member) if member is not None else None


# Terminals --------------------------------------------------------------------------------


def _today_scans(company, device_ids: list[int], now: datetime) -> dict[int, list[FaceEvent]]:
    start = clock.at(company, clock.today(company, now), time(0, 0))
    found = defaultdict(list)
    rows = (
        FaceEvent.objects.filter(company=company, device_id__in=device_ids, event_at__gte=start)
        .exclude(flags__contains=[FaceEvent.Flag.SIMULATED])
        .exclude(kind=FaceEvent.Kind.OTHER)
        .select_related("membership")
        .order_by("event_at")
    )
    for event in rows:
        found[event.device_id].append(event)
    return found


def _who(event: FaceEvent) -> str:
    if event.membership_id:
        return event.membership.full_name or str(event.membership)
    return event.name_on_device or event.employee_no


def history_payload(device: FaceDevice, now: datetime) -> dict:
    """The stored history a terminal uploads when first pointed at us: skipped, only counted.
    `active` while it is still coming (live scans follow it); `clock_hides`: the terminal's
    clock is so far behind that its live scans look old too."""
    return {
        "skipped": device.history_skipped,
        "until": _iso(device.company, device.history_until),
        "active": services.history_active(device, now),
        "clock_hides": services.clock_hides_scans(device, now),
    }


def device_payload(device: FaceDevice, today: list[FaceEvent], now: datetime) -> dict:
    company = device.company
    hourly = [0] * 24
    for event in today:
        hourly[clock.local(company, event.event_at).hour] += 1
    last = today[-1] if today else None
    offset = device.clock_offset_s
    return {
        "id": device.pk,
        "name": device.name,
        "branch": _branch(device.branch),
        "direction": device.direction,
        "enabled": device.enabled,
        "vendor": device.vendor,
        "model": device.model,
        "ip": device.ip,
        "mac": device.mac,
        "status": device_status(device, now),
        "last_seen_at": _iso(company, device.last_seen_at),
        "last_event_at": _iso(company, device.last_event_at),
        "heartbeats": device.last_heartbeat_at is not None,
        "clock_offset_s": offset,
        "clock_off": offset is not None and abs(offset) > services.CLOCK_TOLERANCE.total_seconds(),
        "scans_today": len(today),
        "hourly": hourly,
        "last_scan": {"at": _iso(company, last.event_at), "name": _who(last), "action": last.action}
        if last
        else None,
        "history": history_payload(device, now),
        "created_at": _iso(company, device.created_at),
    }


def setup_payload(device: FaceDevice) -> dict:
    last_test = (
        FaceEvent.objects.filter(device=device, flags__contains=[FaceEvent.Flag.SIMULATED])
        .order_by("-received_at")
        .values_list("received_at", flat=True)
        .first()
    )
    return services.setup(device) | {
        "ip": device.ip,
        "last_event_at": _iso(device.company, device.last_event_at),
        "last_seen_at": _iso(device.company, device.last_seen_at),
        "last_test_at": _iso(device.company, last_test),
        "history": history_payload(device, timezone.now()),
    }


class ScriptRenderer(BaseRenderer):
    """Lets a request for the catch-up helper (`Accept: text/x-python`) through DRF's content
    negotiation; the view answers the file itself."""

    media_type = "text/x-python"
    format = "py"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, bytes | str):
            return data
        return json.dumps(data, default=str).encode()


class DeviceViewSet(FaceIdOn, Scoped, mixins.ListModelMixin, OwnerViewSet):
    """The company's terminals (in the caller's branches): add, change, switch off, a new
    code, what to type into the terminal, and a test scan."""

    perm = MANAGE
    pagination_class = None
    lookup_value_regex = r"\d+"
    http_method_names = ["get", "post", "patch", "head", "options"]
    serializer_class = s.DeviceOutSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return FaceDevice.objects.none()
        return self.devices().select_related("branch", "company").order_by("-enabled", "name")

    def _payloads(self, devices) -> list[dict]:
        now = timezone.now()
        scans = _today_scans(self.company, [device.pk for device in devices], now)
        return [device_payload(device, scans.get(device.pk, []), now) for device in devices]

    @extend_schema(responses=s.DeviceOutSerializer(many=True))
    def list(self, request, *args, **kwargs):
        return Response(self._payloads(list(self.get_queryset())))

    @extend_schema(request=s.DeviceInSerializer, responses={201: s.DeviceOutSerializer})
    def create(self, request, company_id):
        serializer = s.DeviceInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        device = services.create_device(
            self.company,
            by=self.membership,
            name=data["name"],
            branch=self.one_branch(data["branch_id"]),
            direction=data["direction"],
        )
        device = self.get_queryset().get(pk=device.pk)
        return Response(self._payloads([device])[0], status=status.HTTP_201_CREATED)

    @extend_schema(request=s.DevicePatchSerializer, responses=s.DeviceOutSerializer)
    def partial_update(self, request, company_id, pk):
        device = self.get_object()
        serializer = s.DevicePatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)
        if "branch_id" in changes:
            changes["branch"] = self.one_branch(changes.pop("branch_id"))
        services.update_device(device, by=self.membership, **changes)
        return Response(self._payloads([self.get_queryset().get(pk=device.pk)])[0])

    @extend_schema(request=None, responses=s.SetupSerializer)
    @action(detail=True, methods=["get"])
    def setup(self, request, company_id, pk):
        return Response(setup_payload(self.get_object()))

    @extend_schema(request=None, responses=s.SetupSerializer)
    @action(detail=True, methods=["post"])
    def regenerate(self, request, company_id, pk):
        return Response(setup_payload(services.new_code(self.get_object(), by=self.membership)))

    @extend_schema(request=None, responses={(200, ScriptRenderer.media_type): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"], renderer_classes=[JSONRenderer, ScriptRenderer])
    def catchup(self, request, company_id, pk):
        """`catchup.py`, the helper that sends the terminal's newest scans while it still uploads
        its old history, with the terminal's address on the server filled in (it holds the
        terminal's code, like the setup values)."""
        script = services.catchup_script(self.get_object())
        response = HttpResponse(script.encode("utf-8"), content_type="text/x-python; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="catchup.py"'
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @extend_schema(request=None, responses={201: s.EventOutSerializer})
    @action(detail=True, methods=["post"])
    def simulate(self, request, company_id, pk):
        event = services.simulate(self.get_object(), by=self.membership)
        event = FaceEvent.objects.select_related(*EVENT_RELATIONS).get(pk=event.pk)
        rows = event_rows([event], request, self.company)
        return Response(rows[0], status=status.HTTP_201_CREATED)


class StatusView(FaceIdOn, Scoped, OwnerAPIView):
    """How the terminals are doing (the Terminals card), for anyone who sees attendance."""

    perm = VIEW

    @extend_schema(responses=s.StatusSerializer)
    def get(self, request, company_id):
        now = timezone.now()
        devices = list(self.devices().filter(enabled=True).select_related("branch", "company"))
        scans = _today_scans(self.company, [device.pk for device in devices], now)
        rows = [
            {
                "id": device.pk,
                "name": device.name,
                "branch": _branch(device.branch),
                "status": device_status(device, now),
                "last_event_at": _iso(self.company, device.last_event_at),
                "scans_today": len(scans.get(device.pk, [])),
            }
            for device in devices
        ]
        counts = defaultdict(int)
        for row in rows:
            counts[row["status"]] += 1
        unlinked = None
        if self.membership.has_perm(MANAGE):
            from apps.faceid.providers import unlinked_count

            unlinked = unlinked_count(self.membership)
        return Response(
            {
                "total": len(rows),
                "online": counts["online"],
                "quiet": counts["quiet"],
                "never": counts["never"],
                "unlinked": unlinked,
                "devices": rows,
            }
        )


# The feed ---------------------------------------------------------------------------------

EVENT_RELATIONS = (
    "device__branch",
    "membership__user",
    "membership__position",
    "membership__home_branch",
)


def event_rows(events: list[FaceEvent], request, company) -> list[dict]:
    from apps.attendance.models import AttendanceRecord

    records = {
        record.pk: record
        for record in AttendanceRecord.objects.filter(
            pk__in=[event.record_id for event in events if event.record_id]
        )
    }
    rows = []
    for event in events:
        record = records.get(event.record_id)
        rows.append(
            {
                "id": event.pk,
                "event_at": _iso(company, event.event_at),
                "received_at": _iso(company, event.received_at),
                "device": {"id": event.device_id, "name": event.device.name},
                "branch": _branch(event.device.branch),
                "kind": event.kind,
                "action": event.action,
                "method": event.method,
                "verify_mode": event.verify_mode,
                "employee_no": event.employee_no,
                "name_on_device": event.name_on_device,
                "member": person(event.membership) if event.membership_id else None,
                "record": {
                    "id": record.pk,
                    "status": record.status,
                    "check_in_at": _iso(company, record.check_in_at),
                    "check_out_at": _iso(company, record.check_out_at),
                    "is_late": record.is_late,
                    "late_minutes": record.late_minutes,
                    "worked_minutes": record.worked_minutes,
                }
                if record is not None
                else None,
                "flags": list(event.flags),
                "photo_url": photo_url(event, request, company),
            }
        )
    return rows


class EventViewSet(FaceIdOn, Scoped, mixins.ListModelMixin, OwnerViewSet):
    """Every scan the terminals sent, newest first, each with its snapshot (a short link)."""

    perm = VIEW
    serializer_class = s.EventOutSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return FaceEvent.objects.none()
        params = self.request.query_params
        events = self.events().select_related(*EVENT_RELATIONS)
        if params.get("device"):
            events = events.filter(device_id=_id(params["device"], "device"))
        actions = [value for value in params.getlist("action") if value]
        if actions:
            events = events.filter(action__in=actions)
        if params.get("kind"):
            events = events.filter(kind=params["kind"])
        else:
            events = events.exclude(kind=FaceEvent.Kind.OTHER)
        if params.get("member"):
            events = events.filter(membership_id=_id(params["member"], "member"))
        if params.get("number"):
            events = events.filter(number_key=hikvision.number_key(params["number"]))
        branches = _ints(params.getlist("branch"), "branch")
        if branches:
            events = events.filter(device__branch_id__in=branches)
        if params.get("date"):
            start = clock.at(self.company, _day(params["date"], "date"), time(0, 0))
            events = events.filter(event_at__gte=start, event_at__lt=start + timedelta(days=1))
        if params.get("tests") != "1":
            events = events.exclude(flags__contains=[FaceEvent.Flag.SIMULATED])
        return events.order_by("-event_at", "-pk")

    @extend_schema(
        parameters=[
            OpenApiParameter("device", int),
            OpenApiParameter("action", str, many=True, enum=list(FaceEvent.Action.values)),
            OpenApiParameter("kind", str, enum=list(FaceEvent.Kind.values)),
            OpenApiParameter("member", int),
            OpenApiParameter("number", str, description="An Employee No."),
            OpenApiParameter("date", str, description="YYYY-MM-DD"),
            OpenApiParameter("tests", str, enum=["1"], description="1: test scans too."),
            BRANCH_PARAM,
        ],
        responses=s.EventOutSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(event_rows(list(page), request, self.company))


# People: everyone the terminals know ------------------------------------------------------


def _similarity(a: str, b: str) -> int:
    a, b = services.name_key(a), services.name_key(b)
    if not a or not b:
        return 0
    return round(SequenceMatcher(None, a, b).ratio() * 100)


def suggestions(name: str, people, linked: set[int], limit: int = 3) -> list[dict]:
    """The people whose names come closest to the terminal's, in either script ("Гулирано" is
    "Gulirano"): terminals often hold first names only, so an exact first name ranks first,
    then an exact full name, then the closest spelling."""
    key = services.name_key(name)
    if not key:
        return []
    scored = []
    for member in people:
        first, last = member.first_name, member.last_name
        full = member.full_name or str(member.user)
        if key == services.name_key(first):
            rank, score = 0, 100
        elif key in (services.name_key(full), services.name_key(f"{last} {first}")):
            rank, score = 1, 100
        else:
            rank = 2
            score = max(
                _similarity(name, first),
                _similarity(name, full),
                _similarity(name, f"{last} {first}"),
            )
        if score >= 60:
            scored.append((rank, -score, full, member, score))
    scored.sort(key=lambda row: row[:3])
    return [
        {"member": person(member), "score": score, "has_number": member.pk in linked}
        for *_order, member, score in scored[:limit]
    ]


class PeopleView(FaceIdOn, Scoped, OwnerAPIView):
    """Everyone the terminals of the caller's branches know (by number, the last 90 days): the
    number and name as the terminal shows them, the latest snapshot, the Daybook person or "not
    in Daybook" with the people whose names come closest (for `attendance.manage`)."""

    perm = VIEW

    @extend_schema(
        parameters=[OpenApiParameter("linked", str, enum=["0", "1"])],
        responses=s.PersonRowSerializer(many=True),
    )
    def get(self, request, company_id):
        since = timezone.now() - timedelta(days=PEOPLE_DAYS)
        rows = self.events().filter(
            kind=FaceEvent.Kind.PERSON, received_at__gte=since, number_key__gt=""
        )
        rows = rows.exclude(flags__contains=[FaceEvent.Flag.SIMULATED])
        numbers = list(
            rows.values("number_key")
            .annotate(first_at=Min("event_at"), last_at=Max("event_at"), scans=Count("id"))
            .order_by("-last_at")[:300]
        )
        links = {
            link.number_key: link
            for link in FaceLink.objects.filter(
                company=self.company, number_key__in=[row["number_key"] for row in numbers]
            ).select_related("membership__user", "membership__position", "membership__home_branch")
        }
        wanted = request.query_params.get("linked")
        manage = self.membership.has_perm(MANAGE)
        people = (
            list(
                self.people()
                .filter(status=Membership.Status.APPROVED)
                .select_related("user", "position", "home_branch")
            )
            if manage
            else []
        )
        linked = set(
            FaceLink.objects.filter(company=self.company, membership__isnull=False).values_list(
                "membership_id", flat=True
            )
        )
        found = []
        for number in numbers:
            link = links.get(number["number_key"])
            is_linked = link is not None and link.membership_id is not None
            if (wanted == "1" and not is_linked) or (wanted == "0" and is_linked):
                continue
            latest = (
                rows.filter(number_key=number["number_key"])
                .select_related("device")
                .order_by("-event_at")
                .first()
            )
            with_photo = (
                rows.filter(number_key=number["number_key"])
                .exclude(photo="")
                .order_by("-event_at")
                .first()
            )
            found.append(
                {
                    "employee_no": latest.employee_no,
                    "name_on_device": latest.name_on_device,
                    "first_at": _iso(self.company, number["first_at"]),
                    "last_at": _iso(self.company, number["last_at"]),
                    "scans": number["scans"],
                    "device": {"id": latest.device_id, "name": latest.device.name},
                    "photo_url": photo_url(with_photo, request, self.company),
                    "member": person(link.membership) if is_linked else None,
                    "link": {"id": link.pk, "auto": link.auto, "ignored": link.ignored}
                    if link is not None
                    else None,
                    "suggestions": suggestions(latest.name_on_device, people, linked)
                    if manage and link is None
                    else [],
                }
            )
        return Response(found)


class IgnoreView(FaceIdOn, Scoped, OwnerAPIView):
    """Set a number aside: its scans are logged only and nobody is asked about it again."""

    perm = MANAGE

    @extend_schema(request=s.NumberSerializer, responses={201: s.LinkOutSerializer})
    def post(self, request, company_id):
        serializer = s.NumberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        number = serializer.validated_data["employee_no"].strip()
        key = hikvision.number_key(number)
        if not key or not self.events().filter(number_key=key).exists():
            raise NotFound
        link = services.ignore_number(self.company, by=self.membership, employee_no=number)
        return Response(link_row(link), status=status.HTTP_201_CREATED)


# Links ------------------------------------------------------------------------------------


def link_row(link: FaceLink) -> dict:
    return {
        "id": link.pk,
        "employee_no": link.employee_no,
        "member": person(link.membership) if link.membership_id else None,
        "auto": link.auto,
        "ignored": link.ignored,
        "created_at": _iso(link.company, link.created_at),
    }


class LinkViewSet(FaceIdOn, Scoped, mixins.ListModelMixin, mixins.DestroyModelMixin, OwnerViewSet):
    """Which Employee No is whom (a person may have several), and numbers set aside."""

    perm = MANAGE
    pagination_class = None
    lookup_value_regex = r"\d+"
    serializer_class = s.LinkOutSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return FaceLink.objects.none()
        links = FaceLink.objects.for_company(self.company).select_related(
            "company", "membership__user", "membership__position", "membership__home_branch"
        )
        if self.branch_scope is not None:
            links = links.filter(membership__in=self.people())
        return links.order_by("number_key")

    @extend_schema(
        parameters=[
            OpenApiParameter("member", int),
            OpenApiParameter("ignored", str, enum=["1"], description="1: the numbers set aside."),
        ],
        responses=s.LinkOutSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        links = self.get_queryset()
        if request.query_params.get("member"):
            links = links.filter(membership_id=_id(request.query_params["member"], "member"))
        links = links.filter(ignored=request.query_params.get("ignored") == "1")
        return Response([link_row(link) for link in links])

    @extend_schema(request=s.LinkInSerializer, responses={201: s.LinkOutSerializer})
    def create(self, request, company_id):
        serializer = s.LinkInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        link = services.link_number(
            self.company,
            by=self.membership,
            employee_no=data["employee_no"],
            membership=self.staff_member(data["member_id"]),
        )
        return Response(link_row(self.get_queryset().get(pk=link.pk)), status=201)

    def perform_destroy(self, instance):
        services.unlink(instance, by=self.membership)


# Settings ---------------------------------------------------------------------------------


class SettingsView(FaceIdOn, OwnerAPIView):
    """Face ID's settings: attendance and how people use the terminal (`scan_mode`), Telegram,
    groups, alerts, repeats, snapshots."""

    perm = MANAGE

    @extend_schema(responses=s.SettingsSerializer)
    def get(self, request, company_id):
        return Response(s.SettingsSerializer(conf.get_settings(self.company)).data)

    @extend_schema(request=s.SettingsSerializer, responses=s.SettingsSerializer)
    def patch(self, request, company_id):
        row: FaceIdSettings = conf.get_settings(self.company)
        serializer = s.SettingsSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        row = services.update_settings(
            self.company, by=self.membership, **serializer.validated_data
        )
        return Response(s.SettingsSerializer(row).data)


# The Face ID bot ------------------------------------------------------------------------------


def bot_payload(company) -> dict:
    row = conf.get_settings(company)
    people = bot.recipients(company) if row.bot_username else []
    return {
        "configured": bool(row.bot_token and row.bot_username),
        "bot_username": row.bot_username or None,
        "bot_name": row.bot_name or None,
        "status": row.bot_status,
        "checked_at": row.bot_checked_at,
        "start_url": bot.start_url(row) or None,
        "started": sum(person.state == "started" for person in people),
        "pending": [
            {
                "id": person.member.pk,
                "name": person.member.full_name,
                "role": person.role,
                "state": person.state,
            }
            for person in people
            if person.state != "started"
        ],
    }


class BotView(FaceIdOn, OwnerAPIView):
    """The company's Face ID bot: PUT a BotFather token (checked with Telegram's getMe, kept
    encrypted, never shown again), DELETE to remove it. Everything Face ID sends to Telegram
    goes through it while it is connected."""

    perm = MANAGE

    @extend_schema(responses=s.BotSerializer)
    def get(self, request, company_id):
        return Response(bot_payload(self.company))

    @extend_schema(request=s.BotTokenSerializer, responses=s.BotSerializer)
    def put(self, request, company_id):
        serializer = s.BotTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            bot.connect(self.company, by=self.membership, token=serializer.validated_data["token"])
        except bot.TokenError as exc:
            raise ValidationError({"token": [str(exc)]}) from exc
        return Response(bot_payload(self.company))

    @extend_schema(request=None, responses={204: None})
    def delete(self, request, company_id):
        bot.disconnect(self.company, by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BotTestView(FaceIdOn, OwnerAPIView):
    """A test message from the Face ID bot to you."""

    perm = MANAGE

    @extend_schema(request=None, responses=s.BotSentSerializer)
    def post(self, request, company_id):
        bot.send_test(self.company, request.user)
        return Response({"sent": True})
