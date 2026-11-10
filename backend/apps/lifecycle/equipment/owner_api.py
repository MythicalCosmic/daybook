"""Equipment's owner endpoints (`lifecycle/equipment/…`, the lifecycle's Equipment page).

    GET   lifecycle/equipment/?branch                who holds what, totals, what the viewer may
    GET   lifecycle/equipment/items/?status=stock|out|all&branch     things to give out
    POST  lifecycle/equipment/items/ {category_id, name, quantity, branch_id, note, cost,
          serial, model}                             add things to give out
    GET   lifecycle/equipment/categories/            categories and the pharmacy's suggestions
    POST  lifecycle/equipment/categories/ {suggestion} or {name, kind, icon}
    POST  lifecycle/equipment/issue/ (multipart) {person_id, asset_ids, on, condition, note,
          photo}                                     give one or more things to someone
    POST  lifecycle/equipment/handouts/{id}/return/ (multipart) {outcome, on, condition, note,
          photo, write_off, deduction, reason}       it came back, or it is lost
    POST  lifecycle/equipment/handouts/{id}/deduction/ {amount, reason}
    GET   lifecycle/people/{member_id}/equipment/    Person 360's Equipment tab

`assets.manage` or `hr.manage` (a device: assets.manage to add or write off). Company- and
branch-scoped (someone outside the viewer's branches answers 404), 403 while HR or the assets
module is off. Every change goes through the assets services and is audited.
"""

from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.assets.models import AssetAssignment, AssetCategory
from apps.console.base import OwnerAPIView
from apps.hr import queries as hr_queries
from apps.lifecycle.equipment import queries, services
from apps.lifecycle.equipment import serializers as s
from apps.lifecycle.owner_api import ModuleOn
from apps.members.models import Membership

MANAGE = services.MANAGE
BRANCH = OpenApiParameter("branch", int, description="One branch (in scope).")


class EquipmentOn(ModuleOn):
    """HR (the lifecycle) and the assets module both on."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not self.company.has_feature("assets"):
            raise PermissionDenied(_("Assets aren't switched on for this company."))


class EquipmentView(EquipmentOn, OwnerAPIView):
    perm = MANAGE
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def branch_param(self) -> int | None:
        value = self.request.query_params.get("branch")
        if value in (None, ""):
            return None
        try:
            branch = int(value)
        except ValueError as exc:
            raise ValidationError({"branch": [_("Give a number.")]}) from exc
        allowed = self.branch_scope
        if allowed is not None and branch not in allowed:
            raise NotFound
        return branch

    def branch(self, pk):
        if pk in (None, ""):
            return None
        found = self.company.branches.filter(pk=pk, is_active=True).first()
        allowed = self.branch_scope
        if found is None or (allowed is not None and found.pk not in allowed):
            raise ValidationError({"branch_id": [_("Pick a branch you work with.")]})
        return found

    def person(self, member_id, *, statuses=hr_queries.EMPLOYED) -> Membership:
        found = (
            hr_queries.people(self.company, branch_ids=self.branch_scope, statuses=statuses)
            .filter(pk=member_id)
            .select_related("user", "company", "role", "position", "home_branch")
            .first()
        )
        if found is None:
            raise NotFound
        return found

    def handout(self, pk) -> AssetAssignment:
        row = (
            AssetAssignment.objects.filter(company=self.company, pk=pk)
            .select_related("asset__category", "membership")
            .first()
        )
        if row is None:
            raise NotFound
        self.person(row.membership_id)  # in the viewer's branches
        return row

    def holder(self, member: Membership) -> dict:
        return s.EquipmentHolderSerializer(
            queries.holder(self.company, self.membership, member)
        ).data


class PeopleView(EquipmentView):
    @extend_schema(
        parameters=[BRANCH],
        responses=s.EquipmentPeopleSerializer,
        operation_id="lifecycle_equipment_people",
    )
    def get(self, request, company_id):
        data = queries.people(self.company, self.membership, branch=self.branch_param())
        return Response(s.EquipmentPeopleSerializer(data).data)


class ItemsView(EquipmentView):
    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, enum=["stock", "out", "all"]),
            BRANCH,
        ],
        responses=s.EquipmentStockSerializer(many=True),
        operation_id="lifecycle_equipment_items",
    )
    def get(self, request, company_id):
        state = request.query_params.get("status") or "stock"
        if state not in ("stock", "out", "all"):
            raise ValidationError({"status": [_("In stock, given out or all.")]})
        rows = queries.items(
            self.company, self.membership, status=state, branch=self.branch_param()
        )
        return Response(s.EquipmentStockSerializer(rows, many=True).data)

    @extend_schema(
        request=s.AddItemsInputSerializer,
        responses={201: s.AddedSerializer},
        operation_id="lifecycle_equipment_add",
    )
    def post(self, request, company_id):
        serializer = s.AddItemsInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        category = AssetCategory.objects.for_company(self.company).filter(pk=data["category_id"])
        category = category.first()
        if category is None:
            raise ValidationError({"category_id": [_("Pick a category of this company.")]})
        branch = self.branch(data.get("branch_id"))
        if branch is None and self.branch_scope is not None:
            raise ValidationError({"branch_id": [_("Pick the branch it is at.")]})
        made = services.add_items(
            self.company,
            by=self.membership,
            category=category,
            name=data["name"],
            quantity=data["quantity"],
            branch=branch,
            note=data.get("note", ""),
            cost=data.get("cost"),
            serial=data.get("serial", ""),
            model=data.get("model", ""),
        )
        ids = {asset.pk for asset in made}
        rows = [
            row
            for row in queries.items(self.company, self.membership, status="all")
            if row["id"] in ids
        ]
        return Response(s.AddedSerializer({"items": rows}).data, status=status.HTTP_201_CREATED)


class CategoriesView(EquipmentView):
    @extend_schema(
        responses=s.EquipmentCategoriesSerializer, operation_id="lifecycle_equipment_categories"
    )
    def get(self, request, company_id):
        return Response(
            s.EquipmentCategoriesSerializer(queries.categories(self.company, self.membership)).data
        )

    @extend_schema(
        request=s.CategoryInputSerializer,
        responses={201: s.EquipmentCategoriesSerializer},
        operation_id="lifecycle_equipment_category_add",
    )
    def post(self, request, company_id):
        serializer = s.CategoryInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not data.get("suggestion") and not (data.get("name") or "").strip():
            raise ValidationError({"name": [_("Give the category a name.")]})
        services.add_category(
            self.company,
            by=self.membership,
            suggestion=data.get("suggestion") or "",
            name=(data.get("name") or "").strip(),
            kind=data.get("kind") or AssetCategory.Kind.LOW_VALUE,
            icon=data.get("icon") or "",
        )
        return Response(
            s.EquipmentCategoriesSerializer(queries.categories(self.company, self.membership)).data,
            status=status.HTTP_201_CREATED,
        )


class IssueView(EquipmentView):
    @extend_schema(
        request={
            "multipart/form-data": s.IssueInputSerializer,
            "application/json": s.IssueInputSerializer,
        },
        responses=s.EquipmentHolderSerializer,
        operation_id="lifecycle_equipment_issue",
    )
    def post(self, request, company_id):
        serializer = s.IssueInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        person = self.person(data["person_id"], statuses=(Membership.Status.APPROVED,))
        wanted = set(data["asset_ids"])
        stock = list(
            queries.stock_rows(self.company, self.membership, status="stock")
            .filter(pk__in=wanted)
            .select_related("category", "company")
        )
        if len(stock) != len(wanted):
            raise ValidationError(
                {
                    "asset_ids": [
                        _("Pick things in stock in your branches: one was given meanwhile.")
                    ]
                }
            )
        services.issue_many(
            self.company,
            by=self.membership,
            person=person,
            items=stock,
            on=data.get("on"),
            condition=data.get("condition") or "",
            note=data.get("note") or "",
            photo=data.get("photo"),
        )
        return Response(self.holder(person))


class ReturnView(EquipmentView):
    @extend_schema(
        request={
            "multipart/form-data": s.ReturnInputSerializer,
            "application/json": s.ReturnInputSerializer,
        },
        responses=s.EquipmentHolderSerializer,
        operation_id="lifecycle_equipment_return",
    )
    def post(self, request, company_id, pk):
        assignment = self.handout(pk)
        serializer = s.ReturnInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        services.give_back(
            assignment,
            by=self.membership,
            outcome=data.get("outcome") or services.RETURNED,
            on=data.get("on"),
            condition=data.get("condition") or "",
            note=data.get("note") or "",
            photo=data.get("photo"),
            write_off=data.get("write_off", False),
            deduction=data.get("deduction"),
            reason=data.get("reason") or "",
        )
        return Response(self.holder(assignment.membership))


class DeductionView(EquipmentView):
    @extend_schema(
        request=s.DeductionInputSerializer,
        responses=s.EquipmentHolderSerializer,
        operation_id="lifecycle_equipment_deduction",
    )
    def post(self, request, company_id, pk):
        assignment = self.handout(pk)
        serializer = s.DeductionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.propose_deduction(
            assignment,
            by=self.membership,
            amount=serializer.validated_data["amount"],
            reason=serializer.validated_data.get("reason") or "",
        )
        return Response(self.holder(assignment.membership))


class PersonView(EquipmentView):
    """Person 360's Equipment tab: what they hold, and what they were given before."""

    @extend_schema(
        responses=s.EquipmentPersonPageSerializer, operation_id="lifecycle_equipment_person"
    )
    def get(self, request, company_id, member_id):
        member = self.person(member_id)
        return Response(
            s.EquipmentPersonPageSerializer(
                {
                    "today": hr_queries.today(self.company),
                    "holder": queries.holder(self.company, self.membership, member),
                    "history": queries.history(self.company, self.membership, member),
                    "can": queries.can(self.company, self.membership),
                }
            ).data
        )
