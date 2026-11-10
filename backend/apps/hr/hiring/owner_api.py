"""Owner dashboard endpoints of hiring (`hr.hiring`), mounted with HR's under
`/api/v1/owner/companies/<id>/`:

    GET/POST          hr/vacancies/?status&branch&q          vacancies with counts per stage
    GET/PATCH/DELETE  hr/vacancies/{id}/                     (DELETE only without applicants)
    POST              hr/vacancies/{id}/open|pause|close/
    GET               hr/vacancies/{id}/qr/?plain            the QR code as a PNG
    GET               hr/applicants/?vacancy&stage&source&q&branch
    GET               hr/applicants/{id}/                    answers, diploma photo, history
    POST              hr/applicants/{id}/move/   {stage, message, notify}
    POST              hr/applicants/{id}/reject/ {reason, message, notify}
    POST              hr/applicants/{id}/hire/   {branch_id, message}   (also members.approve)
    POST              hr/applicants/{id}/notes/  {text}

A vacancy outside the caller's branches answers 404 like another company's (one without a
branch needs every branch), and so do its applicants; everything answers 403 while HR is off.
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.companies.models import Branch
from apps.console.base import OwnerViewSet
from apps.core import qr
from apps.core.api import Pagination
from apps.hr.hiring import queries, services
from apps.hr.hiring import serializers as s
from apps.hr.models import Applicant, Vacancy
from apps.hr.owner_api import ModuleOn
from apps.members.models import Position
from apps.members.permissions import Perm

HIRING = Perm.HR_HIRING
BRANCH_PARAM = OpenApiParameter("branch", int, many=True, description="Branch ids (in scope).")


def _ints(values, name: str) -> list[int]:
    try:
        return [int(value) for value in values if str(value).strip()]
    except ValueError as exc:
        raise ValidationError({name: [_("Give a number.")]}) from exc


class ApplicantPagination(Pagination):
    """The pipeline board asks for a whole vacancy at once."""

    max_page_size = 500


class VacancyViewSet(
    ModuleOn,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    OwnerViewSet,
):
    """Vacancies in the caller's branches, working ones first, each with its stage counts."""

    perm = HIRING
    serializer_class = s.VacancySerializer
    lookup_value_regex = r"\d+"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Vacancy.objects.none()
        rows = queries.with_counts(queries.vacancies(self.company, branch_ids=self.branch_scope))
        if self.action != "list":
            return rows
        params = self.request.query_params
        statuses = [value for value in params.getlist("status") if value in Vacancy.Status.values]
        if statuses:
            rows = rows.filter(status__in=statuses)
        if branches := _ints(params.getlist("branch"), "branch"):
            rows = rows.filter(branch_id__in=branches)
        if q := (params.get("q") or "").strip():
            rows = rows.filter(title__icontains=q)
        return queries.ordered(rows)

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, many=True, enum=list(Vacancy.Status.values)),
            OpenApiParameter("q", str),
            BRANCH_PARAM,
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=s.VacancyWriteSerializer, responses={201: s.VacancySerializer})
    def create(self, request, company_id):
        serializer = s.VacancyWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        publish = data.pop("publish", False)
        vacancy = services.create_vacancy(
            self.company, by=self.membership, publish=publish, **self._fields(data)
        )
        return Response(self._one(vacancy), status=status.HTTP_201_CREATED)

    @extend_schema(request=s.VacancyPatchSerializer, responses=s.VacancySerializer)
    def partial_update(self, request, company_id, pk):
        vacancy = self.get_object()
        serializer = s.VacancyPatchSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("publish", None)
        vacancy = services.update_vacancy(vacancy, by=self.membership, **self._fields(data))
        return Response(self._one(vacancy))

    @extend_schema(responses={204: None})
    def destroy(self, request, company_id, pk):
        services.delete_vacancy(self.get_object(), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=s.VacancySerializer)
    @action(detail=True, methods=["post"], url_path="open")
    def open_up(self, request, company_id, pk):
        return self._status(Vacancy.Status.OPEN)

    @extend_schema(request=None, responses=s.VacancySerializer)
    @action(detail=True, methods=["post"])
    def pause(self, request, company_id, pk):
        return self._status(Vacancy.Status.PAUSED)

    @extend_schema(request=None, responses=s.VacancySerializer)
    @action(detail=True, methods=["post"])
    def close(self, request, company_id, pk):
        return self._status(Vacancy.Status.CLOSED)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "plain", bool, description="The plain link's code (default: the QR code's own)."
            )
        ],
        responses={
            (200, "image/png"): OpenApiResponse(OpenApiTypes.BINARY, description="A PNG."),
            404: OpenApiResponse(description="No such vacancy, or no bot username set."),
        },
    )
    @action(detail=True, methods=["get"])
    def qr(self, request, company_id, pk):
        vacancy = self.get_object()
        link = vacancy.bot_link(qr=request.query_params.get("plain") != "true")
        if not link:
            return Response(status=status.HTTP_404_NOT_FOUND)
        response = HttpResponse(qr.png(link), content_type="image/png")
        name = slugify(vacancy.title) or f"vacancy-{vacancy.pk}"
        response["Content-Disposition"] = f'inline; filename="{name}-qr.png"'
        response["Cache-Control"] = "private, max-age=300"
        return response

    def _status(self, value: str):
        vacancy = services.set_status(self.get_object(), value, by=self.membership)
        return Response(self._one(vacancy))

    def _fields(self, data: dict) -> dict:
        """The validated body as the service takes it: rows of this company for the ids."""
        fields = {name: value for name, value in data.items() if not name.endswith("_id")}
        for name, model in (("position", Position), ("branch", Branch)):
            key = f"{name}_id"
            if key in data:
                value = data[key]
                fields[name] = (
                    get_object_or_404(model.objects.filter(company=self.company), pk=value)
                    if value is not None
                    else None
                )
        return fields

    def _one(self, vacancy: Vacancy) -> dict:
        fresh = self.get_queryset().filter(pk=vacancy.pk).first()
        return s.VacancySerializer(fresh, context=self.get_serializer_context()).data


class ApplicantViewSet(
    ModuleOn,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    OwnerViewSet,
):
    """Applicants of the vacancies in the caller's branches, newest first."""

    perm = HIRING
    serializer_class = s.ApplicantSerializer
    pagination_class = ApplicantPagination
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Applicant.objects.none()
        params = self.request.query_params
        rows = queries.applicants(self.company, branch_ids=self.branch_scope)
        if self.action != "list":
            return rows
        vacancies = _ints(params.getlist("vacancy"), "vacancy")
        if vacancies:
            rows = rows.filter(vacancy_id__in=vacancies)
        stages = [value for value in params.getlist("stage") if value in queries.STAGES]
        if stages:
            rows = rows.filter(stage__in=stages)
        if (source := params.get("source")) in Applicant.Source.values:
            rows = rows.filter(source=source)
        if branches := _ints(params.getlist("branch"), "branch"):
            rows = rows.filter(vacancy__branch_id__in=branches)
        if q := params.get("q"):
            rows = queries.applicants(self.company, branch_ids=self.branch_scope, q=q).filter(
                pk__in=rows.values("pk")
            )
        return rows.order_by("-created_at", "-pk")

    def get_serializer_class(self):
        return s.ApplicantDetailSerializer if self.action == "retrieve" else s.ApplicantSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("vacancy", int, many=True),
            OpenApiParameter("stage", str, many=True, enum=list(queries.STAGES)),
            OpenApiParameter("source", str, enum=list(Applicant.Source.values)),
            OpenApiParameter("q", str, description="Name, phone digits or @username."),
            BRANCH_PARAM,
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=s.MoveSerializer, responses=s.ApplicantDetailSerializer)
    @action(detail=True, methods=["post"])
    def move(self, request, company_id, pk):
        data = self._valid(s.MoveSerializer)
        applicant = services.move(
            self.get_object(),
            data["stage"],
            by=self.membership,
            message=data["message"],
            notify=data["notify"],
        )
        return Response(self._one(applicant))

    @extend_schema(request=s.RejectSerializer, responses=s.ApplicantDetailSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, company_id, pk):
        data = self._valid(s.RejectSerializer)
        applicant = services.reject(
            self.get_object(),
            by=self.membership,
            reason=data["reason"],
            message=data["message"],
            notify=data["notify"],
        )
        return Response(self._one(applicant))

    @extend_schema(request=s.HireSerializer, responses=s.ApplicantDetailSerializer)
    @action(detail=True, methods=["post"])
    def hire(self, request, company_id, pk):
        data = self._valid(s.HireSerializer)
        branch = None
        if data.get("branch_id") is not None:
            branch = get_object_or_404(
                Branch.objects.filter(company=self.company), pk=data["branch_id"]
            )
        applicant = services.hire(
            self.get_object(), by=self.membership, branch=branch, message=data["message"]
        )
        return Response(self._one(applicant))

    @extend_schema(request=s.NoteSerializer, responses={201: s.ApplicantDetailSerializer})
    @action(detail=True, methods=["post"])
    def notes(self, request, company_id, pk):
        data = self._valid(s.NoteSerializer)
        applicant = self.get_object()
        services.add_note(applicant, by=self.membership, text=data["text"])
        return Response(self._one(applicant), status=status.HTTP_201_CREATED)

    def _valid(self, serializer_class) -> dict:
        serializer = serializer_class(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _one(self, applicant: Applicant) -> dict:
        fresh = queries.applicants(self.company, branch_ids=self.branch_scope).get(pk=applicant.pk)
        return s.ApplicantDetailSerializer(fresh, context=self.get_serializer_context()).data
