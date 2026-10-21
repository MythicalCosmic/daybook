"""One OpenAPI schema per audience: the mini app's types never see owner endpoints."""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import path
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.schema import split_by_audience


class ThingSerializer(serializers.Serializer):
    name = serializers.CharField()


class EmployeeThings(APIView):
    @extend_schema(responses=ThingSerializer)
    def get(self, request, company_id):
        return Response({"name": "mine"})


class OwnerThings(APIView):
    @extend_schema(responses=ThingSerializer)
    def get(self, request, company_id):
        return Response({"name": "everyone's"})


class OwnerMe(APIView):
    @extend_schema(responses=ThingSerializer)
    def get(self, request):
        return Response({"name": "me"})


PATTERNS = [
    path("api/v1/companies/<int:company_id>/things/", EmployeeThings.as_view()),
    path("api/v1/owner/companies/<int:company_id>/things/", OwnerThings.as_view()),
    path("api/v1/owner/me/", OwnerMe.as_view()),
]
EMPLOYEE_PATH = "/api/v1/companies/{company_id}/things/"
OWNER_PATHS = {"/api/v1/owner/companies/{company_id}/things/", "/api/v1/owner/me/"}


def schema_paths(patterns=None) -> set[str]:
    generator = SchemaGenerator(patterns=patterns)
    return set(generator.get_schema(request=None, public=True)["paths"])


def test_the_employee_schema_leaves_out_owner_endpoints(settings):
    settings.SCHEMA_AUDIENCE = "employee"

    assert schema_paths(PATTERNS) == {EMPLOYEE_PATH}


def test_the_owner_schema_has_only_owner_endpoints(settings):
    settings.SCHEMA_AUDIENCE = "owner"

    assert schema_paths(PATTERNS) == OWNER_PATHS


def test_without_an_audience_the_schema_has_everything(settings):
    settings.SCHEMA_AUDIENCE = ""

    assert schema_paths(PATTERNS) == {EMPLOYEE_PATH, *OWNER_PATHS}


def test_an_unknown_audience_is_refused(settings):
    settings.SCHEMA_AUDIENCE = "admins"

    with pytest.raises(ImproperlyConfigured):
        split_by_audience([("/api/v1/me/", r"^api/v1/me/$", "GET", None)])


def test_the_real_api_splits_cleanly(settings):
    settings.SCHEMA_AUDIENCE = "employee"
    employee = schema_paths()
    settings.SCHEMA_AUDIENCE = "owner"
    owner = schema_paths()
    settings.SCHEMA_AUDIENCE = ""
    everything = schema_paths()

    assert "/api/v1/me/" in employee
    assert not any(route.startswith("/api/v1/owner/") for route in employee)
    assert all(route.startswith("/api/v1/owner/") for route in owner)
    assert everything == employee | owner
    # The mini app gets access tokens only; its refresh route is gone.
    assert "/api/v1/auth/refresh/" not in everything


def generate(settings, audience: str) -> tuple[dict, list[str]]:
    """The audience's schema and every warning and error drf-spectacular raised making it."""
    settings.SCHEMA_AUDIENCE = audience
    GENERATOR_STATS.reset()
    try:
        with GENERATOR_STATS.silence():
            schema = SchemaGenerator().get_schema(request=None, public=True)
        return schema, sorted({*GENERATOR_STATS._warn_cache, *GENERATOR_STATS._error_cache})
    finally:
        GENERATOR_STATS.reset()


@pytest.mark.parametrize("audience", ["employee", "owner"])
def test_each_schema_generates_without_warnings(settings, audience):
    """Two serializers sharing a component name, a view without a serializer, an enum named by
    a hash or a field the generator can't read: each makes a wrong schema, none is allowed.
    `make schema-check` (part of `make check`) runs the same through `spectacular
    --fail-on-warn`. Fix a clash with an app-prefixed `Meta.ref_name` ("SalesReason")."""
    _schema, problems = generate(settings, audience)

    assert problems == []


def test_the_mini_app_keeps_its_component_and_enum_names(settings):
    """`miniapp/src/api/types.ts` and `permissions.ts` read these by name."""
    schema, _problems = generate(settings, "employee")

    assert {
        "Me",
        "Membership",
        "Position",
        "Task",
        "TaskStatusEnum",
        "ActionsEnum",
        "Comment",
        "Activity",
        "Summary",
        "ReminderInfo",
        "Day",
        "MemberBrief",
        "LanguageEnum",
        "RepeatEnum",
        "ProofEnum",
        "PeriodEnum",
        "Score",
        "TeamRow",
        "TeamStats",
        "TimeOff",
        "TimeOffStatusEnum",
        "Holiday",
        "OffToday",
        "PermissionsEnum",
    } <= set(schema["components"]["schemas"])
