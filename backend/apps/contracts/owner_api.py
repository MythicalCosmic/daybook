"""Owner dashboard endpoints of business contracts (`contracts/…`).

    GET/PATCH   contracts/settings/                    reminder days (read / manage)
    GET         contracts/summary/?branch              counts for the chips, cost a month
    GET         contracts/options/                     categories, accounts, recurring payments
                                                       and parties for the form (manage)
    GET/POST    contracts/?kind&branch&status&ending&q the list (soonest date first) / add
    GET/PATCH/DELETE contracts/{id}/                   its page: files, dates, payments
    POST        contracts/{id}/renew/                  a new end date
    POST        contracts/{id}/terminate/              stopped early, on a day
    POST        contracts/{id}/keep-renewing/          the auto-renewal is wanted
    POST        contracts/{id}/stop-renewing/          notice given: it ends on its end date
    POST        contracts/{id}/files/                  a PDF or a picture (multipart)
    DELETE      contracts/files/{id}/

Reading needs `finance.view`; changing `finance.view` and `finance.manage`. Company- and
branch-scoped: a contract of a branch outside the caller's scope (or a company-wide one for a
caller without every branch) answers 404, like another company's. Every change is audited by
the services and bumps the `contracts` pulse key after commit.
"""

from django.db.models import Count, Q
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.console.base import OwnerAPIView
from apps.console.perms import holds
from apps.contracts import conf, providers, queries, services
from apps.contracts import serializers as s
from apps.contracts.models import BusinessContract, ContractFile
from apps.members.models import Membership

READ, MANAGE = providers.READ, providers.MANAGE
BRANCH_PARAM = OpenApiParameter("branch", int, description="One branch (in scope).")
LIST_PARAMS = [
    OpenApiParameter("kind", str, enum=BusinessContract.Kind.values),
    BRANCH_PARAM,
    OpenApiParameter(
        "status",
        str,
        description="One status, or `current` (draft, active and ending: the default) or `all`.",
    ),
    OpenApiParameter("ending", bool, description="Only what ends soon or needs a decision."),
    OpenApiParameter("q", str, description="Title, number or counterparty."),
]
CURRENT = (
    BusinessContract.Status.DRAFT,
    BusinessContract.Status.ACTIVE,
    BusinessContract.Status.ENDING,
)


class Scope:
    """Lookups inside the caller's company and branch scope."""

    def branches(self) -> list[int] | None:
        """The caller's branches, narrowed to `?branch=` when given (and allowed)."""
        asked = self.request.query_params.get("branch")
        allowed = self.branch_scope
        if not asked:
            return allowed
        try:
            branch = int(asked)
        except ValueError as exc:
            raise ValidationError({"branch": [_("Give a number.")]}) from exc
        if allowed is not None and branch not in allowed:
            raise NotFound
        return [branch]

    def contracts(self):
        return queries.scoped(self.company, branch_ids=self.branch_scope).select_related(
            *queries.RELATIONS
        )

    def contract(self, pk) -> BusinessContract:
        found = self.contracts().filter(pk=pk).first()
        if found is None:
            raise NotFound
        return found

    def today(self):
        return services.local_today(self.company)


class ContractsView(Scope, OwnerAPIView):
    """GET (finance.view) / POST (finance.view and finance.manage) `contracts/`."""

    perm = READ
    perms_by_action = {"post": MANAGE}
    parser_classes = [JSONParser]

    @extend_schema(parameters=LIST_PARAMS, responses=s.RowSerializer(many=True))
    def get(self, request, company_id):
        params = request.query_params
        rows = queries.scoped(self.company, branch_ids=self.branches()).select_related(
            *queries.RELATIONS
        )
        kind = params.get("kind")
        if kind:
            if kind not in BusinessContract.Kind.values:
                raise ValidationError({"kind": [_("Pick a kind from the list.")]})
            rows = rows.filter(kind=kind)
        wanted = params.get("status") or "current"
        if wanted == "current":
            rows = rows.filter(status__in=CURRENT)
        elif wanted != "all":
            if wanted not in BusinessContract.Status.values:
                raise ValidationError({"status": [_("Pick a status from the list.")]})
            rows = rows.filter(status=wanted)
        if q := (params.get("q") or "").strip():
            rows = rows.filter(
                Q(title__icontains=q) | Q(number__icontains=q) | Q(counterparty__name__icontains=q)
            )
        rows = list(rows.annotate(file_count=Count("files"))[:1000])
        today = self.today()
        settings = conf.get_settings(self.company)
        if params.get("ending") in ("1", "true"):
            rows = [row for row in rows if services.needs_attention(row, today, settings)]
        data = [s.row_of(row, today=today, settings=settings, files=row.file_count) for row in rows]
        far = today.replace(year=today.year + 100)
        data.sort(
            key=lambda row: (
                row["status"] not in ("ending", "active", "draft"),
                row["key_day"] or far,
                row["title"],
            )
        )
        return Response(s.RowSerializer(data, many=True).data)

    @extend_schema(request=s.ContractWriteSerializer, responses={201: s.DetailSerializer})
    def post(self, request, company_id):
        serializer = s.ContractWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fields, money = self.fields(serializer.validated_data)
        if not fields.get("title"):
            raise ValidationError({"title": [_("Give the contract a name.")]})
        if self.branch_scope is not None and fields.get("branch") is None:
            raise ValidationError({"branch": [_("Pick the branch it is for.")]})
        contract = services.create_contract(self.company, by=self.membership, money=money, **fields)
        return Response(self.out(contract), status=status.HTTP_201_CREATED)

    # Input --------------------------------------------------------------------------------------

    def fields(self, data: dict) -> tuple[dict, services.RuleChoice | None]:
        fields = dict(data)
        category = fields.pop("category", None)
        account = fields.pop("account", None)
        link = fields.pop("link_rule", None)
        if "branch" in fields:
            fields["branch"] = self.pick_branch(fields["branch"])
        if "counterparty" in fields:
            fields["counterparty"] = self.pick_party(fields["counterparty"])
        if "responsible" in fields:
            fields["responsible"] = self.pick_person(fields["responsible"])
        money = None
        if category is not None or account is not None or link is not None:
            money = services.RuleChoice(
                category=self.pick_category(category),
                account=self.pick_account(account),
                rule=self.pick_rule(link),
            )
        return fields, money

    def pick_branch(self, pk):
        if pk is None:
            return None
        found = self.company.branches.filter(pk=pk).first()
        scope = self.branch_scope
        if found is None or (scope is not None and found.pk not in scope):
            raise ValidationError({"branch": [_("Pick a branch you work with.")]})
        return found

    def pick_party(self, pk):
        from apps.finance.models import Counterparty

        if pk is None:
            return None
        found = Counterparty.objects.for_company(self.company).filter(pk=pk).first()
        if found is None:
            raise ValidationError({"counterparty": [_("Pick a counterparty of this company.")]})
        return found

    def pick_person(self, pk) -> Membership | None:
        if pk is None:
            return None
        found = Membership.objects.for_company(self.company).filter(pk=pk).first()
        if found is None:
            raise ValidationError({"responsible": [_("Pick someone of this company.")]})
        return found

    def pick_category(self, pk):
        from apps.finance.models import Category

        if pk is None:
            return None
        found = (
            Category.objects.for_company(self.company)
            .filter(pk=pk, kind=Category.Kind.EXPENSE, is_active=True)
            .first()
        )
        if found is None:
            raise ValidationError({"category": [_("Pick an expense category.")]})
        return found

    def pick_account(self, pk):
        from apps.finance import access

        if pk is None:
            return None
        found = access.visible_accounts(self.membership).filter(pk=pk, is_active=True).first()
        if found is None:
            raise ValidationError({"account": [_("Pick one of your accounts.")]})
        return found

    def pick_rule(self, pk):
        from apps.finance import recurring

        if pk is None:
            return None
        found = (
            recurring.visible_rules(self.company, branch_ids=self.branch_scope)
            .filter(pk=pk, kind="expense")
            .first()
        )
        if found is None:
            raise ValidationError({"link_rule": [_("Pick one of your recurring payments.")]})
        return found

    def out(self, contract: BusinessContract) -> dict:
        contract = self.contract(contract.pk)
        data = s.detail_of(
            contract,
            user=self.request.user,
            today=self.today(),
            settings=conf.get_settings(self.company),
            branch_ids=self.branch_scope,
            can_manage=holds(self.membership, MANAGE),
        )
        return s.DetailSerializer(data).data


class ContractView(ContractsView):
    """GET (read) / PATCH / DELETE (manage) `contracts/{id}/`."""

    perm = READ
    perms_by_action = {"patch": MANAGE, "delete": MANAGE}
    http_method_names = ["get", "patch", "delete"]

    @extend_schema(responses=s.DetailSerializer)
    def get(self, request, company_id, contract_id):
        return Response(self.out(self.contract(contract_id)))

    @extend_schema(request=s.ContractWriteSerializer, responses=s.DetailSerializer)
    def patch(self, request, company_id, contract_id):
        contract = self.contract(contract_id)
        serializer = s.ContractWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields, money = self.fields(serializer.validated_data)
        if "branch" in fields and fields["branch"] is None and self.branch_scope is not None:
            raise ValidationError({"branch": [_("Pick the branch it is for.")]})
        contract = services.update_contract(contract, by=self.membership, money=money, **fields)
        return Response(self.out(contract))

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, contract_id):
        services.delete_contract(self.contract(contract_id), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RenewView(ContractsView):
    perm = MANAGE
    perms_by_action = {}
    http_method_names = ["post"]

    @extend_schema(request=s.RenewSerializer, responses=s.DetailSerializer)
    def post(self, request, company_id, contract_id):
        contract = self.contract(contract_id)
        serializer = s.RenewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contract = services.renew(
            contract, by=self.membership, ends_on=serializer.validated_data["ends_on"]
        )
        return Response(self.out(contract))


class TerminateView(ContractsView):
    perm = MANAGE
    perms_by_action = {}
    http_method_names = ["post"]

    @extend_schema(request=s.TerminateSerializer, responses=s.DetailSerializer)
    def post(self, request, company_id, contract_id):
        contract = self.contract(contract_id)
        serializer = s.TerminateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        contract = services.terminate(
            contract, by=self.membership, on=data["on"], reason=data.get("reason", "")
        )
        return Response(self.out(contract))


class KeepRenewingView(ContractsView):
    perm = MANAGE
    perms_by_action = {}
    http_method_names = ["post"]

    @extend_schema(request=None, responses=s.DetailSerializer)
    def post(self, request, company_id, contract_id):
        contract = services.confirm_renewal(self.contract(contract_id), by=self.membership)
        return Response(self.out(contract))


class StopRenewingView(ContractsView):
    perm = MANAGE
    perms_by_action = {}
    http_method_names = ["post"]

    @extend_schema(request=None, responses=s.DetailSerializer)
    def post(self, request, company_id, contract_id):
        contract = services.stop_renewal(self.contract(contract_id), by=self.membership)
        return Response(self.out(contract))


class FilesView(ContractsView):
    perm = MANAGE
    perms_by_action = {}
    http_method_names = ["post"]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=s.FileUploadSerializer, responses={201: s.DetailSerializer})
    def post(self, request, company_id, contract_id):
        contract = self.contract(contract_id)
        serializer = s.FileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        services.add_file(
            contract,
            by=self.membership,
            file=data["file"],
            kind=data.get("kind", ""),
            label=data.get("label", ""),
        )
        return Response(self.out(contract), status=status.HTTP_201_CREATED)


class FileView(Scope, OwnerAPIView):
    perm = MANAGE
    http_method_names = ["delete"]

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, file_id):
        row = (
            ContractFile.objects.for_company(self.company)
            .filter(pk=file_id)
            .select_related("contract")
            .first()
        )
        if row is None:
            raise NotFound
        self.contract(row.contract_id)  # in the caller's branches
        services.remove_file(row, by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SummaryView(Scope, OwnerAPIView):
    perm = READ

    @extend_schema(parameters=[BRANCH_PARAM], responses=s.SummarySerializer)
    def get(self, request, company_id):
        data = queries.summary(self.company, branch_ids=self.branches(), today=self.today())
        return Response(s.SummarySerializer(data).data)


class SettingsView(Scope, OwnerAPIView):
    perm = READ
    perms_by_action = {"patch": MANAGE}

    def out(self):
        row = conf.get_settings(self.company)
        return {"remind_days": row.remind_days, "notice_remind_days": row.notice_remind_days}

    @extend_schema(responses=s.SettingsSerializer)
    def get(self, request, company_id):
        return Response(s.SettingsSerializer(self.out()).data)

    @extend_schema(request=s.SettingsSerializer, responses=s.SettingsSerializer)
    def patch(self, request, company_id):
        serializer = s.SettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_settings(self.company, by=self.membership, **serializer.validated_data)
        return Response(s.SettingsSerializer(self.out()).data)


class OptionsView(Scope, OwnerAPIView):
    """What the form picks from: expense categories, accounts in scope, recurring payments no
    contract has yet, and the party directory."""

    perm = MANAGE

    @extend_schema(responses=s.OptionsSerializer)
    def get(self, request, company_id):
        from apps.finance import access, recurring
        from apps.finance.models import Category, Counterparty

        finance_on = self.company.has_feature("finance")
        categories = accounts = rules = []
        if finance_on:
            categories = [
                {"id": row.pk, "name": row.name, "system_code": row.system_code}
                for row in Category.objects.for_company(self.company)
                .filter(kind=Category.Kind.EXPENSE, is_active=True)
                .order_by("parent_id", "name")
            ]
            accounts = [
                {"id": row.pk, "name": row.name, "currency": row.currency}
                for row in access.visible_accounts(self.membership)
                .filter(is_active=True)
                .order_by("name")
            ]
            rules = [
                {
                    "id": row.pk,
                    "name": row.name,
                    "amount": row.amount,
                    "currency": row.currency,
                    "frequency": row.frequency,
                    "counterparty": row.counterparty_id,
                    "branch": row.branch_id,
                }
                for row in recurring.visible_rules(self.company, branch_ids=self.branch_scope)
                .filter(is_active=True, kind="expense", business_contracts__isnull=True)
                .order_by("name")
            ]
        parties = [
            {"id": row.pk, "name": row.name, "kind": row.kind}
            for row in Counterparty.objects.for_company(self.company)
            .filter(is_active=True)
            .order_by("name")[:1000]
        ]
        return Response(
            s.OptionsSerializer(
                {
                    "finance": finance_on,
                    "base_currency": self.company.base_currency,
                    "categories": categories,
                    "accounts": accounts,
                    "rules": rules,
                    "parties": parties,
                }
            ).data
        )
