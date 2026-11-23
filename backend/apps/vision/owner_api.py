"""Owner endpoints of Ko‘z, routed by `owner_urls.py` under `/api/v1/owner/companies/<id>/vision/…`
(docs/KOZ.md §6):

    overview/?branch=&day=             a day's visitors, receipts, conversion, hours, insights
    live/?branch=                      every camera's numbers now (polled every 5 s)
    cameras/ (+ {id}/)                 cameras; PATCH name, role, enabled, zones, register_id
    cameras/{id}/frame/                the live frame (vision.video); 204 until there is one
    cameras/{id}/snapshot/             GET the JPEG (video or manage); POST ask for a fresh one
    alerts/ (+ {id}/)                  alerts, newest first, {count, results}; {id}/clip/
    clips/ (+ {id}/)                   video receipts (vision.video): ask for one, poll it
    settings/                          the rules, who hears, how long things are kept
    agents/ (+ {id}/)                  Ko‘z boxes (vision.manage); {id}/pairing/ a new code
    review/?day=&branch=               voids and payouts with nobody at the counter (video)

Every endpoint needs the module on (404 otherwise) and `vision.view` or `vision.manage`, unless
a stronger permission is named. Members without `branches.all` see only their branches: anything
of another branch answers 404, like another company's.
"""

from __future__ import annotations

import base64
from datetime import date, datetime, time, timedelta
from urllib.parse import urlsplit

from django.conf import settings as django_settings
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.attendance import clock
from apps.companies.models import Branch
from apps.console.base import AnyOf, OwnerAPIView, OwnerViewSet
from apps.core.storage import SANDBOX_HEADERS
from apps.members import scope
from apps.members.permissions import Perm
from apps.vision import analytics, conf, demo_live, live, queries, review, services
from apps.vision.audit_actions import VisionAction
from apps.vision.errors import VisionError
from apps.vision.models import Agent, Alert, Camera, Clip
from apps.vision.serializers import (
    VisionAgentCreatedSerializer,
    VisionAgentSerializer,
    VisionAgentWriteSerializer,
    VisionAlertSerializer,
    VisionCameraSerializer,
    VisionCameraWriteSerializer,
    VisionClipRequestSerializer,
    VisionClipSerializer,
    VisionFrameSerializer,
    VisionLiveSerializer,
    VisionOverviewSerializer,
    VisionPairingSerializer,
    VisionReviewSerializer,
    VisionSettingsSerializer,
    VisionSettingsWriteSerializer,
    VisionSnapshotRequestedSerializer,
)
from apps.vision.zones import ZoneError

READ = AnyOf(Perm.VISION_VIEW, Perm.VISION_MANAGE)
VIDEO = Perm.VISION_VIDEO
MANAGE = Perm.VISION_MANAGE
SNAPSHOT = AnyOf(Perm.VISION_VIDEO, Perm.VISION_MANAGE)
BRANCH = OpenApiParameter("branch", int, description="One branch (in the caller's scope).")
DAY = OpenApiParameter("day", OpenApiTypes.DATE, description="YYYY-MM-DD; today by default.")


class VisionOn:
    """404 while the company's Ko‘z is off; Ko‘z's refusals as `{"detail", "code"}`."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not conf.is_on(self.company):
            raise NotFound

    def handle_exception(self, exc):
        if isinstance(exc, ZoneError):
            exc = ValidationError({"zones": [str(exc)]})
        elif isinstance(exc, VisionError):
            return Response({"detail": str(exc), "code": exc.code}, status=exc.status)
        return super().handle_exception(exc)


class Scope:
    def branch_filter(self) -> tuple[list[int] | None, Branch | None]:
        """The caller's branches narrowed to `?branch=` (another one answers 404), and that
        branch."""
        asked = self.request.query_params.get("branch")
        allowed = self.branch_scope
        if not asked:
            return allowed, None
        try:
            branch_id = int(asked)
        except ValueError as exc:
            raise ValidationError({"branch": [_("Give a number.")]}) from exc
        if allowed is not None and branch_id not in allowed:
            raise NotFound
        branch = Branch.objects.filter(company=self.company, pk=branch_id).first()
        if branch is None:
            raise NotFound
        return [branch_id], branch

    def day(self) -> date:
        asked = self.request.query_params.get("day")
        if not asked:
            return clock.today(self.company)
        found = parse_date(asked)
        if found is None:
            raise ValidationError({"day": [_("Give a date as YYYY-MM-DD.")]})
        return found

    def camera(self, pk) -> Camera:
        found = queries.camera_in(self.company, pk, branch_ids=self.branch_scope)
        if found is None:
            raise NotFound
        return found


class OverviewView(VisionOn, Scope, OwnerAPIView):
    perm = READ

    @extend_schema(parameters=[BRANCH, DAY], responses=VisionOverviewSerializer)
    def get(self, request, company_id):
        branch_ids, branch = self.branch_filter()
        return Response(
            analytics.overview(
                self.company,
                branch_ids=branch_ids,
                branch=branch,
                day=self.day(),
                member=self.membership,
            )
        )


class LiveView(VisionOn, Scope, OwnerAPIView):
    perm = READ

    @extend_schema(parameters=[BRANCH], responses=VisionLiveSerializer)
    def get(self, request, company_id):
        branch_ids, _branch = self.branch_filter()
        return Response(queries.live_page(self.company, branch_ids=branch_ids, user=request.user))


class CameraViewSet(VisionOn, Scope, OwnerViewSet):
    lookup_value_regex = r"\d+"
    pagination_class = None
    perm = READ
    perms_by_action = {"partial_update": MANAGE, "frame": VIDEO}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Camera.objects.none()
        return queries.cameras(self.company, branch_ids=self.branch_scope)

    def required_perm(self):
        if getattr(self, "action", None) == "snapshot":
            return MANAGE if self.request.method == "POST" else SNAPSHOT
        return super().required_perm()

    @extend_schema(parameters=[BRANCH], responses=VisionCameraSerializer(many=True))
    def list(self, request, company_id):
        branch_ids, _branch = self.branch_filter()
        rows = queries.cameras(self.company, branch_ids=branch_ids)
        return Response([queries.camera_row(camera, user=request.user) for camera in rows])

    @extend_schema(request=VisionCameraWriteSerializer, responses=VisionCameraSerializer)
    def partial_update(self, request, company_id, pk=None):
        camera = self.camera(pk)
        serializer = VisionCameraWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changed = services.update_camera(
            camera, by=self.membership, changes=serializer.validated_data
        )
        return Response(queries.camera_row(self.camera(changed.pk), user=request.user))

    @extend_schema(
        responses={
            200: VisionFrameSerializer,
            204: OpenApiResponse(description="No fresh frame yet."),
        }
    )
    @action(detail=True, methods=["get"])
    def frame(self, request, company_id, pk=None):
        camera = self.camera(pk)
        live.watch(camera.pk)
        if live.first_view(self.membership.pk, camera.pk):
            self.audit(VisionAction.LIVE_VIEWED, camera, camera=camera.name)
        found = demo_live.frame(camera) if camera.agent.demo else live.frame(camera.pk)
        if not found:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(
            {
                "at": found["at"],
                "w": found["w"],
                "h": found["h"],
                "people": found["people"],
                "image_b64": base64.b64encode(found["jpeg"]).decode(),
            }
        )

    @extend_schema(
        methods=["GET"],
        responses={
            (200, "image/jpeg"): OpenApiTypes.BINARY,
            404: OpenApiResponse(description="No snapshot yet."),
        },
    )
    @extend_schema(
        methods=["POST"], request=None, responses={202: VisionSnapshotRequestedSerializer}
    )
    @action(detail=True, methods=["get", "post"])
    def snapshot(self, request, company_id, pk=None):
        camera = self.camera(pk)
        if request.method == "POST":
            services.request_snapshot(camera, by=self.membership)
            return Response(
                {"snapshot_requested_at": queries.iso(camera.snapshot_requested_at)},
                status=status.HTTP_202_ACCEPTED,
            )
        if not camera.snapshot:
            raise NotFound
        try:
            with camera.snapshot.open("rb") as handle:
                data = handle.read()
        except (FileNotFoundError, OSError) as exc:
            raise NotFound from exc
        response = HttpResponse(data, content_type="image/jpeg")
        for header, value in SANDBOX_HEADERS.items():
            response[header] = value
        response["Cache-Control"] = "private, no-store"
        return response


def _when(value: str, *, end: bool, company) -> datetime:
    """A `from`/`to` filter: a date (the whole local day) or a moment."""
    day = parse_date(value)
    if day is not None:
        moment = clock.at(company, day, time(0, 0))
        return moment + timedelta(days=1) if end else moment
    moment = parse_datetime(value)
    if moment is None:
        raise ValidationError({"to" if end else "from": [_("Give a date as YYYY-MM-DD.")]})
    return moment if timezone.is_aware(moment) else timezone.make_aware(moment, clock.zone(company))


class AlertViewSet(VisionOn, Scope, mixins.ListModelMixin, OwnerViewSet):
    lookup_value_regex = r"\d+"
    perm = READ
    perms_by_action = {"clip": VIDEO}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Alert.objects.none()
        return queries.alerts(self.company, branch_ids=self.branch_scope)

    def alert(self, pk) -> Alert:
        found = self.get_queryset().filter(pk=pk).first()
        if found is None:
            raise NotFound
        return found

    @extend_schema(
        parameters=[
            BRANCH,
            OpenApiParameter("state", str, enum=Alert.State.values),
            OpenApiParameter("kind", str, enum=Alert.Kind.values),
            OpenApiParameter("from", OpenApiTypes.DATE),
            OpenApiParameter("to", OpenApiTypes.DATE),
        ],
        responses=VisionAlertSerializer(many=True),
    )
    def list(self, request, company_id):
        branch_ids, _branch = self.branch_filter()
        rows = queries.alerts(self.company, branch_ids=branch_ids)
        params = request.query_params
        if params.get("state") in Alert.State.values:
            rows = rows.filter(state=params["state"])
        if params.get("kind") in Alert.Kind.values:
            rows = rows.filter(kind=params["kind"])
        if params.get("from"):
            rows = rows.filter(
                started_at__gte=_when(params["from"], end=False, company=self.company)
            )
        if params.get("to"):
            rows = rows.filter(started_at__lt=_when(params["to"], end=True, company=self.company))
        page = self.paginate_queryset(rows)
        return self.get_paginated_response(
            [queries.alert_row(alert, user=request.user) for alert in page]
        )

    @extend_schema(responses=VisionAlertSerializer)
    def retrieve(self, request, company_id, pk=None):
        return Response(queries.alert_row(self.alert(pk), user=request.user))

    @extend_schema(request=None, responses={201: VisionClipSerializer})
    @action(detail=True, methods=["post"])
    def clip(self, request, company_id, pk=None):
        clip = services.request_alert_clip(self.alert(pk), by=self.membership)
        return Response(queries.clip_row(clip, user=request.user), status=status.HTTP_201_CREATED)


class ClipViewSet(VisionOn, OwnerViewSet):
    lookup_value_regex = r"\d+"
    pagination_class = None
    perm = VIDEO

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Clip.objects.none()
        rows = Clip.objects.filter(company=self.company).select_related("camera")
        return scope.restrict(rows, self.branch_scope, field="camera__branch")

    @extend_schema(request=VisionClipRequestSerializer, responses={201: VisionClipSerializer})
    def create(self, request, company_id):
        serializer = VisionClipRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("sale_id") is not None:
            from apps.sales.models import Sale

            sale = scope.restrict(
                Sale.objects.filter(company=self.company, pk=data["sale_id"]), self.branch_scope
            ).first()
            if sale is None:
                raise NotFound
            clip = services.request_sale_clip(sale, by=self.membership)
        else:
            camera = queries.camera_in(
                self.company, data["camera_id"], branch_ids=self.branch_scope
            )
            if camera is None:
                raise NotFound
            clip = services.request_clip(
                camera,
                by=self.membership,
                start=data["at"] - timedelta(seconds=data["before_s"]),
                end=data["at"] + timedelta(seconds=data["after_s"]),
                reason=Clip.Reason.MANUAL,
            )
        return Response(queries.clip_row(clip, user=request.user), status=status.HTTP_201_CREATED)

    @extend_schema(responses=VisionClipSerializer)
    def retrieve(self, request, company_id, pk=None):
        clip = self.get_queryset().filter(pk=pk).first()
        if clip is None:
            raise NotFound
        return Response(queries.clip_row(clip, user=request.user))


class SettingsView(VisionOn, OwnerAPIView):
    perm = READ
    perms_by_action = {"patch": MANAGE}

    @extend_schema(responses=VisionSettingsSerializer)
    def get(self, request, company_id):
        return Response(VisionSettingsSerializer(conf.get_settings(self.company)).data)

    @extend_schema(request=VisionSettingsWriteSerializer, responses=VisionSettingsSerializer)
    def patch(self, request, company_id):
        current = conf.get_settings(self.company)
        serializer = VisionSettingsWriteSerializer(current, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changed = services.update_settings(
            self.company, by=self.membership, changes=serializer.validated_data
        )
        return Response(VisionSettingsSerializer(changed).data)


def pair_command(request, code: str) -> str:
    """The line to run on the box's PC: `koz-agent pair https://<host> KOZ-…` (§6.8)."""
    base = django_settings.DASHBOARD_URL
    if base:
        parts = urlsplit(base)
        origin = f"{parts.scheme}://{parts.netloc}"
    else:
        origin = request.build_absolute_uri("/").rstrip("/")
    return f"koz-agent pair {origin} {code}"


class AgentViewSet(VisionOn, OwnerViewSet):
    lookup_value_regex = r"\d+"
    pagination_class = None
    perm = MANAGE

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Agent.objects.none()
        return queries.agents(self.company, branch_ids=self.branch_scope)

    def agent(self, pk) -> Agent:
        found = self.get_queryset().filter(pk=pk).first()
        if found is None:
            raise NotFound
        return found

    def pairing_json(self, code) -> dict:
        return {
            "code": code.code,
            "expires_at": queries.iso(code.expires_at),
            "command": pair_command(self.request, code.code),
        }

    @extend_schema(responses=VisionAgentSerializer(many=True))
    def list(self, request, company_id):
        return Response([queries.agent_row(agent) for agent in self.get_queryset()])

    @extend_schema(
        request=VisionAgentWriteSerializer, responses={201: VisionAgentCreatedSerializer}
    )
    def create(self, request, company_id):
        serializer = VisionAgentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        allowed = self.branch_scope
        branch = Branch.objects.filter(company=self.company, pk=data["branch_id"]).first()
        if branch is None or (allowed is not None and branch.pk not in allowed):
            raise ValidationError({"branch_id": [_("Pick one of your branches.")]})
        agent, code = services.create_agent(
            self.company, by=self.membership, name=data["name"], branch=branch
        )
        return Response(
            {"agent": queries.agent_row(agent, cameras=0), "pairing": self.pairing_json(code)},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(responses={204: None})
    def destroy(self, request, company_id, pk=None):
        services.remove_agent(self.agent(pk), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=VisionPairingSerializer)
    @action(detail=True, methods=["post"], url_path="pairing")
    def pairing_code(self, request, company_id, pk=None):
        code = services.new_pairing(self.agent(pk), by=self.membership)
        return Response(self.pairing_json(code))


class ReviewView(VisionOn, Scope, OwnerAPIView):
    perm = VIDEO

    @extend_schema(parameters=[BRANCH, DAY], responses=VisionReviewSerializer)
    def get(self, request, company_id):
        branch_ids, _branch = self.branch_filter()
        return Response(review.items(self.company, branch_ids=branch_ids, day=self.day()))
