"""Owner dashboard endpoints of the finance ledger, mounted under
`/api/v1/owner/companies/<id>/finance/` (docs/PLAN-OWNER.md §4.7, the rows of Package D).

Thin views over `services` (writes, audited there) and `queries` (reads). Every endpoint is
company-scoped and permission-checked by `apps.console.base`, answers 404 while the finance
module is off, applies the caller's branch scope (§2.6), returns money as strings and bumps the
`finance.ledger` pulse key after a write.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, F, Prefetch, Q, Sum, prefetch_related_objects
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    inline_serializer,
)
from rest_framework import exceptions, mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.companies.models import Branch
from apps.console import pulse
from apps.console.base import AllOf, AnyOf, OwnerAPIView, OwnerViewSet, RangeMixin
from apps.core.api import Pagination
from apps.core.exceptions import DomainError
from apps.core.money import Currency, quantize
from apps.finance import access, cbu, conf, filters, queries, services
from apps.finance import owner_serializers as out
from apps.finance.models import (
    Category,
    CompanyRate,
    Counterparty,
    Debt,
    ExchangeRate,
    MoneyAccount,
    Receipt,
    Transaction,
    Transfer,
)
from apps.members.models import Membership
from apps.members.permissions import Perm

VIEW = Perm.FINANCE_VIEW
RECORD = Perm.FINANCE_RECORD
MANAGE = Perm.FINANCE_MANAGE
APPROVE = Perm.FINANCE_APPROVE
VIEW_OR_RECORD = AnyOf(Perm.FINANCE_VIEW, Perm.FINANCE_RECORD)
# Debts are only visible with finance.view, so writing one needs both (a recorder who can't see
# debts would make one and get it back as "not found").
VIEW_AND_RECORD = AllOf(Perm.FINANCE_VIEW, Perm.FINANCE_RECORD)
VIEW_AND_MANAGE = AllOf(Perm.FINANCE_VIEW, Perm.FINANCE_MANAGE)
LEDGER = "finance.ledger"
OVERDUE = "finance.overdue"
OVERVIEW_TTL = 60
TRANSACTION_RELATIONS = (
    "account",
    "category__parent",
    "counterparty",
    "membership",
    "branch",
    "project",
    "debt",
    "created_by",
    "approved_by",
    "voided_by",
)
TRANSACTION_ORDERING = {
    "occurred_on": ("occurred_on", "pk"),
    "-occurred_on": ("-occurred_on", "-pk"),
    "amount": ("base_amount", "pk"),
    "-amount": ("-base_amount", "-pk"),
    "created_at": ("created_at", "pk"),
    "-created_at": ("-created_at", "-pk"),
}


def money(value) -> str | None:
    return str(quantize(value)) if value is not None else None


class FinanceMixin:
    """The finance module must be on; the shared helpers of every finance view."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not self.company.has_feature("finance"):
            raise exceptions.NotFound(_("The finance module is off for this company."))

    @property
    def today(self):
        return queries.local_today(self.company)

    def context(self, **extra) -> dict:
        settings_row = conf.get_settings(self.company)
        return {
            "request": self.request,
            "membership": self.membership,
            "company": self.company,
            "today": self.today,
            "locked_until": settings_row.locked_until,
            **extra,
        }

    def changed(self, *keys: str) -> None:
        self.bump(LEDGER, *keys)

    def account(self, pk, queryset=None) -> MoneyAccount:
        rows = queryset if queryset is not None else access.visible_accounts(self.membership)
        found = rows.filter(pk=pk).first() if pk is not None else None
        if found is None:
            raise exceptions.ValidationError({"account": [_("Pick one of your accounts.")]})
        return found

    def category(self, pk) -> Category | None:
        if pk is None:
            return None
        found = Category.objects.filter(company=self.company, pk=pk).first()
        if found is None:
            raise exceptions.ValidationError({"category": [_("Pick a category.")]})
        return found

    def party(self, pk) -> Counterparty | None:
        if pk is None:
            return None
        found = Counterparty.objects.filter(company=self.company, pk=pk).first()
        if found is None:
            raise exceptions.ValidationError({"counterparty": [_("Pick a counterparty.")]})
        return found

    def member(self, pk, field: str = "member") -> Membership | None:
        if pk is None:
            return None
        found = Membership.objects.filter(company=self.company, pk=pk).first()
        if found is None:
            raise exceptions.ValidationError({field: [_("Pick a person of the company.")]})
        return found

    def branch(self, pk) -> Branch | None:
        if pk is None:
            return None
        member_scope = self.branch_scope
        found = Branch.objects.filter(company=self.company, pk=pk).first()
        if found is None or (member_scope is not None and found.pk not in member_scope):
            raise exceptions.ValidationError({"branch": [_("Pick one of your branches.")]})
        return found

    def write_branch(self, pk, *, default: bool = True) -> Branch | None:
        """The branch of an account or debt someone makes or moves (§2.6).

        A member limited to some branches can't leave a row without one: it would vanish from
        their own view (rows with no branch are for people who see every branch). With `default`
        (a new row) the only branch they have is taken; otherwise they pick one.
        """
        found = self.branch(pk)
        member_scope = self.branch_scope
        if found is not None or member_scope is None:
            return found
        if default and len(member_scope) == 1:
            return Branch.objects.get(company=self.company, pk=member_scope[0])
        raise exceptions.ValidationError({"branch": [_("Pick one of your branches.")]})

    def project(self, pk):
        if pk is None:
            return None
        from apps.projects.models import Project

        found = Project.objects.filter(company=self.company, pk=pk).first()
        if found is None:
            raise exceptions.ValidationError({"project": [_("Pick a project.")]})
        return found

    def not_future(self, day, field: str):
        """Money is booked on the day it moved: a later day would put it in today's balances
        while the reports for today leave it out."""
        if day is not None and day > self.today:
            raise exceptions.ValidationError({field: [_("Pick today or an earlier day.")]})
        return day

    def wanted_branches(self) -> list[int] | None:
        """The caller's scope narrowed to `?branch=` (§4: intersected with the scope)."""
        return access.branch_filter(
            self.branch_scope, filters.ints(self.request.query_params, "branch")
        )


def domain(call):
    """Run a service call. A broken rule (`DomainError`) becomes a 400 with its message in
    `apps.core.api.exception_handler`, so the dashboard shows it as a toast."""
    return call()


def refuse_foreign(row) -> None:
    """Entries, transfers and debts another module booked (a shift's sales, a payslip) are
    corrected in that module: voiding or cancelling them here would leave it out of step."""
    label = out.foreign_source(row)
    if label is not None:
        message = _("This entry comes from %(source)s: correct it there.")
        raise DomainError(message % {"source": label})


# Overview and options -------------------------------------------------------------------------


class OverviewView(FinanceMixin, OwnerAPIView):
    """Cash now, this month against last month, money owed both ways, what falls due within a
    week, entries waiting for approval, the top expenses and the rate (cached 60 s)."""

    perm = VIEW

    @extend_schema(
        responses=inline_serializer(
            "FinanceOverview",
            {
                "currency": serializers.CharField(),
                "today": serializers.DateField(),
                "cash": serializers.DictField(),
                "month": serializers.DictField(),
                "receivable": serializers.DictField(),
                "payable": serializers.DictField(),
                "due_soon": out.DebtSerializer(many=True),
                "pending": serializers.DictField(),
                "top_expenses": serializers.ListField(child=serializers.DictField()),
                "negative_accounts": serializers.ListField(child=serializers.DictField()),
                "rate": serializers.DictField(),
                "has_ledger": serializers.BooleanField(),
                "locked_until": serializers.DateField(allow_null=True),
            },
        )
    )
    def get(self, request, company_id):
        version = pulse.versions(self.company.pk, [LEDGER])[LEDGER]
        member_scope = self.branch_scope
        masked = not access.sees_salary_detail(self.membership)
        # What the member may see is part of the key: a role or branch change shows at once.
        seen = "all" if member_scope is None else ".".join(map(str, member_scope)) or "none"
        key = (
            f"finance:overview:{self.membership.pk}:{version}:{self.today.isoformat()}"
            f":{seen}:{int(masked)}"
        )
        cached = cache.get(key)
        if cached is not None:
            return Response(cached)
        data = queries.overview(
            self.company, branch_ids=member_scope, today=self.today, mask_sensitive=masked
        )
        payload = _jsonable(
            {
                **data,
                "due_soon": out.DebtSerializer(
                    data["due_soon"], many=True, context=self.context()
                ).data,
                "has_ledger": queries.has_ledger_rows(self.company),
                "locked_until": conf.get_settings(self.company).locked_until,
            }
        )
        cache.set(key, payload, OVERVIEW_TTL)
        return Response(payload)


class OptionsView(FinanceMixin, OwnerAPIView):
    """Everything a finance form picks from, in one call: the accounts the caller may record
    on, transfer targets, people, branches, projects, the base currency, the receipt threshold
    and the period lock."""

    perm = VIEW_OR_RECORD

    @extend_schema(
        responses=inline_serializer(
            "FinanceOptions",
            {
                "base_currency": serializers.CharField(),
                "accounts": out.FinanceAccountRefSerializer(many=True),
                "transfer_targets": out.FinanceAccountRefSerializer(many=True),
                "members": out.FinanceRefSerializer(many=True),
                "branches": out.FinanceBranchRefSerializer(many=True),
                "projects": out.FinanceRefSerializer(many=True),
                "receipt_required_over": serializers.CharField(allow_null=True),
                "locked_until": serializers.DateField(allow_null=True),
                "today": serializers.DateField(),
                "rate": serializers.DictField(),
            },
        )
    )
    def get(self, request, company_id):
        member = self.membership
        settings_row = conf.get_settings(self.company)
        accounts = (
            access.recordable_accounts(member).select_related("branch").order_by("order", "name")
        )
        targets = access.transfer_targets(member).order_by("order", "name")
        people = Membership.objects.filter(
            company=self.company, status=Membership.Status.APPROVED
        ).select_related("position")
        member_scope = self.branch_scope
        if member_scope is not None:
            people = people.filter(Q(branches__in=member_scope) | Q(pk=member.pk)).distinct()
        branches = Branch.objects.filter(company=self.company, is_active=True).order_by(
            "order", "pk"
        )
        if member_scope is not None:
            branches = branches.filter(pk__in=member_scope)
        from apps.projects.models import Project

        projects = Project.objects.filter(company=self.company, archived_at__isnull=True).order_by(
            "name"
        )
        value = queries.valuation(self.company, self.today)
        return Response(
            {
                "base_currency": self.company.base_currency,
                "accounts": [
                    {**out.account_ref(account), "branch_id": account.branch_id}
                    for account in accounts
                ],
                "transfer_targets": [out.account_ref(account) for account in targets],
                "members": [
                    {"id": person.pk, "name": str(person), "position": str(person.position or "")}
                    for person in people.order_by("first_name", "last_name")
                ],
                "branches": [out.branch_ref(branch) for branch in branches],
                "projects": [{"id": project.pk, "name": project.name} for project in projects],
                "receipt_required_over": money(settings_row.receipt_required_over),
                "locked_until": settings_row.locked_until,
                "today": self.today,
                "rate": {
                    "rate": str(value.rate) if value.rate is not None else None,
                    "stale": value.stale,
                    "source": value.source,
                },
            }
        )


# Accounts -------------------------------------------------------------------------------------


class AccountViewSet(FinanceMixin, OwnerViewSet):
    """Money accounts: cash desks, banks, cards, wallets, terminal clearing, safes and money
    people hold."""

    perm = VIEW_OR_RECORD
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "archive": MANAGE,
        "reopen": MANAGE,
    }
    serializer_class = out.AccountSerializer
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MoneyAccount.objects.none()
        return (
            access.visible_accounts(self.membership)
            .select_related("branch", "holder")
            .prefetch_related("operators")
            .order_by("-is_active", "order", "name")
        )

    def _figures(self, accounts) -> dict:
        value = queries.valuation(self.company, self.today)
        return {
            "figures": queries.account_figures(list(accounts), self.today, value),
            "recordable": set(
                access.recordable_accounts(self.membership).values_list("pk", flat=True)
            ),
        }

    @extend_schema(
        parameters=[OpenApiParameter("archived", bool, description="Include archived accounts.")],
        responses=inline_serializer(
            "FinanceAccounts",
            {
                "accounts": out.AccountSerializer(many=True),
                "totals": serializers.DictField(),
                "rate": serializers.DictField(),
            },
        ),
    )
    def list(self, request, company_id):
        accounts = self.get_queryset()
        if filters.boolean(request.query_params, "archived") is not True:
            accounts = accounts.filter(is_active=True)
        accounts = list(accounts)
        value = queries.valuation(self.company, self.today)
        context = self.context(**self._figures(accounts))
        by_currency: dict[str, object] = {}
        total = quantize(0)
        complete = True
        for account in accounts:
            if not account.is_active:
                continue
            by_currency[account.currency] = (
                by_currency.get(account.currency, quantize(0)) + account.balance
            )
            base = value.to_base(account.balance, account.currency)
            if base is None:
                complete = False
            else:
                total += base
        return Response(
            {
                "accounts": out.AccountSerializer(accounts, many=True, context=context).data,
                "totals": {
                    "base": money(total),
                    "complete": complete,
                    "by_currency": [
                        {
                            "currency": currency,
                            "amount": money(amount),
                            "base": money(value.to_base(amount, currency)),
                        }
                        for currency, amount in sorted(by_currency.items())
                    ],
                },
                "rate": {
                    "rate": str(value.rate) if value.rate is not None else None,
                    "stale": value.stale,
                    "source": value.source,
                    "date": value.day,
                },
            }
        )

    def retrieve(self, request, company_id, pk=None):
        account = self.get_object()
        return Response(
            out.AccountSerializer(account, context=self.context(**self._figures([account]))).data
        )

    @extend_schema(request=out.AccountWriteSerializer, responses={201: out.AccountSerializer})
    def create(self, request, company_id):
        data = self._valid(out.AccountWriteSerializer)
        holder = self.member(data.get("holder"), "holder")
        branch = self.write_branch(data.get("branch"))
        operators = [self.member(pk, "operators") for pk in data.get("operators", [])]
        self.not_future(data.get("opening_on"), "opening_on")
        opening = data.get("opening_balance")
        if opening is not None and opening < 0:
            # A card or account that starts in the red can only hold that balance with an
            # overdraft allowed.
            data["allow_negative"] = True

        def make():
            with transaction.atomic():
                account = services.create_account(
                    self.company,
                    by=self.membership,
                    kind=data["kind"],
                    name=data["name"],
                    currency=data["currency"],
                    branch=branch,
                    holder=holder,
                )
                extra = {
                    key: data[key]
                    for key in ("bank_name", "number_last4", "allow_negative", "color", "order")
                    if key in data
                }
                if operators:
                    extra["operators"] = operators
                if extra:
                    account = services.update_account(account, by=self.membership, **extra)
                if opening:
                    services.record_entry(
                        self.company,
                        by=self.membership,
                        kind=Transaction.Kind.OPENING,
                        amount=abs(opening),
                        direction="in" if opening > 0 else "out",
                        occurred_on=data.get("opening_on") or self.today,
                        account=account,
                        description=_("Opening balance"),
                    )
                return account

        account = domain(make)
        self.changed()
        account = self.get_queryset().get(pk=account.pk)
        return Response(
            out.AccountSerializer(account, context=self.context(**self._figures([account]))).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=out.AccountUpdateSerializer, responses=out.AccountSerializer)
    def partial_update(self, request, company_id, pk=None):
        account = self.get_object()
        data = self._valid(out.AccountUpdateSerializer)
        if "branch" in data:
            data["branch"] = self.write_branch(data["branch"], default=False)
        if "operators" in data:
            data["operators"] = [self.member(pk, "operators") for pk in data["operators"]]
        domain(lambda: services.update_account(account, by=self.membership, **data))
        self.changed()
        return self.retrieve(request, company_id, pk)

    @extend_schema(request=None, responses=out.AccountSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, company_id, pk=None):
        account = self.get_object()
        domain(lambda: services.archive_account(account, by=self.membership))
        self.changed()
        return self.retrieve(request, company_id, pk)

    @extend_schema(request=None, responses=out.AccountSerializer)
    @action(detail=True, methods=["post"])
    def reopen(self, request, company_id, pk=None):
        account = self.get_object()
        domain(lambda: services.reopen_account(account, by=self.membership))
        self.changed()
        return self.retrieve(request, company_id, pk)

    @extend_schema(
        parameters=[OpenApiParameter("from", str), OpenApiParameter("to", str)],
        responses=inline_serializer(
            "FinanceStatement",
            {
                "account": out.AccountSerializer(),
                "from": serializers.DateField(),
                "to": serializers.DateField(),
                "today": serializers.DateField(),
                "opening": serializers.CharField(),
                "closing": serializers.CharField(),
                "money_in": serializers.CharField(),
                "money_out": serializers.CharField(),
                "lines": serializers.ListField(child=serializers.DictField()),
                "pending": out.TransactionSerializer(many=True),
            },
        ),
    )
    @action(detail=True, methods=["get"])
    def statement(self, request, company_id, pk=None):
        """Rows with the running balance (finance.view, or someone who operates or holds it)."""
        account = self.get_object()
        start = filters.day(request.query_params, "from") or (self.today - timedelta(days=29))
        end = filters.day(request.query_params, "to") or self.today
        if end < start:
            raise exceptions.ValidationError({"to": [_("The last day can't be before the first.")]})
        data = queries.statement(account, start, end)
        context = self.context(**self._figures([account]))
        rows = [row for row, _balance in data["lines"]]
        serialized = out.TransactionSerializer(
            _with_receipts(rows), many=True, context=context
        ).data
        lines = [
            {**row, "running_balance": str(balance)}
            for row, (_txn, balance) in zip(serialized, data["lines"], strict=True)
        ]
        return Response(
            {
                "account": out.AccountSerializer(account, context=context).data,
                "from": start,
                "to": end,
                "today": self.today,
                "opening": money(data["opening"]),
                "closing": money(data["closing"]),
                "money_in": money(data["money_in"]),
                "money_out": money(data["money_out"]),
                "lines": lines,
                "pending": out.TransactionSerializer(
                    _with_receipts(data["pending"]), many=True, context=context
                ).data,
            }
        )

    def _valid(self, serializer_class) -> dict:
        serializer = serializer_class(
            data=self.request.data, partial=self.action == "partial_update"
        )
        serializer.is_valid(raise_exception=True)
        return dict(serializer.validated_data)


def _with_receipts(rows):
    """The rows with their receipts fetched in one query."""
    rows = list(rows)
    prefetch_related_objects(rows, Prefetch("receipts", queryset=Receipt.objects.order_by("pk")))
    return rows


# Categories -----------------------------------------------------------------------------------


class CategoryViewSet(FinanceMixin, OwnerViewSet):
    """The category tree (income and expense, two levels). System categories can be renamed,
    not deleted."""

    perm = VIEW_OR_RECORD
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "destroy": MANAGE,
        "merge": MANAGE,
        "move": MANAGE,
    }
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Category.objects.none()
        return access.visible_categories(self.membership)

    def get_object(self) -> Category:
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])

    def _tree(self) -> list[dict]:
        categories = list(self.get_queryset().order_by("kind", "order", "name", "pk"))
        entries = dict(
            Transaction.objects.filter(company=self.company, category__isnull=False)
            .values("category_id")
            .annotate(n=Count("pk"))
            .values_list("category_id", "n")
        )
        children: dict[int, list[dict]] = {}
        for category in categories:
            if category.parent_id is not None:
                children.setdefault(category.parent_id, []).append(
                    out.category_node(category, entries, [])
                )
        return [
            out.category_node(category, entries, children.get(category.pk, []))
            for category in categories
            if category.parent_id is None
        ]

    @extend_schema(responses=out.CategoryNodeSerializer(many=True))
    def list(self, request, company_id):
        return Response(self._tree())

    @extend_schema(request=out.CategoryWriteSerializer, responses={201: out.CategoryNodeSerializer})
    def create(self, request, company_id):
        serializer = out.CategoryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        parent = self.category(data.pop("parent", None))
        if data.get("is_sensitive") and not access.sees_salary_detail(self.membership):
            raise exceptions.PermissionDenied(
                _("Only people with payroll access mark salary categories.")
            )
        category = domain(
            lambda: services.create_category(
                self.company, by=self.membership, parent=parent, **data
            )
        )
        self.changed()
        return Response(out.category_node(category, {}, []), status=status.HTTP_201_CREATED)

    @extend_schema(request=out.CategoryUpdateSerializer, responses=out.CategoryNodeSerializer)
    def partial_update(self, request, company_id, pk=None):
        category = self.get_object()
        serializer = out.CategoryUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "is_sensitive" in data and not access.sees_salary_detail(self.membership):
            raise exceptions.PermissionDenied(
                _("Only people with payroll access mark salary categories.")
            )
        category = domain(lambda: services.update_category(category, by=self.membership, **data))
        self.changed()
        return Response(out.category_node(category, {}, []))

    @extend_schema(responses={204: None})
    def destroy(self, request, company_id, pk=None):
        category = self.get_object()
        domain(lambda: services.delete_category(category, by=self.membership))
        self.changed()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=out.CategoryMergeSerializer, responses=out.CategoryNodeSerializer(many=True)
    )
    @action(detail=True, methods=["post"])
    def merge(self, request, company_id, pk=None):
        category = self.get_object()
        serializer = out.CategoryMergeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        into = self.category(serializer.validated_data["into"])
        domain(lambda: services.merge_category(category, into=into, by=self.membership))
        self.changed()
        return Response(self._tree())

    @extend_schema(
        request=out.CategoryMoveSerializer, responses=out.CategoryNodeSerializer(many=True)
    )
    @action(detail=True, methods=["post"])
    def move(self, request, company_id, pk=None):
        category = self.get_object()
        serializer = out.CategoryMoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parent = self.category(serializer.validated_data["parent"])
        domain(
            lambda: services.move_category(
                category,
                by=self.membership,
                parent=parent,
                index=serializer.validated_data["index"],
            )
        )
        self.changed()
        return Response(self._tree())


# Counterparties -------------------------------------------------------------------------------


class CounterpartyViewSet(FinanceMixin, OwnerViewSet):
    """The party directory: customers, suppliers, the landlord, the tax office, with what they
    owe us and what we owe them."""

    perm = VIEW_OR_RECORD
    perms_by_action = {"retrieve": VIEW, "create": RECORD, "partial_update": RECORD}
    serializer_class = out.CounterpartySerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Counterparty.objects.none()
        return access.visible_counterparties(self.membership).select_related(
            "default_category__parent"
        )

    def get_object(self) -> Counterparty:
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str),
            OpenApiParameter("kind", str, description="customer, supplier, both, state, other"),
            OpenApiParameter("active", bool),
            OpenApiParameter("owes", str, description="us: they owe us; we: we owe them"),
            OpenApiParameter("ordering", str, description="name, -name, -created_at"),
        ],
        responses=out.CounterpartySerializer(many=True),
    )
    def list(self, request, company_id):
        params = request.query_params
        parties = self.get_queryset()
        if q := (params.get("q") or "").strip():
            parties = parties.filter(
                Q(name__icontains=q)
                | Q(phone__contains=q.replace(" ", ""))
                | Q(tin__startswith=q)
                | Q(contact_person__icontains=q)
            )
        if kinds := filters.choices(params, "kind", Counterparty.Kind.values):
            wanted = set(kinds)
            if "customer" in wanted or "supplier" in wanted:
                wanted.add("both")
            parties = parties.filter(kind__in=wanted)
        active = filters.boolean(params, "active")
        if active is not None:
            parties = parties.filter(is_active=active)
        owes = params.get("owes")
        if owes in ("us", "we"):
            direction = Debt.Direction.RECEIVABLE if owes == "us" else Debt.Direction.PAYABLE
            open_debts = access.visible_debts(self.membership).filter(
                status=Debt.Status.OPEN, direction=direction, counterparty__isnull=False
            )
            parties = parties.filter(pk__in=open_debts.values("counterparty_id"))
        ordering = {"name": ("name",), "-name": ("-name",), "-created_at": ("-created_at",)}.get(
            params.get("ordering") or "name", ("name",)
        )
        page = self.paginate_queryset(parties.order_by(*ordering, "pk"))
        context = self.context(balances=self._balances(page))
        return self.get_paginated_response(
            out.CounterpartySerializer(page, many=True, context=context).data
        )

    @extend_schema(
        responses=inline_serializer(
            "FinanceCounterpartyDetail",
            {
                "counterparty": out.CounterpartySerializer(),
                "totals": serializers.DictField(),
                "debts": out.DebtSerializer(many=True),
                "transactions": out.TransactionSerializer(many=True),
            },
        )
    )
    def _balances(self, parties) -> dict:
        """What each party owes and is owed, counting only debts of the member's branches
        (and none for a member without `finance.view`, who sees no debts at all)."""
        if not access.can_view(self.membership):
            return {}
        return queries.party_balances(list(parties), self.today, branch_ids=self.branch_scope)

    def retrieve(self, request, company_id, pk=None):
        party = self.get_object()
        context = self.context(balances=self._balances([party]))
        debts_ = (
            access.visible_debts(self.membership)
            .filter(counterparty=party)
            .exclude(status=Debt.Status.CANCELLED)
            .select_related("counterparty", "membership", "branch", "responsible", "company")
            .order_by("status", F("due_on").asc(nulls_last=True), "-issued_on")[:100]
        )
        rows = list(
            access.visible_transactions(self.membership)
            .filter(counterparty=party)
            .select_related(*TRANSACTION_RELATIONS)
            .order_by("-occurred_on", "-pk")[:100]
        )
        totals = queries.party_totals(party, branch_ids=self.branch_scope)
        return Response(
            {
                "counterparty": out.CounterpartySerializer(party, context=context).data,
                "totals": {key: money(value) for key, value in totals.items()},
                "debts": out.DebtSerializer(debts_, many=True, context=context).data,
                "transactions": out.TransactionSerializer(
                    _with_receipts(rows), many=True, context=context
                ).data,
            }
        )

    def _write_data(self, partial: bool) -> dict:
        serializer = out.CounterpartyWriteSerializer(data=self.request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "default_category" in data:
            data["default_category"] = self.category(data["default_category"])
        return data

    @extend_schema(
        request=out.CounterpartyWriteSerializer, responses={201: out.CounterpartySerializer}
    )
    def create(self, request, company_id):
        data = self._write_data(partial=False)
        if not data.get("name"):
            raise exceptions.ValidationError({"name": [_("Give the counterparty a name.")]})
        party = domain(
            lambda: services.create_counterparty(self.company, by=self.membership, **data)
        )
        self.changed()
        return Response(
            out.CounterpartySerializer(party, context=self.context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=out.CounterpartyWriteSerializer, responses=out.CounterpartySerializer)
    def partial_update(self, request, company_id, pk=None):
        party = self.get_object()
        data = self._write_data(partial=True)
        party = domain(lambda: services.update_counterparty(party, by=self.membership, **data))
        self.changed()
        context = self.context(balances=self._balances([party]))
        return Response(out.CounterpartySerializer(party, context=context).data)


# Transactions ---------------------------------------------------------------------------------


class TransactionPagination(Pagination):
    """A page of entries plus the sums of everything the filters match."""

    summary: dict | None = None

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data["summary"] = self.summary
        return response

    def get_paginated_response_schema(self, schema):
        schema = super().get_paginated_response_schema(schema)
        schema["properties"]["summary"] = {"type": "object"}
        return schema


class TransactionViewSet(FinanceMixin, OwnerViewSet):
    """The ledger: every income, expense, transfer row, debt row and exchange difference."""

    perm = VIEW_OR_RECORD
    perms_by_action = {
        "create": RECORD,
        "partial_update": RECORD,
        "void": MANAGE,
        "bulk": MANAGE,
        "approve": APPROVE,
        "reject": APPROVE,
        "receipts": RECORD,
        "remove_receipt": RECORD,
    }
    serializer_class = out.TransactionSerializer
    pagination_class = TransactionPagination
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Transaction.objects.none()
        return access.visible_transactions(self.membership).select_related(*TRANSACTION_RELATIONS)

    def get_object(self) -> Transaction:
        row = get_object_or_404(
            self.get_queryset().prefetch_related(
                Prefetch("receipts", Receipt.objects.order_by("pk"))
            ),
            pk=self.kwargs["pk"],
        )
        return row

    def _filtered(self):
        params = self.request.query_params
        parsed = filters.transaction_filters(params)
        parsed["mask_sensitive"] = not access.sees_salary_detail(self.membership)
        return queries.filter_transactions(self.get_queryset(), parsed)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name, str, many=name in filters.MULTI_INTS or name in ("kind", "status")
            )
            for name in queries.TRANSACTION_FILTERS
        ]
        + [
            OpenApiParameter(
                "ordering", str, description="occurred_on, amount, created_at (- for desc)"
            )
        ],
        responses=out.TransactionSerializer(many=True),
    )
    def list(self, request, company_id):
        rows = self._filtered()
        # The sums follow the filters: posted rows unless a status is asked for (the "Waiting"
        # view sums what waits), and transfers only when the list is narrowed to them (both legs,
        # so in = out); otherwise they would only move money between our own accounts.
        counted = rows
        if Transaction.Kind.TRANSFER not in filters.choices(
            request.query_params, "kind", Transaction.Kind.values
        ):
            counted = counted.exclude(kind=Transaction.Kind.TRANSFER)
        if not filters.choices(request.query_params, "status", Transaction.Status.values):
            counted = counted.filter(status=Transaction.Status.POSTED)
        sums = counted.aggregate(
            money_in=Sum("base_amount", filter=Q(base_amount__gt=0)),
            money_out=Sum("base_amount", filter=Q(base_amount__lt=0)),
        )
        money_in = quantize(sums["money_in"] or 0)
        money_out = quantize(-(sums["money_out"] or 0))
        self.paginator.summary = {
            "money_in": money(money_in),
            "money_out": money(money_out),
            "net": money(money_in - money_out),
            "currency": self.company.base_currency,
        }
        ordering = TRANSACTION_ORDERING.get(request.query_params.get("ordering") or "-occurred_on")
        if ordering is None:
            raise exceptions.ValidationError({"ordering": [_("Unknown ordering.")]})
        page = self.paginate_queryset(rows.order_by(*ordering))
        return self.get_paginated_response(
            out.TransactionSerializer(_with_receipts(page), many=True, context=self.context()).data
        )

    def retrieve(self, request, company_id, pk=None):
        return Response(out.TransactionSerializer(self.get_object(), context=self.context()).data)

    @extend_schema(
        request=out.TransactionCreateSerializer, responses={201: out.TransactionSerializer}
    )
    def create(self, request, company_id):
        serializer = out.TransactionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        self.not_future(data["occurred_on"], "occurred_on")
        kind = data["kind"]
        if kind in (Transaction.Kind.OWNER, Transaction.Kind.OPENING) and not access.can_manage(
            self.membership
        ):
            raise exceptions.PermissionDenied(
                _("Owner money and opening balances need finance.manage.")
            )
        account = self.account(data["account"], access.recordable_accounts(self.membership))
        receipts = list(
            Receipt.objects.filter(
                company=self.company,
                pk__in=data.get("receipt_ids", []),
                uploaded_by=self.membership.user,
                transaction__isnull=True,
            )
        )
        if len(receipts) != len(set(data.get("receipt_ids", []))):
            raise exceptions.ValidationError({"receipt_ids": [_("Upload the receipt again.")]})
        row = domain(
            lambda: services.record_entry(
                self.company,
                by=self.membership,
                kind=kind,
                direction=data["direction"],
                amount=data["amount"],
                occurred_on=data["occurred_on"],
                account=account,
                category=self.category(data.get("category")),
                counterparty=self.party(data.get("counterparty")),
                membership=self.member(data.get("member")),
                branch=self.branch(data.get("branch")),
                project=self.project(data.get("project")),
                description=data.get("description", ""),
                receipts=receipts,
                receipt_files=request.FILES.getlist("receipts"),
            )
        )
        self.changed()
        row = self.get_queryset().prefetch_related("receipts").get(pk=row.pk)
        return Response(
            out.TransactionSerializer(row, context=self.context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=out.TransactionUpdateSerializer, responses=out.TransactionSerializer)
    def partial_update(self, request, company_id, pk=None):
        row = self.get_object()
        if not self._may_edit(row):
            raise exceptions.PermissionDenied(
                _("Only finance managers change entries, or whoever made one within 24 hours.")
            )
        serializer = out.TransactionUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        self.not_future(data.get("occurred_on"), "occurred_on")
        changes = {}
        for key, value in data.items():
            match key:
                case "category":
                    changes["category"] = self.category(value)
                case "counterparty":
                    changes["counterparty"] = self.party(value)
                case "member":
                    changes["membership"] = self.member(value)
                case "branch":
                    changes["branch"] = self.write_branch(value, default=False)
                case "project":
                    changes["project"] = self.project(value)
                case "account":
                    changes["account"] = self.account(
                        value, access.recordable_accounts(self.membership)
                    )
                case _:
                    changes[key] = value
        domain(lambda: services.update_transaction(row, by=self.membership, **changes))
        self.changed(OVERDUE)
        return self.retrieve(request, company_id, pk)

    def _may_edit(self, row) -> bool:
        if access.can_manage(self.membership):
            return True
        return (
            row.created_by_id == self.membership.user_id
            and row.created_at >= timezone.now() - out.EDIT_WINDOW
        )

    @extend_schema(request=out.ReasonSerializer, responses=out.TransactionSerializer)
    @action(detail=True, methods=["post"])
    def void(self, request, company_id, pk=None):
        row = self.get_object()
        serializer = out.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refuse_foreign(row)
        domain(
            lambda: services.void_transaction(
                row, by=self.membership, reason=serializer.validated_data["reason"]
            )
        )
        self.changed(OVERDUE)
        return self.retrieve(request, company_id, pk)

    def _check_decision(self, row) -> None:
        """Entries waiting for approval that were recorded here are decided here; a claim's
        entry is decided with its claim, and nobody but an owner decides their own entry."""
        if row.status != Transaction.Status.PENDING:
            raise DomainError(_("This entry isn't waiting for approval."))
        if row.source_type:
            raise DomainError(
                _("This entry comes from %(source)s: decide it there.")
                % {"source": out.source_label(row)}
            )
        if row.created_by_id == self.membership.user_id and not access.is_owner(self.membership):
            raise exceptions.PermissionDenied(_("Someone else approves the entries you made."))

    @extend_schema(request=None, responses=out.TransactionSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, company_id, pk=None):
        """Post an entry that waits for approval: from now on it moves its account."""
        row = self.get_object()
        self._check_decision(row)
        domain(lambda: services.approve_transaction(row, by=self.membership))
        self.changed()
        return self.retrieve(request, company_id, pk)

    @extend_schema(request=out.ReasonSerializer, responses=out.TransactionSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, company_id, pk=None):
        """Turn down an entry that waits for approval, with the reason."""
        row = self.get_object()
        serializer = out.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self._check_decision(row)
        domain(
            lambda: services.reject_transaction(
                row, by=self.membership, reason=serializer.validated_data["reason"]
            )
        )
        self.changed()
        return self.retrieve(request, company_id, pk)

    @extend_schema(
        request=out.BulkSerializer,
        responses=inline_serializer(
            "FinanceBulkResults", {"results": out.BulkResultSerializer(many=True)}
        ),
    )
    @action(detail=False, methods=["post"])
    def bulk(self, request, company_id):
        serializer = out.BulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        rows = list(self.get_queryset().filter(pk__in=data["ids"]).order_by("pk"))
        missing = sorted(set(data["ids"]) - {row.pk for row in rows})
        payload = {"reason": data.get("reason", "")}
        if data["action"] == "categorize":
            payload["category"] = self.category(data.get("category"))
        refused = []
        if data["action"] == "void":
            for row in rows:
                if (label := out.foreign_source(row)) is not None:
                    error = _("This entry comes from %(source)s: correct it there.")
                    refused.append({"id": row.pk, "ok": False, "error": error % {"source": label}})
            refused_ids = {item["id"] for item in refused}
            rows = [row for row in rows if row.pk not in refused_ids]
        results = (
            domain(
                lambda: services.bulk_transactions(
                    rows, by=self.membership, action=data["action"], payload=payload
                )
            )
            if rows
            else []
        )
        results += refused
        results += [{"id": pk, "ok": False, "error": _("Not found.")} for pk in missing]
        self.changed(OVERDUE)
        return Response({"results": results})

    @extend_schema(
        request={"multipart/form-data": out.ReceiptUploadSerializer},
        responses={201: out.ReceiptSerializer},
    )
    @action(detail=True, methods=["post"], parser_classes=(MultiPartParser, FormParser))
    def receipts(self, request, company_id, pk=None):
        row = self.get_object()
        file = request.FILES.get("file")
        if file is None:
            raise exceptions.ValidationError({"file": [_("Attach a photo or a PDF.")]})
        receipt = domain(
            lambda: services.upload_receipt(self.company, by=self.membership, file=file, txn=row)
        )
        self.changed()
        return Response(
            out.ReceiptSerializer(receipt, context=self.context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(responses={204: None})
    @action(detail=True, methods=["delete"], url_path=r"receipts/(?P<receipt_id>\d+)")
    def remove_receipt(self, request, company_id, pk=None, receipt_id=None):
        row = self.get_object()
        receipt = get_object_or_404(Receipt, pk=receipt_id, transaction=row)
        if not (
            access.can_manage(self.membership) or receipt.uploaded_by_id == self.membership.user_id
        ):
            raise exceptions.PermissionDenied(
                _("Only finance managers remove someone else's receipt.")
            )
        domain(lambda: services.remove_receipt(receipt, by=self.membership))
        self.changed()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReceiptUploadView(FinanceMixin, OwnerAPIView):
    """Upload a receipt before recording its entry (quick add, AI reading); link it with the
    entry's `receipt_ids`."""

    perm = RECORD
    parser_classes = (MultiPartParser, FormParser)

    @extend_schema(
        request={"multipart/form-data": out.ReceiptUploadSerializer},
        responses={201: out.ReceiptSerializer},
    )
    def post(self, request, company_id):
        file = request.FILES.get("file")
        if file is None:
            raise exceptions.ValidationError({"file": [_("Attach a photo or a PDF.")]})
        receipt = domain(
            lambda: services.upload_receipt(self.company, by=self.membership, file=file)
        )
        return Response(
            out.ReceiptSerializer(receipt, context=self.context()).data,
            status=status.HTTP_201_CREATED,
        )


# Transfers ------------------------------------------------------------------------------------


class TransferViewSet(FinanceMixin, mixins.ListModelMixin, OwnerViewSet):
    """Money moved between the company's accounts, across currencies too."""

    perm = VIEW_OR_RECORD
    perms_by_action = {"create": RECORD, "void": MANAGE}
    serializer_class = out.TransferSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Transfer.objects.none()
        rows = access.visible_transfers(self.membership).select_related(
            "from_account", "to_account", "created_by"
        )
        params = self.request.query_params
        if start := filters.day(params, "from"):
            rows = rows.filter(occurred_on__gte=start)
        if end := filters.day(params, "to"):
            rows = rows.filter(occurred_on__lte=end)
        if accounts := filters.ints(params, "account"):
            rows = rows.filter(Q(from_account__in=accounts) | Q(to_account__in=accounts))
        return rows.order_by("-occurred_on", "-pk")

    def get_serializer_context(self):
        return self.context()

    @extend_schema(request=out.TransferCreateSerializer, responses={201: out.TransferSerializer})
    def create(self, request, company_id):
        serializer = out.TransferCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        self.not_future(data["occurred_on"], "occurred_on")
        source = self.account(data["from_account"], access.recordable_accounts(self.membership))
        target = self.account(data["to_account"], access.transfer_targets(self.membership))
        moved = domain(
            lambda: services.transfer(
                self.company,
                by=self.membership,
                from_account=source,
                to_account=target,
                amount_out=data["amount_out"],
                amount_in=data.get("amount_in"),
                rate=data.get("rate"),
                fee=data.get("fee") or 0,
                occurred_on=data["occurred_on"],
                description=data.get("description", ""),
            )
        )
        self.changed()
        moved = Transfer.objects.select_related("from_account", "to_account", "created_by").get(
            pk=moved.pk
        )
        return Response(
            out.TransferSerializer(moved, context=self.context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=out.ReasonSerializer, responses=out.TransferSerializer)
    @action(detail=True, methods=["post"])
    def void(self, request, company_id, pk=None):
        moved = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = out.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refuse_foreign(moved)
        domain(
            lambda: services.void_transfer(
                moved, by=self.membership, reason=serializer.validated_data["reason"]
            )
        )
        self.changed()
        moved.refresh_from_db()
        return Response(out.TransferSerializer(moved, context=self.context()).data)


# Debts ----------------------------------------------------------------------------------------


class DebtViewSet(FinanceMixin, OwnerViewSet):
    """Nasiya and qarz: money owed to us and money we owe, with payments, write-offs and
    instalment plans."""

    perm = VIEW
    perms_by_action = {
        "create": VIEW_AND_RECORD,
        "partial_update": VIEW_AND_RECORD,
        "payments": VIEW_AND_RECORD,
        "installments": VIEW_AND_RECORD,
        "write_off": VIEW_AND_MANAGE,
        "cancel": VIEW_AND_MANAGE,
    }
    serializer_class = out.DebtSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Debt.objects.none()
        return access.visible_debts(self.membership).select_related(
            "counterparty", "membership", "branch", "responsible", "company"
        )

    def get_object(self) -> Debt:
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])

    @extend_schema(
        parameters=[
            OpenApiParameter("direction", str, description="receivable or payable"),
            OpenApiParameter("status", str, many=True, description="open (default), paid, …, all"),
            OpenApiParameter("overdue", bool),
            OpenApiParameter("kind", str, many=True),
            OpenApiParameter("party", str, description='"counterparty:12" or "member:7"'),
            OpenApiParameter("q", str),
            OpenApiParameter("ordering", str, description="due_on, -outstanding, -issued_on"),
        ],
        responses=out.DebtSerializer(many=True),
    )
    def list(self, request, company_id):
        parsed = filters.debt_filters(request.query_params)
        rows = self.get_queryset()
        if parsed["direction"]:
            rows = rows.filter(direction=parsed["direction"])
        if "all" not in parsed["status"]:
            rows = rows.filter(status__in=parsed["status"])
        if parsed["kind"]:
            rows = rows.filter(kind__in=parsed["kind"])
        if parsed["overdue"]:
            rows = rows.filter(status=Debt.Status.OPEN, due_on__lt=self.today)
        if parsed["branch"]:
            rows = rows.filter(branch_id__in=parsed["branch"])
        if parsed["counterparty"]:
            rows = rows.filter(counterparty_id__in=parsed["counterparty"])
        if parsed["member"]:
            rows = rows.filter(membership_id__in=parsed["member"])
        if party := parsed["party"]:
            kind, _sep, pk = party.partition(":")
            if kind == "counterparty" and pk.isdigit():
                rows = rows.filter(counterparty_id=int(pk))
            elif kind == "member" and pk.isdigit():
                rows = rows.filter(membership_id=int(pk))
        if q := parsed["q"]:
            text = Q(counterparty__name__icontains=q) | Q(description__icontains=q)
            if access.sees_salary_detail(self.membership):
                text |= Q(membership__first_name__icontains=q) | Q(
                    membership__last_name__icontains=q
                )
            else:
                text = (text & ~Q(kind__in=Debt.SENSITIVE_KINDS)) | (
                    (Q(membership__first_name__icontains=q) | Q(membership__last_name__icontains=q))
                    & ~Q(kind__in=Debt.SENSITIVE_KINDS)
                )
            rows = rows.filter(text)
        ordering = {
            "due_on": (F("due_on").asc(nulls_last=True), "issued_on", "pk"),
            "-issued_on": ("-issued_on", "-pk"),
            "issued_on": ("issued_on", "pk"),
            "-amount": ("-amount", "-pk"),
        }.get(
            request.query_params.get("ordering") or "due_on",
            (F("due_on").asc(nulls_last=True), "issued_on", "pk"),
        )
        page = self.paginate_queryset(rows.order_by(*ordering))
        return self.get_paginated_response(
            out.DebtSerializer(page, many=True, context=self.context()).data
        )

    @extend_schema(
        responses=inline_serializer(
            "FinanceDebtSummary",
            {
                "receivable": serializers.DictField(),
                "payable": serializers.DictField(),
                "aging": serializers.DictField(),
            },
        )
    )
    @action(detail=False, methods=["get"])
    def summary(self, request, company_id):
        """Totals both ways (book value, overdue part, counts) and the aging of each side."""
        owed = queries.debt_totals(self.company, branch_ids=self.branch_scope, today=self.today)
        mask = not access.sees_salary_detail(self.membership)
        aging = {
            direction: queries.debts_aging(
                self.company,
                direction,
                branch_ids=self.branch_scope,
                today=self.today,
                mask_sensitive=mask,
            )["totals"]
            for direction in Debt.Direction.values
        }
        return Response(
            _jsonable(
                {
                    "receivable": owed[Debt.Direction.RECEIVABLE],
                    "payable": owed[Debt.Direction.PAYABLE],
                    "aging": aging,
                    "currency": self.company.base_currency,
                }
            )
        )

    @extend_schema(
        responses=inline_serializer(
            "FinanceDebtDetail",
            {
                "debt": out.DebtSerializer(),
                "installments": out.InstallmentSerializer(many=True),
                "payments": out.TransactionSerializer(many=True),
                "can_pay": serializers.BooleanField(),
                "can_write_off": serializers.BooleanField(),
                "can_cancel": serializers.BooleanField(),
            },
        )
    )
    def retrieve(self, request, company_id, pk=None):
        debt = self.get_object()
        return Response(self._detail(debt))

    def _detail(self, debt: Debt) -> dict:
        context = self.context()
        rows = list(
            Transaction.objects.filter(debt=debt)
            .select_related(*TRANSACTION_RELATIONS)
            .order_by("occurred_on", "pk")
        )
        masked = access.masks_debt(self.membership, debt)
        schedule = queries.installment_schedule(debt, self.today)
        is_open = debt.status == Debt.Status.OPEN and not debt.is_locked
        return _jsonable(
            {
                "debt": out.DebtSerializer(debt, context=context).data,
                "installments": schedule,
                "payments": out.TransactionSerializer(
                    _with_receipts(rows), many=True, context=context
                ).data
                if not masked
                else [],
                "can_pay": is_open and access.can_record(self.membership),
                "can_write_off": is_open and access.can_manage(self.membership),
                "can_cancel": debt.status != Debt.Status.CANCELLED
                and not debt.is_locked
                and out.foreign_source(debt) is None
                and access.can_manage(self.membership),
            }
        )

    @extend_schema(request=out.DebtCreateSerializer, responses={201: out.DebtSerializer})
    def create(self, request, company_id):
        serializer = out.DebtCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        self.not_future(data["issued_on"], "issued_on")
        mode = data["mode"]
        account = (
            self.account(data.get("account"), access.recordable_accounts(self.membership))
            if mode == "account"
            else None
        )
        category = self.category(data.get("category")) if mode == "category" else None
        if mode == "opening" and not access.can_manage(self.membership):
            raise exceptions.PermissionDenied(_("Opening debts need finance.manage."))
        debt = domain(
            lambda: services.open_debt(
                self.company,
                by=self.membership,
                direction=data["direction"],
                kind=data["kind"],
                amount=data["amount"],
                currency=data["currency"],
                issued_on=data["issued_on"],
                due_on=data.get("due_on"),
                counterparty=self.party(data.get("counterparty")),
                membership=self.member(data.get("member")),
                account=account,
                category=category,
                branch=self.write_branch(data.get("branch")),
                responsible=self.member(data.get("responsible"), "responsible"),
                description=data.get("description", ""),
                is_opening=mode == "opening",
            )
        )
        self.changed(OVERDUE)
        debt = self.get_queryset().get(pk=debt.pk)
        return Response(
            out.DebtSerializer(debt, context=self.context()).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=out.DebtUpdateSerializer, responses=out.DebtSerializer)
    def partial_update(self, request, company_id, pk=None):
        debt = self.get_object()
        serializer = out.DebtUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "responsible" in data:
            data["responsible"] = self.member(data["responsible"], "responsible")
        if "branch" in data:
            data["branch"] = self.write_branch(data["branch"], default=False)
        domain(lambda: services.update_debt(debt, by=self.membership, **data))
        self.changed(OVERDUE)
        return Response(out.DebtSerializer(self.get_object(), context=self.context()).data)

    @extend_schema(request=out.PaymentSerializer, responses=out.TransactionSerializer)
    @action(detail=True, methods=["post"])
    def payments(self, request, company_id, pk=None):
        debt = self.get_object()
        serializer = out.PaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        self.not_future(data["paid_on"], "paid_on")
        account = self.account(data["account"], access.recordable_accounts(self.membership))
        row = domain(
            lambda: services.pay_debt(
                debt,
                by=self.membership,
                amount=data["amount"],
                paid_on=data["paid_on"],
                account=account,
                debt_amount=data.get("debt_amount"),
            )
        )
        self.changed(OVERDUE)
        row = (
            Transaction.objects.select_related(*TRANSACTION_RELATIONS)
            .prefetch_related("receipts")
            .get(pk=row.pk)
        )
        return Response(
            out.TransactionSerializer(row, context=self.context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=out.WriteOffSerializer, responses=out.TransactionSerializer)
    @action(detail=True, methods=["post"], url_path="write-off")
    def write_off(self, request, company_id, pk=None):
        debt = self.get_object()
        serializer = out.WriteOffSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row = domain(
            lambda: services.write_off(
                debt, by=self.membership, reason=data["reason"], amount=data.get("amount")
            )
        )
        self.changed(OVERDUE)
        row = (
            Transaction.objects.select_related(*TRANSACTION_RELATIONS)
            .prefetch_related("receipts")
            .get(pk=row.pk)
        )
        return Response(
            out.TransactionSerializer(row, context=self.context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=out.ReasonSerializer, responses=out.DebtSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, company_id, pk=None):
        debt = self.get_object()
        serializer = out.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refuse_foreign(debt)
        domain(
            lambda: services.cancel_debt(
                debt, by=self.membership, reason=serializer.validated_data["reason"]
            )
        )
        self.changed(OVERDUE)
        return Response(out.DebtSerializer(self.get_object(), context=self.context()).data)

    @extend_schema(
        request=out.InstallmentsWriteSerializer, responses=out.InstallmentSerializer(many=True)
    )
    @action(detail=True, methods=["put"])
    def installments(self, request, company_id, pk=None):
        debt = self.get_object()
        serializer = out.InstallmentsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rows = [
            (item["due_on"], item["amount"]) for item in serializer.validated_data["installments"]
        ]
        domain(lambda: services.set_installments(debt, by=self.membership, rows=rows))
        self.changed(OVERDUE)
        debt.refresh_from_db()
        return Response(_jsonable(queries.installment_schedule(debt, self.today)))


# Rates ----------------------------------------------------------------------------------------


class RatesView(FinanceMixin, OwnerAPIView):
    """The dollar rate: today's in use (and whether it is stale), the Central Bank's last 60
    days and the company's own rates; POST sets the company's rate for a day."""

    perm = VIEW_OR_RECORD
    perms_by_action = {"post": MANAGE}

    @extend_schema(
        parameters=[OpenApiParameter("from", str), OpenApiParameter("to", str)],
        responses=inline_serializer(
            "FinanceRates",
            {
                "currency": serializers.CharField(),
                "current": serializers.DictField(),
                "rate_source": serializers.CharField(),
                "rows": out.RateRowSerializer(many=True),
            },
        ),
    )
    def get(self, request, company_id):
        params = request.query_params
        end = filters.day(params, "to") or self.today
        start = filters.day(params, "from") or (end - timedelta(days=59))
        foreign = Currency.USD if self.company.base_currency != Currency.USD else Currency.UZS
        quoted = Currency.USD
        official = ExchangeRate.objects.filter(currency=quoted, date__range=(start, end))
        own = CompanyRate.objects.filter(
            company=self.company, currency=quoted, date__range=(start, end)
        ).select_related("set_by")
        rows = sorted(
            [out.rate_row(row) for row in official] + [out.rate_row(row) for row in own],
            key=lambda row: (row["date"], row["source"]),
            reverse=True,
        )
        current = queries.valuation(self.company, self.today)
        fetched = (
            ExchangeRate.objects.filter(currency=quoted).order_by("-date", "-fetched_at").first()
        )
        return Response(
            {
                "currency": quoted,
                "base_currency": self.company.base_currency,
                "foreign_currency": foreign,
                "current": {
                    "rate": str(current.rate) if current.rate is not None else None,
                    "stale": current.stale,
                    "source": current.source,
                    "date": current.day,
                    "last_fetched_at": fetched.fetched_at if fetched else None,
                    "last_official_date": fetched.date if fetched else None,
                },
                "rate_source": conf.get_settings(self.company).rate_source,
                "rows": rows,
            }
        )

    @extend_schema(request=out.RateCreateSerializer, responses={201: out.RateRowSerializer})
    def post(self, request, company_id):
        serializer = out.RateCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row = domain(
            lambda: services.set_company_rate(
                self.company,
                by=self.membership,
                currency=data["currency"],
                day=data["date"],
                rate=data["rate"],
            )
        )
        self.changed()
        return Response(out.rate_row(row), status=status.HTTP_201_CREATED)


class RateDeleteView(FinanceMixin, OwnerAPIView):
    perm = MANAGE

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, pk):
        row = get_object_or_404(CompanyRate, company=self.company, pk=pk)
        domain(lambda: services.delete_company_rate(row, by=self.membership))
        self.changed()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RateFetchView(FinanceMixin, OwnerAPIView):
    """Ask the Central Bank for today's rate now (the hourly job does it on its own)."""

    perm = MANAGE

    @extend_schema(
        request=None,
        responses=inline_serializer(
            "FinanceRateFetch",
            {
                "ok": serializers.BooleanField(),
                "rate": serializers.CharField(allow_null=True),
                "detail": serializers.CharField(),
            },
        ),
    )
    def post(self, request, company_id):
        try:
            row = cbu.fetch_rate(self.today)
        except cbu.RateUnavailable:
            return Response(
                {
                    "ok": False,
                    "rate": None,
                    "detail": _(
                        "The Central Bank didn't answer. The last known rate stays in use."
                    ),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        self.changed()
        return Response({"ok": True, "rate": str(row.rate), "detail": _("Today's rate is stored.")})


# Reports --------------------------------------------------------------------------------------


def _compare(range_) -> tuple | None:
    return (range_.compare_start, range_.compare_end) if range_.has_compare else None


class PnlView(FinanceMixin, RangeMixin, OwnerAPIView):
    """Profit and loss: category trees by month or quarter, with margin."""

    perm = VIEW

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str),
            OpenApiParameter("to", str),
            OpenApiParameter("preset", str),
            OpenApiParameter("compare", str, description="none, prev, year"),
            OpenApiParameter("group", str, description="month (default) or quarter"),
            OpenApiParameter("branch", int, many=True),
        ],
        responses=inline_serializer(
            "FinancePnl", {"range": serializers.DictField(), "income": serializers.DictField()}
        ),
    )
    def get(self, request, company_id):
        group = request.query_params.get("group") or "month"
        if group not in ("month", "quarter"):
            raise exceptions.ValidationError({"group": [_("month or quarter.")]})
        data = queries.pnl(
            self.company,
            self.range.start,
            self.range.end,
            group,
            branch_ids=self.wanted_branches(),
            compare=_compare(self.range),
        )
        return Response(
            _jsonable({**self.range.as_dict(), "currency": self.company.base_currency, **data})
        )


class CashFlowView(FinanceMixin, RangeMixin, OwnerAPIView):
    """Cash flow in the analytics shape (`income`, `expense`, `net`) plus the operating,
    investing, financing, owner, transfer and opening sections."""

    perm = VIEW

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str),
            OpenApiParameter("to", str),
            OpenApiParameter("preset", str),
            OpenApiParameter("compare", str),
            OpenApiParameter("group", str, description="day, week or month (default: by length)"),
            OpenApiParameter("branch", int, many=True),
        ],
        responses=inline_serializer(
            "FinanceCashFlow",
            {
                "range": serializers.DictField(),
                "compare": serializers.DictField(allow_null=True),
                "currency": serializers.CharField(),
                "totals": serializers.DictField(),
                "previous": serializers.DictField(allow_null=True),
                "series": serializers.ListField(child=serializers.DictField()),
                "breakdown": serializers.ListField(child=serializers.DictField()),
                "start_cash": serializers.CharField(),
                "end_cash": serializers.CharField(),
            },
        ),
    )
    def get(self, request, company_id):
        group = request.query_params.get("group") or queries.auto_group(
            self.range.start, self.range.end
        )
        if group not in ("day", "week", "month"):
            raise exceptions.ValidationError({"group": [_("day, week or month.")]})
        data = queries.cash_flow(
            self.company,
            self.range.start,
            self.range.end,
            group,
            branch_ids=self.wanted_branches(),
            compare=_compare(self.range),
        )
        labels = {
            "operating": _("Operating"),
            "investing": _("Equipment and investments"),
            "financing": _("Loans"),
            "owner": _("Owner money"),
            "transfers": _("Transfers and exchange"),
            "opening": _("Opening balances"),
        }
        breakdown = [{**row, "label": labels[row["key"]]} for row in data.pop("sections")]
        return Response(_jsonable({**self.range.as_dict(), **data, "breakdown": breakdown}))


class BalancesView(FinanceMixin, OwnerAPIView):
    """Balances on a date: every account, what was owed both ways, the net position."""

    perm = VIEW

    @extend_schema(
        parameters=[OpenApiParameter("on", str), OpenApiParameter("branch", int, many=True)],
        responses=inline_serializer(
            "FinanceBalances", {"on": serializers.DateField(), "total": serializers.CharField()}
        ),
    )
    def get(self, request, company_id):
        on = filters.day(request.query_params, "on") or self.today
        if on > self.today:
            on = self.today
        data = queries.balances_on(self.company, on, branch_ids=self.wanted_branches())
        names = {
            account.pk: account
            for account in MoneyAccount.objects.filter(
                pk__in=[row["id"] for row in data["accounts"]]
            ).select_related("branch")
        }
        for row in data["accounts"]:
            account = names[row["id"]]
            row["kind_label"] = account.get_kind_display()
            row["branch"] = out.branch_ref(account.branch)
            row["is_active"] = account.is_active
        return Response(_jsonable(data))


class AgingView(FinanceMixin, OwnerAPIView):
    """Debt aging: open debts by days overdue (current, 1-30, 31-60, 61-90, 90+) per party."""

    perm = VIEW

    @extend_schema(
        parameters=[OpenApiParameter("direction", str), OpenApiParameter("branch", int, many=True)],
        responses=inline_serializer(
            "FinanceAging",
            {"direction": serializers.CharField(), "totals": serializers.DictField()},
        ),
    )
    def get(self, request, company_id):
        direction = request.query_params.get("direction") or Debt.Direction.RECEIVABLE
        if direction not in Debt.Direction.values:
            raise exceptions.ValidationError({"direction": [_("receivable or payable.")]})
        data = queries.debts_aging(
            self.company,
            direction,
            branch_ids=self.wanted_branches(),
            today=self.today,
            mask_sensitive=not access.sees_salary_detail(self.membership),
        )
        for party in data["parties"]:
            if party["type"] == "hidden":
                party["name"] = _("Staff (hidden)")
        return Response(_jsonable({**data, "today": self.today}))


class CategoryTrendView(FinanceMixin, OwnerAPIView):
    """One category (with its subcategories) month by month."""

    perm = VIEW

    @extend_schema(
        parameters=[
            OpenApiParameter("category", int, required=True),
            OpenApiParameter("months", int, description="1-36, default 12"),
            OpenApiParameter("branch", int, many=True),
        ],
        responses=inline_serializer(
            "FinanceCategoryTrend",
            {
                "series": serializers.ListField(child=serializers.DictField()),
                "previous_same_days": serializers.DictField(),
            },
        ),
    )
    def get(self, request, company_id):
        pk = filters.one_int(request.query_params, "category")
        if pk is None:
            raise exceptions.ValidationError({"category": [_("Pick a category.")]})
        category = get_object_or_404(Category, company=self.company, pk=pk)
        months = filters.one_int(request.query_params, "months") or 12
        data = queries.category_trend(
            self.company, category, months, branch_ids=self.wanted_branches(), today=self.today
        )
        return Response(_jsonable(data))


# Settings -------------------------------------------------------------------------------------


class SettingsView(FinanceMixin, OwnerAPIView):
    """Finance settings: rate source, thresholds, how reimbursements are paid, the period lock."""

    perm = MANAGE

    @extend_schema(responses=out.SettingsSerializer)
    def get(self, request, company_id):
        return Response(
            out.SettingsSerializer(conf.get_settings(self.company), context=self.context()).data
        )

    @extend_schema(request=out.SettingsUpdateSerializer, responses=out.SettingsSerializer)
    def patch(self, request, company_id):
        serializer = out.SettingsUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        row = domain(
            lambda: services.update_settings(
                self.company, by=self.membership, **serializer.validated_data
            )
        )
        self.changed()
        return Response(out.SettingsSerializer(row, context=self.context()).data)


class LockView(FinanceMixin, OwnerAPIView):
    """Close the books up to a day (or reopen: owners only)."""

    perm = MANAGE

    @extend_schema(request=out.LockSerializer, responses=out.SettingsSerializer)
    def post(self, request, company_id):
        serializer = out.LockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = domain(
            lambda: services.lock_period(
                self.company, by=self.membership, until=serializer.validated_data["until"]
            )
        )
        self.changed()
        return Response(out.SettingsSerializer(row, context=self.context()).data)


# JSON -----------------------------------------------------------------------------------------


def _jsonable(value):
    """Decimals as strings, days as ISO (model instances are serialized before this)."""
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if hasattr(value, "items") and not isinstance(value, dict):
        return _jsonable(dict(value.items()))
    return value
