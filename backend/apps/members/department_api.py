"""Owner endpoints of departments (the company's structure, each department with a head), mounted
at `/api/v1/owner/companies/<int:company_id>/`:

    GET    departments/                 the tree, parents before children (members.view)
    POST   departments/                 a new department (members.manage, every branch)
    PATCH  departments/{id}/            rename, move, set or clear the head
    DELETE departments/{id}/            its people and sub-departments move up to its parent
    POST   departments/{id}/members/    put people into it (members.manage, your branches)
"""

from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.console.base import AnyOf, OwnerViewSet
from apps.members import departments
from apps.members.models import Department, Membership
from apps.members.owner_api import PersonRefSerializer
from apps.members.permissions import Perm
from apps.members.queries import person_ref


class DepartmentSerializer(serializers.ModelSerializer):
    parent_id = serializers.IntegerField(allow_null=True, read_only=True)
    head = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField(help_text="Current people directly in it.")
    total_count = serializers.SerializerMethodField(help_text="With every department below.")
    path = serializers.SerializerMethodField(help_text="Names from the top down to it.")
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = (
            "id",
            "name",
            "parent_id",
            "head",
            "member_count",
            "total_count",
            "path",
            "can_edit",
        )
        read_only_fields = fields

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_head(self, department: Department) -> dict | None:
        return person_ref(department.head)

    def get_member_count(self, department: Department) -> int:
        return self.context["counts"].get(department.pk, 0)

    def get_total_count(self, department: Department) -> int:
        counts = self.context["counts"]
        return sum(counts.get(pk, 0) for pk in self.context["org"].below([department.pk]))

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_path(self, department: Department) -> list[str]:
        return self.context["org"].path(department.pk)

    def get_can_edit(self, department: Department) -> bool:
        return self.context["can_edit"]


class DepartmentInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    parent_id = serializers.IntegerField(required=False, allow_null=True)
    head_id = serializers.IntegerField(required=False, allow_null=True)


class DepartmentPatchSerializer(DepartmentInputSerializer):
    name = serializers.CharField(max_length=100, required=False)


class DepartmentMembersSerializer(serializers.Serializer):
    member_ids = serializers.ListField(
        child=serializers.IntegerField(), min_length=1, max_length=departments.PLACE_LIMIT
    )


class DepartmentViewSet(mixins.ListModelMixin, OwnerViewSet):
    """The company's departments; a head manages everyone in theirs and below."""

    perm = Perm.MEMBERS_MANAGE
    perms_by_action = {"list": AnyOf(Perm.MEMBERS_VIEW, Perm.MEMBERS_MANAGE)}
    serializer_class = DepartmentSerializer
    pagination_class = None
    lookup_value_regex = r"\d+"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Department.objects.none()
        return Department.objects.for_company(self.company).select_related("head__user")

    def list(self, request, *args, **kwargs):
        org = departments.Org(self.company.pk)
        rows = [org.departments[pk] for pk in org.in_tree_order()]
        return Response(DepartmentSerializer(rows, many=True, context=self._context(org)).data)

    @extend_schema(request=DepartmentInputSerializer, responses={201: DepartmentSerializer})
    def create(self, request, company_id):
        serializer = DepartmentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        department = departments.create_department(
            self.company, by=self.membership, **self._fields(serializer.validated_data)
        )
        return Response(self._one(department), status=status.HTTP_201_CREATED)

    @extend_schema(request=DepartmentPatchSerializer, responses=DepartmentSerializer)
    def partial_update(self, request, company_id, pk):
        department = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = DepartmentPatchSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        department = departments.update_department(
            department, by=self.membership, **self._fields(serializer.validated_data)
        )
        return Response(self._one(department))

    @extend_schema(responses={204: None})
    def destroy(self, request, company_id, pk):
        departments.delete_department(
            get_object_or_404(self.get_queryset(), pk=pk), by=self.membership
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=DepartmentMembersSerializer, responses=DepartmentSerializer)
    @action(detail=True, methods=["post"])
    def members(self, request, company_id, pk):
        department = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = DepartmentMembersSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = list(dict.fromkeys(serializer.validated_data["member_ids"]))
        people = list(
            Membership.objects.for_company(self.company)
            .filter(pk__in=ids)
            .select_related("department", "user")
        )
        if len(people) != len(ids):
            raise serializers.ValidationError({"member_ids": [_("Pick people of this company.")]})
        departments.place(department, by=self.membership, people=people)
        return Response(self._one(department))

    def _fields(self, data: dict) -> dict:
        """The validated body as the service takes it: rows of this company for the ids."""
        fields = {"name": data["name"]} if "name" in data else {}
        if "parent_id" in data:
            fields["parent"] = (
                get_object_or_404(self.get_queryset(), pk=data["parent_id"])
                if data["parent_id"] is not None
                else None
            )
        if "head_id" in data:
            fields["head"] = (
                get_object_or_404(Membership.objects.for_company(self.company), pk=data["head_id"])
                if data["head_id"] is not None
                else None
            )
        return fields

    def _context(self, org: departments.Org) -> dict:
        return self.get_serializer_context() | {
            "org": org,
            "counts": departments.counts(self.company.pk),
            "can_edit": departments.may_edit_structure(self.membership),
        }

    def _one(self, department: Department) -> dict:
        org = departments.Org(self.company.pk)
        return DepartmentSerializer(
            org.departments.get(department.pk, department), context=self._context(org)
        ).data
