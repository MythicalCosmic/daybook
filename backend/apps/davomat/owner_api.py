"""Davomat's owner endpoints (docs/DAVOMAT.md §1). JSON; times are UTC, dates company-local.

Outside a company (`root_urlpatterns`, mounted at `/api/v1/owner/`):

    GET  edition/                   public: which product this is, the organization, setup
    POST edition/setup/             public, Davomat only, once: the organization and its owner
    POST auth/password/             public, both editions: username + password -> a session
    POST auth/password/change/      signed in: {current, new}

Under `/api/v1/owner/companies/<id>/`, Davomat only (404 in Daybook):

    GET/PATCH  davomat/settings/                    GET: anyone; PATCH: company.settings
    users/                    roles.manage: list, create, retrieve, PATCH, DELETE (switch off),
                              {id}/password/, {id}/deactivate/, {id}/activate/, roles/,
                              {id}/telegram-link/ (POST/DELETE; yourself without roles.manage)
    employees/                members.view to read, members.manage to change: list, create,
                              retrieve, PATCH, {id}/photo/ (POST/DELETE), {id}/leave/,
                              {id}/return/, {id}/face-numbers/ (POST), {id}/face-numbers/<no>/
                              (DELETE), {id}/telegram-link/ (POST/DELETE), import/, export/
    GET/PUT/DELETE telegram/  ·  POST telegram/test/          company.settings
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramUnauthorizedError,
)
from django.conf import settings
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.attendance import clock
from apps.attendance.models import WorkSchedule
from apps.companies.models import Branch, Company
from apps.console.base import OwnerAPIView, OwnerViewSet
from apps.core.api import Pagination
from apps.core.throttles import AddressRateThrottle
from apps.core.uploads import sanitize_image
from apps.davomat import conf, importing, passwords, queries, services
from apps.davomat import serializers as shapes
from apps.davomat.models import DavomatSettings
from apps.faceid import hikvision
from apps.hr.queries import employment_dates
from apps.members import scope
from apps.members.models import AccessRole, Department, Membership, Position
from apps.members.permissions import Perm
from apps.notifications import telegram as bots
from apps.signin import services as signin
from apps.signin.auth import FromDashboard, OwnerJWTAuthentication
from apps.signin.tokens import SESSION_CLAIM

PHOTO_SIDE = 640
LANGUAGES = list(shapes.LANGUAGES)
YES, NO = ("1", "true", "yes", "on", "linked"), ("0", "false", "no", "off", "not_linked")


class DavomatPagination(Pagination):
    page_size = 100
    max_page_size = 500


class DavomatOnly:
    """Davomat's company endpoints don't exist in Daybook: 404 before anything else answers."""

    def initial(self, request, *args, **kwargs):
        if not conf.is_on():
            raise Http404
        super().initial(request, *args, **kwargs)


def _validation(exc: passwords.FieldError) -> ValidationError:
    detail: dict | list = list(exc.messages)
    for part in reversed(exc.field.split(".")):
        detail = {part: detail}
    return ValidationError(detail)


@contextmanager
def field_errors():
    """A service's `FieldError` as a 400 naming the field (`{"admin": {"password": [...]}}`)."""
    try:
        yield
    except passwords.FieldError as exc:
        raise _validation(exc) from exc


def _flag(value: str | None) -> bool | None:
    text = (value or "").strip().lower()
    if text in YES:
        return True
    if text in NO:
        return False
    return None


def _number(params, name: str) -> int | None:
    value = params.get(name)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: [_("Give a number.")]}) from exc


def _row_of(model, company: Company, pk, field: str):
    """The company's row `pk` of `model` (None for None), or a 400 naming `field`."""
    if pk is None:
        return None
    found = model.objects.filter(company=company, pk=pk).first()
    if found is None:
        raise ValidationError({field: [_("Pick one of the options offered.")]})
    return found


def _branches_of(company: Company, ids, field: str = "branch_ids") -> list[Branch] | None:
    if ids is None:
        return None
    ids = list(dict.fromkeys(ids))
    found = list(Branch.objects.filter(company=company, pk__in=ids))
    if len(found) != len(ids):
        raise ValidationError({field: [_("Pick branches of this organization.")]})
    order = {pk: index for index, pk in enumerate(ids)}
    return sorted(found, key=lambda branch: order[branch.pk])


# Edition and first run ------------------------------------------------------------------------


def edition_payload() -> dict:
    """What the sign-in page needs before anyone signs in."""
    if not conf.is_on():
        bot = settings.OWNER_BOT_USERNAME or settings.EMPLOYEE_BOT_USERNAME
        return {
            "edition": conf.DAYBOOK,
            "product": "Daybook",
            "organization": None,
            "needs_setup": False,
            "default_language": "uz",
            "languages": LANGUAGES,
            "telegram": {
                "configured": bool(settings.OWNER_BOT_TOKEN or settings.EMPLOYEE_BOT_TOKEN),
                "bot_username": bot or None,
            },
        }
    company = conf.organization()
    row = DavomatSettings.objects.filter(company=company).first() if company else None
    connected = bool(row and row.bot_token and row.bot_username)
    return {
        "edition": conf.DAVOMAT,
        "product": conf.product_name(company),
        "organization": {
            "name": company.name,
            "logo_url": company.logo.url if company.logo else None,
        }
        if company
        else None,
        "needs_setup": services.needs_setup(),
        "default_language": company.default_language if company else "uz",
        "languages": LANGUAGES,
        "telegram": {
            "configured": connected,
            "bot_username": row.bot_username if connected else None,
        },
    }


class EditionView(APIView):
    """Which product this install is, its organization, and whether it still needs setting
    up. Public: the sign-in page reads it."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (AddressRateThrottle,)
    address_throttle_scope = "owner_auth_address"

    @extend_schema(responses=shapes.EditionSerializer)
    def get(self, request):
        return Response(edition_payload())


class PublicCookieView(APIView):
    """Public endpoints that answer with a session (an access token and the refresh cookie):
    only the dashboard itself may call them (`X-Requested-With: dashboard`, same origin)."""

    authentication_classes = ()
    permission_classes = (AllowAny, FromDashboard)
    throttle_classes = (AddressRateThrottle,)
    address_throttle_scope = "owner_auth_address"

    def get_authenticate_header(self, request):
        return 'Bearer realm="dashboard"'


class SetupView(PublicCookieView):
    """The first run: the organization and its owner, signed in at once. Only while no
    organization exists (409 afterwards)."""

    def initial(self, request, *args, **kwargs):
        if not conf.is_on():
            raise Http404
        super().initial(request, *args, **kwargs)

    @extend_schema(
        request=shapes.SetupSerializer,
        responses={
            201: OpenApiResponse(description="Signed in: {access} and the refresh cookie."),
            409: OpenApiResponse(description="The organization exists already."),
        },
    )
    def post(self, request):
        if not services.needs_setup():
            return _setup_done()
        serializer = shapes.SetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            with field_errors():
                owner = services.setup_organization(
                    name=data["organization"],
                    timezone=data["timezone"],
                    language=data["language"],
                    admin=dict(data["admin"]),
                )
        except services.SetupDone:
            return _setup_done()
        return signin.session_response(owner.user, request, status=status.HTTP_201_CREATED)


def _setup_done() -> Response:
    return Response(
        {"detail": _("The organization is already set up. Sign in instead."), "code": "setup_done"},
        status=status.HTTP_409_CONFLICT,
    )


# Passwords --------------------------------------------------------------------------------------


def _locked(retry_after: int) -> Response:
    minutes = max(1, (retry_after + 59) // 60)
    response = Response(
        {
            "detail": ngettext(
                "Too many wrong passwords. Try again in %(count)s minute.",
                "Too many wrong passwords. Try again in %(count)s minutes.",
                minutes,
            )
            % {"count": minutes},
            "code": "locked",
        },
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
    response["Retry-After"] = str(retry_after)
    return response


class PasswordLoginView(PublicCookieView):
    """Sign in with a username and password (both editions). Five wrong passwords for one
    username from one address lock it for 15 minutes (429)."""

    @extend_schema(
        request=shapes.PasswordLoginSerializer,
        responses={
            200: OpenApiResponse(description="Signed in: {access} and the refresh cookie."),
            400: OpenApiResponse(description='{"detail": "Wrong username or password."}'),
            403: OpenApiResponse(description="The account may not use the web app."),
            429: OpenApiResponse(description="Locked for a while after wrong passwords."),
        },
    )
    def post(self, request):
        serializer = shapes.PasswordLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            user = passwords.sign_in(request, data["username"], data["password"])
        except passwords.Locked as locked:
            return _locked(locked.retry_after)
        except passwords.WrongPassword:
            return Response(
                {"detail": _("Wrong username or password."), "code": "wrong_password"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except passwords.NoAccess:
            return Response(
                {
                    "detail": _("This account can't use the web app. Ask your administrator."),
                    "code": "no_access",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return signin.session_response(user, request)


class PasswordChangeView(APIView):
    """Change your own password: every other browser of yours is signed out."""

    authentication_classes = (OwnerJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (AddressRateThrottle,)
    address_throttle_scope = "owner_auth_address"

    @extend_schema(
        request=shapes.PasswordChangeSerializer,
        responses={204: None, 400: OpenApiResponse(description="{current|new: [messages]}")},
    )
    def post(self, request):
        serializer = shapes.PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        token = getattr(request, "auth", None)
        session = token.get(SESSION_CLAIM) if token is not None else None
        try:
            with field_errors():
                passwords.change_password(
                    request.user,
                    current=data.get("current", ""),
                    new=data["new"],
                    request=request,
                    keep_session=session if isinstance(session, int) else None,
                )
        except passwords.Locked as locked:
            return _locked(locked.retry_after)
        return Response(status=status.HTTP_204_NO_CONTENT)


# Settings -----------------------------------------------------------------------------------


def _settings_payload(row: DavomatSettings) -> dict:
    return {"product_name": row.product_name, "auto_create_employees": row.auto_create_employees}


class SettingsView(DavomatOnly, OwnerAPIView):
    perms_by_action = {"patch": Perm.COMPANY_SETTINGS}

    @extend_schema(responses=shapes.SettingsSerializer)
    def get(self, request, company_id):
        return Response(_settings_payload(conf.get_settings(self.company)))

    @extend_schema(request=shapes.SettingsSerializer, responses=shapes.SettingsSerializer)
    def patch(self, request, company_id):
        serializer = shapes.SettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        row = services.update_settings(
            self.company, by=self.membership, **serializer.validated_data
        )
        return Response(_settings_payload(row))


# Users ------------------------------------------------------------------------------------


def user_payload(person: Membership, *, viewer: Membership, employees: set[int]) -> dict:
    role = person.role
    kind = queries.role_kind(role)
    user = person.user
    return {
        "id": person.pk,
        "username": user.username,
        "first_name": person.first_name,
        "last_name": person.last_name,
        "role": {"id": role.pk, "name": role.name, "kind": kind}
        if kind in queries.WEB_KINDS
        else None,
        "branch_ids": sorted(branch.pk for branch in person.branches.all()),
        "is_active": user.is_active and person.status == Membership.Status.APPROVED,
        "last_login": user.last_login,
        "telegram_linked": user.telegram_id is not None,
        "is_employee": person.pk in employees,
        "is_self": person.pk == viewer.pk,
    }


def _employee_ids(people) -> set[int]:
    from apps.davomat.models import Employee

    return set(
        Employee.objects.filter(membership__in=[p.pk for p in people]).values_list(
            "membership_id", flat=True
        )
    )


def _role(company: Company, data: dict) -> AccessRole | None:
    """The role asked for, by id or by kind ("manager")."""
    if data.get("role_id") is not None:
        return _row_of(AccessRole, company, data["role_id"], "role_id")
    if data.get("role"):
        roles = queries.web_roles(company)
        found = [role for role in roles if queries.role_kind(role) == data["role"]]
        if not found:
            raise ValidationError({"role": [_("Pick one of the roles offered.")]})
        return found[0]
    return None


class UserViewSet(DavomatOnly, OwnerViewSet):
    """The people who sign in to the web app."""

    perm = Perm.ROLES_MANAGE
    perms_by_action = {"telegram_link": None}
    pagination_class = DavomatPagination

    def get_queryset(self):
        return scope.restrict(queries.users(self.company), self.branch_scope, field="branches")

    def _one(self, pk) -> Membership:
        person = self.get_queryset().filter(pk=pk).first()
        if person is None:
            raise Http404
        return person

    def _payload(self, person: Membership) -> dict:
        person = queries.users(self.company).get(pk=person.pk)
        return user_payload(person, viewer=self.membership, employees=_employee_ids([person]))

    @extend_schema(
        parameters=[
            OpenApiParameter("search", str, description="Name or username."),
            OpenApiParameter("kind", str, enum=list(queries.WEB_KINDS)),
            OpenApiParameter("active", bool),
        ],
        responses=shapes.UserSerializer(many=True),
    )
    def list(self, request, company_id):
        people = self.get_queryset()
        params = request.query_params
        if text := params.get("search", "").strip():
            for word in text.split()[:4]:
                people = people.filter(
                    Q(first_name__icontains=word)
                    | Q(last_name__icontains=word)
                    | Q(user__username__icontains=word)
                )
        active = _flag(params.get("active"))
        rows = list(people.distinct())
        if kind := params.get("kind"):
            rows = [person for person in rows if queries.role_kind(person.role) == kind]
        if active is not None:
            rows = [
                person
                for person in rows
                if (person.user.is_active and person.status == Membership.Status.APPROVED) == active
            ]
        page = self.paginate_queryset(rows)
        employees = _employee_ids(page)
        return self.get_paginated_response(
            [user_payload(p, viewer=self.membership, employees=employees) for p in page]
        )

    @extend_schema(request=shapes.UserCreateSerializer, responses={201: shapes.UserSerializer})
    def create(self, request, company_id):
        serializer = shapes.UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        employee = None
        if data.get("employee_id") is not None:
            employee = (
                queries.employees(self.company, branch_ids=self.branch_scope)
                .filter(pk=data["employee_id"])
                .first()
            )
            if employee is None:
                raise ValidationError({"employee_id": [_("Pick a current employee.")]})
        role = _role(self.company, data)
        if role is None:
            raise ValidationError({"role_id": [_("Pick one of the roles offered.")]})
        with field_errors():
            person = services.create_user(
                self.company,
                by=self.membership,
                username=data["username"],
                password=data["password"],
                role=role,
                first_name=data.get("first_name", ""),
                last_name=data.get("last_name", ""),
                branches=_branches_of(self.company, data.get("branch_ids")) or [],
                employee=employee,
            )
        return Response(self._payload(person), status=status.HTTP_201_CREATED)

    @extend_schema(responses=shapes.UserSerializer)
    def retrieve(self, request, company_id, pk):
        return Response(self._payload(self._one(pk)))

    @extend_schema(request=shapes.UserUpdateSerializer, responses=shapes.UserSerializer)
    def partial_update(self, request, company_id, pk):
        person = self._one(pk)
        serializer = shapes.UserUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with field_errors():
            person = services.update_user(
                person,
                by=self.membership,
                username=data.get("username"),
                first_name=data.get("first_name"),
                last_name=data.get("last_name"),
                role=_role(self.company, data),
                branches=_branches_of(self.company, data.get("branch_ids")),
                is_active=data.get("is_active"),
                is_employee=data.get("is_employee"),
            )
        return Response(self._payload(person))

    @extend_schema(request=None, responses={204: None})
    def destroy(self, request, company_id, pk):
        """Switch the user off (nothing is deleted; `activate/` brings them back)."""
        services.set_active(self._one(pk), by=self.membership, active=False)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=shapes.UserSerializer)
    @action(detail=True, methods=["post"])
    def deactivate(self, request, company_id, pk):
        person = services.set_active(self._one(pk), by=self.membership, active=False)
        return Response(self._payload(person))

    @extend_schema(request=None, responses=shapes.UserSerializer)
    @action(detail=True, methods=["post"])
    def activate(self, request, company_id, pk):
        person = services.set_active(self._one(pk), by=self.membership, active=True)
        return Response(self._payload(person))

    @extend_schema(request=shapes.PasswordSetSerializer, responses={204: None})
    @action(detail=True, methods=["post"])
    def password(self, request, company_id, pk):
        """Give the user a new password: their sessions end (yours stays, for your own)."""
        person = self._one(pk)
        serializer = shapes.PasswordSetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = request.auth.get(SESSION_CLAIM) if request.auth is not None else None
        with field_errors():
            passwords.set_password(
                person,
                by=self.membership,
                password=serializer.validated_data["password"],
                keep_session=session if isinstance(session, int) else None,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses=shapes.RoleSerializer(many=True))
    @action(detail=False, methods=["get"])
    def roles(self, request, company_id):
        """The roles a user can be given, strongest first."""
        return Response(
            [
                {"id": role.pk, "name": role.name, "kind": queries.role_kind(role)}
                for role in queries.web_roles(self.company)
            ]
        )

    @extend_schema(methods=["POST"], request=None, responses={201: shapes.TelegramLinkSerializer})
    @extend_schema(methods=["DELETE"], request=None, responses={204: None})
    @action(detail=True, methods=["post", "delete"], url_path="telegram-link")
    def telegram_link(self, request, company_id, pk):
        """A one-time link for the user's Telegram (yourself, or anyone with roles.manage), or
        DELETE to unlink it."""
        if str(pk) == str(self.membership.pk):
            person = self.membership
        else:
            if not self.membership.has_perm(Perm.ROLES_MANAGE):
                self.permission_denied(request, message=_("You don't have permission to do this."))
            person = self._one(pk)
        return _telegram_link(request, person, by=self.membership)


def _telegram_link(request, person: Membership, *, by: Membership) -> Response:
    if request.method == "DELETE":
        services.unlink_telegram(person, by=by)
        return Response(status=status.HTTP_204_NO_CONTENT)
    made = services.make_link(person, by=by)
    return Response(
        {"url": made.url, "code": made.code, "expires_at": made.link.expires_at},
        status=status.HTTP_201_CREATED,
    )


# Employees --------------------------------------------------------------------------------


def employee_rows(company: Company, people: list[Membership], now: datetime) -> list[dict]:
    """The employee shape (§1.4) of each person, in order."""
    if not people:
        return []
    ids = [person.pk for person in people]
    dates = employment_dates(company, ids)
    today = queries.today_states(company, people, now)
    return [employee_payload(person, dates=dates, today=today) for person in people]


def employee_payload(person: Membership, *, dates: dict, today: dict) -> dict:
    user = person.user
    hired, left = dates.get(person.pk, (None, None))
    assignment = getattr(person, "work_schedule", None)
    gone = person.status == Membership.Status.LEFT
    employee = getattr(person, "davomat_employee", None)
    return {
        "id": person.pk,
        "first_name": person.first_name,
        "last_name": person.last_name,
        "full_name": person.full_name or str(user),
        "photo_url": user.photo.url if user.photo else None,
        "phone": user.phone or "",
        "position": {"id": person.position_id, "name": person.position.name}
        if person.position_id
        else None,
        "department": {"id": person.department_id, "name": person.department.name}
        if person.department_id
        else None,
        "branch_ids": sorted(branch.pk for branch in person.branches.all()),
        "face_numbers": sorted(link.employee_no for link in person.face_links.all()),
        "status": "left" if gone else "active",
        "hire_date": hired,
        "left_on": left if gone else None,
        "schedule": {"id": assignment.schedule_id, "name": assignment.schedule.name}
        if assignment is not None and assignment.schedule_id
        else None,
        "telegram_linked": user.telegram_id is not None,
        "is_user": queries.is_user(person),
        "source": employee.source if employee is not None else "manual",
        "today": today.get(person.pk),
    }


class XlsxRenderer(BaseRenderer):
    """Lets `?format=xlsx` through DRF's content negotiation; the view answers the file."""

    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    format = "xlsx"
    charset = None
    render_style = "binary"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data if isinstance(data, bytes) else json.dumps(data, default=str).encode()


class CsvRenderer(XlsxRenderer):
    media_type = "text/csv"
    format = "csv"


EMPLOYEE_FILTERS = [
    OpenApiParameter("search", str, description="Name, phone or face number."),
    OpenApiParameter("branch", int),
    OpenApiParameter("department", int),
    OpenApiParameter("position", int),
    OpenApiParameter("status", str, enum=["active", "left"]),
    OpenApiParameter("linked", bool, description="Telegram linked (true) or not (false)."),
    OpenApiParameter("face", bool, description="Has face numbers (true) or none (false)."),
]


class EmployeeViewSet(DavomatOnly, OwnerViewSet):
    """The people who scan at the terminals."""

    perm = Perm.MEMBERS_VIEW
    perms_by_action = {
        action: Perm.MEMBERS_MANAGE
        for action in (
            "create",
            "partial_update",
            "photo",
            "leave",
            "return_",
            "face_numbers",
            "face_number",
            "telegram_link",
            "import_",
        )
    }
    pagination_class = DavomatPagination

    def get_queryset(self):
        return (
            queries.employees(self.company, branch_ids=self.branch_scope)
            .select_related(
                "user",
                "role",
                "position",
                "department",
                "home_branch",
                "davomat_employee",
                "work_schedule__schedule",
            )
            .prefetch_related("branches", "face_links")
            .order_by("first_name", "last_name", "pk")
        )

    def _one(self, pk) -> Membership:
        person = self.get_queryset().filter(pk=pk).first()
        if person is None:
            raise Http404
        return person

    def _payload(self, person: Membership) -> dict:
        (row,) = employee_rows(self.company, [self._one(person.pk)], timezone.now())
        return row

    def _filtered(self, request):
        people = self.get_queryset()
        params = request.query_params
        if text := params.get("search", "").strip():
            key = hikvision.number_key(text)
            digits = "".join(ch for ch in text if ch.isdigit())
            for word in text.split()[:4]:
                people = people.filter(Q(first_name__icontains=word) | Q(last_name__icontains=word))
            if key or len(digits) >= 4:
                numbers = Q(face_links__number_key=key) if key else Q(pk__in=[])
                phones = Q(user__phone__contains=digits) if len(digits) >= 4 else Q(pk__in=[])
                people = people | self.get_queryset().filter(numbers | phones)
        if (branch := _number(params, "branch")) is not None:
            people = people.filter(branches=branch)
        if (department := _number(params, "department")) is not None:
            people = people.filter(department_id=department)
        if (position := _number(params, "position")) is not None:
            people = people.filter(position_id=position)
        state = params.get("status")
        if state == "active":
            people = people.filter(status__in=queries.CURRENT)
        elif state == "left":
            people = people.filter(status=Membership.Status.LEFT)
        if (linked := _flag(params.get("linked"))) is not None:
            people = people.filter(user__telegram_id__isnull=not linked)
        if (face := _flag(params.get("face"))) is not None:
            people = people.filter(face_links__isnull=not face)
        return people.distinct()

    @extend_schema(parameters=EMPLOYEE_FILTERS, responses=shapes.EmployeeSerializer(many=True))
    def list(self, request, company_id):
        page = self.paginate_queryset(self._filtered(request))
        return self.get_paginated_response(employee_rows(self.company, page, timezone.now()))

    def _write_fields(self, data: dict) -> dict:
        company = self.company
        fields = {}
        for name in ("first_name", "last_name", "phone", "hire_date", "face_numbers"):
            if name in data:
                fields[name] = data[name]
        if "position_id" in data:
            fields["position"] = _row_of(Position, company, data["position_id"], "position_id")
        if "department_id" in data:
            fields["department"] = _row_of(
                Department, company, data["department_id"], "department_id"
            )
        if "schedule_id" in data:
            fields["schedule"] = _row_of(WorkSchedule, company, data["schedule_id"], "schedule_id")
        if "branch_ids" in data:
            fields["branches"] = _branches_of(company, data["branch_ids"])
        return fields

    @extend_schema(
        request=shapes.EmployeeWriteSerializer, responses={201: shapes.EmployeeSerializer}
    )
    def create(self, request, company_id):
        serializer = shapes.EmployeeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fields = self._write_fields(serializer.validated_data)
        with field_errors():
            person = services.create_employee(self.company, by=self.membership, **fields)
        return Response(self._payload(person), status=status.HTTP_201_CREATED)

    @extend_schema(responses=shapes.EmployeeSerializer)
    def retrieve(self, request, company_id, pk):
        return Response(self._payload(self._one(pk)))

    @extend_schema(request=shapes.EmployeeWriteSerializer, responses=shapes.EmployeeSerializer)
    def partial_update(self, request, company_id, pk):
        person = self._one(pk)
        serializer = shapes.EmployeeWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = self._write_fields(serializer.validated_data)
        if fields.get("hire_date", services.UNSET) is None:
            fields.pop("hire_date")  # a hire date is never cleared, only changed
        with field_errors():
            person = services.update_employee(person, by=self.membership, **fields)
        return Response(self._payload(person))

    @extend_schema(
        methods=["POST"],
        request={"multipart/form-data": shapes.PhotoSerializer},
        responses=shapes.EmployeeSerializer,
    )
    @extend_schema(methods=["DELETE"], request=None, responses=shapes.EmployeeSerializer)
    @action(detail=True, methods=["post", "delete"], parser_classes=[MultiPartParser, FormParser])
    def photo(self, request, company_id, pk):
        """Their photo (re-encoded on the server), or DELETE to remove it."""
        person = self._one(pk)
        picture = None
        if request.method == "POST":
            upload = request.FILES.get("photo")
            if upload is None:
                raise ValidationError({"photo": [_("Choose a photo.")]})
            picture = sanitize_image(upload, max_side=PHOTO_SIDE)
        services.set_photo(person, by=self.membership, photo=picture)
        return Response(self._payload(person))

    @extend_schema(request=shapes.LeaveSerializer, responses=shapes.EmployeeSerializer)
    @action(detail=True, methods=["post"])
    def leave(self, request, company_id, pk):
        """They left on `left_on` (today if empty)."""
        person = self._one(pk)
        serializer = shapes.LeaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.leave(person, by=self.membership, left_on=serializer.validated_data.get("left_on"))
        return Response(self._payload(person))

    @extend_schema(request=shapes.ReturnSerializer, responses=shapes.EmployeeSerializer)
    @action(detail=True, methods=["post"], url_path="return")
    def return_(self, request, company_id, pk):
        """Someone who left comes back, hired again on `hire_date` (today if empty)."""
        person = self._one(pk)
        serializer = shapes.ReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with field_errors():
            services.return_employee(
                person, by=self.membership, hire_date=serializer.validated_data.get("hire_date")
            )
        return Response(self._payload(person))

    @extend_schema(request=shapes.FaceNumberSerializer, responses=shapes.EmployeeSerializer)
    @action(detail=True, methods=["post"], url_path="face-numbers")
    def face_numbers(self, request, company_id, pk):
        """Link one more terminal number to them."""
        person = self._one(pk)
        serializer = shapes.FaceNumberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with field_errors():
            services.add_face_number(
                person, by=self.membership, number=serializer.validated_data["number"]
            )
        return Response(self._payload(person))

    @extend_schema(request=None, responses=shapes.EmployeeSerializer)
    @action(detail=True, methods=["delete"], url_path=r"face-numbers/(?P<number>[^/]+)")
    def face_number(self, request, company_id, pk, number):
        """Unlink one of their terminal numbers."""
        person = self._one(pk)
        services.remove_face_number(person, by=self.membership, number=number)
        return Response(self._payload(person))

    @extend_schema(methods=["POST"], request=None, responses={201: shapes.TelegramLinkSerializer})
    @extend_schema(methods=["DELETE"], request=None, responses={204: None})
    @action(detail=True, methods=["post", "delete"], url_path="telegram-link")
    def telegram_link(self, request, company_id, pk):
        """A one-time link (24 hours) for their Telegram, or DELETE to unlink it."""
        return _telegram_link(request, self._one(pk), by=self.membership)

    @extend_schema(
        parameters=[OpenApiParameter("dry_run", bool, description="Only say what would happen.")],
        request={"multipart/form-data": shapes.ImportUploadSerializer},
        responses=shapes.ImportResultSerializer,
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="import",
        parser_classes=[MultiPartParser, FormParser],
    )
    def import_(self, request, company_id):
        """Employees from an XLSX or CSV file (first name, last name, phone, position,
        department, branch, face number, hire date): a face number someone has updates them,
        the rest are added. `?dry_run=1` changes nothing."""
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": [_("Choose a file.")]})
        dry_run = bool(_flag(request.query_params.get("dry_run") or request.data.get("dry_run")))
        result = importing.import_employees(
            self.company, upload, by=self.membership, dry_run=dry_run
        )
        return Response(result)

    @extend_schema(
        parameters=[
            OpenApiParameter("format", str, enum=["xlsx", "csv"], description="xlsx if empty."),
            *EMPLOYEE_FILTERS,
        ],
        responses={
            (200, XlsxRenderer.media_type): OpenApiTypes.BINARY,
            (200, CsvRenderer.media_type): OpenApiTypes.BINARY,
        },
    )
    @action(
        detail=False, methods=["get"], renderer_classes=[JSONRenderer, XlsxRenderer, CsvRenderer]
    )
    def export(self, request, company_id):
        """The employees (with the list's filters) as a spreadsheet, in the columns the import
        reads."""
        people = list(self._filtered(request))
        dates = employment_dates(self.company, [person.pk for person in people])
        rows = importing.export_rows(self.company, people, dates)
        day = clock.today(self.company)
        title = _("Employees")
        if request.query_params.get("format") == "csv":
            content, media, suffix = importing.as_csv(rows), CsvRenderer.media_type, "csv"
        else:
            content = importing.as_xlsx(rows, title=title)
            media, suffix = XlsxRenderer.media_type, "xlsx"
        response = HttpResponse(content, content_type=media)
        response["Content-Disposition"] = f'attachment; filename="employees-{day}.{suffix}"'
        response["X-Content-Type-Options"] = "nosniff"
        return response


# Telegram ---------------------------------------------------------------------------------


def telegram_payload(row: DavomatSettings) -> dict:
    connected = bool(row.bot_token and row.bot_username)
    return {
        "configured": connected,
        "bot_username": row.bot_username or None,
        "bot_name": row.bot_name or None,
        "status": row.bot_status,
        "checked_at": row.bot_checked_at,
    }


class TelegramView(DavomatOnly, OwnerAPIView):
    """The organization's own bot: PUT a BotFather token (checked with Telegram first, kept
    encrypted, never shown again), DELETE to disconnect it."""

    perm = Perm.COMPANY_SETTINGS

    @extend_schema(responses=shapes.TelegramSerializer)
    def get(self, request, company_id):
        return Response(telegram_payload(conf.get_settings(self.company)))

    @extend_schema(request=shapes.TelegramSerializer, responses=shapes.TelegramSerializer)
    def put(self, request, company_id):
        token = request.data.get("token") if hasattr(request.data, "get") else None
        if not isinstance(token, str) or not token.strip():
            raise ValidationError({"token": [_("Paste the token BotFather gave you.")]})
        with field_errors():
            row = services.connect_bot(self.company, by=self.membership, token=token)
        return Response(telegram_payload(row))

    @extend_schema(request=None, responses={204: None})
    def delete(self, request, company_id):
        services.disconnect_bot(self.company, by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TelegramTestView(DavomatOnly, OwnerAPIView):
    """A test message from the bot to you (your Telegram must be linked)."""

    perm = Perm.COMPANY_SETTINGS

    @extend_schema(request=None, responses={200: shapes.SentSerializer, 400: OpenApiResponse()})
    def post(self, request, company_id):
        row = conf.get_settings(self.company)
        if not (row.bot_token and row.bot_username):
            raise ValidationError({"detail": _("Connect the Telegram bot first.")})
        chat = request.user.telegram_id
        if chat is None:
            raise ValidationError({"detail": _("Link your Telegram first, then try again.")})
        product = conf.product_name(self.company)
        text = _("Test message from %(product)s.") % {"product": product}
        try:
            bots.send_message(bots.BotName.OWNER, chat, text)
        except TelegramUnauthorizedError as exc:
            services.mark_bot_refused(self.company)
            raise ValidationError(
                {"detail": _("Telegram doesn't accept the bot's token any more. Paste a new one.")}
            ) from exc
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            raise ValidationError(
                {"detail": _("Open the bot in Telegram, press Start, then try again.")}
            ) from exc
        except (TelegramAPIError, OSError) as exc:
            raise ValidationError(
                {"detail": _("Telegram can't be reached right now. Try again in a minute.")}
            ) from exc
        return Response({"sent": True})
