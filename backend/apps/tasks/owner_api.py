"""Owner endpoints of tasks (docs/PLAN-OWNER.md §4.5): every task as a table, board and calendar,
the task drawer and its actions, bulk changes, reviews, the photo wall and routines.

Visibility always goes through `queries.visible_tasks` (personal tasks only for owners with the
company setting on; branch scope §2.6), so a task outside it answers 404 like another company's.
"""

from datetime import date, timedelta

from django.db import transaction
from django.db.models import Case, F, IntegerField, Value, When
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import exceptions, mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.companies.models import Branch
from apps.console.base import AnyOf, OwnerAPIView, OwnerViewSet
from apps.core.exceptions import DomainError
from apps.members.models import Membership, Position
from apps.members.permissions import Perm
from apps.members.scope import restrict
from apps.reminders.models import ReminderPolicy
from apps.tasks import dashboard, generation, queries, services
from apps.tasks.models import Task, TaskTemplate
from apps.tasks.owner_serializers import (
    BulkResponseSerializer,
    BulkSerializer,
    CommentRowSerializer,
    CommentSerializer,
    MoveSerializer,
    ReasonSerializer,
    ReassignSerializer,
    RoutineSerializer,
    RoutineWriteSerializer,
    TaskCreateSerializer,
    TaskDetailSerializer,
    TaskRowSerializer,
    TaskUpdateSerializer,
    person,
)

LIST_FILTERS = [
    OpenApiParameter(
        "status",
        description="One or more: todo, in_progress, review, returned, done, cancelled.",
        many=True,
    ),
    OpenApiParameter("kind", description="daily, assigned, personal (several allowed).", many=True),
    OpenApiParameter("assignee", int, many=True),
    OpenApiParameter("position", int, many=True),
    OpenApiParameter("branch", int, many=True),
    OpenApiParameter("created_by", int, many=True),
    OpenApiParameter("priority", many=True),
    OpenApiParameter("routine", int, many=True),
    OpenApiParameter("due_from", description="Company-local day, YYYY-MM-DD."),
    OpenApiParameter("due_to", description="Company-local day, YYYY-MM-DD (inclusive)."),
    OpenApiParameter("overdue", bool),
    OpenApiParameter("has_proof", bool),
    OpenApiParameter("needs_confirmation", bool),
    OpenApiParameter("q", description="Title, description or the person's name."),
]
ORDERINGS = {
    "due_at",
    "-due_at",
    "created_at",
    "-created_at",
    "completed_at",
    "-completed_at",
    "priority",
    "-priority",
    "status",
    "-status",
    "title",
    "-title",
    "assignee",
    "-assignee",
}
PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


def _ints(values) -> list[int]:
    out = []
    for value in values:
        for part in str(value).split(","):
            if part.strip().lstrip("-").isdigit():
                out.append(int(part))
    return out


def _texts(values) -> list[str]:
    return [part for value in values for part in str(value).split(",") if part]


def _boolean(value: str | None) -> bool | None:
    if value in (None, ""):
        return None
    return value.lower() in ("1", "true", "yes")


def _day(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise exceptions.ValidationError({name: [_("Use a day like 2026-10-20.")]}) from None


def parse_filters(params) -> queries.TaskFilters:
    return queries.TaskFilters(
        status=_texts(params.getlist("status")),
        kind=_texts(params.getlist("kind")),
        assignee=_ints(params.getlist("assignee")),
        position=_ints(params.getlist("position")),
        branch=_ints(params.getlist("branch")),
        created_by=_ints(params.getlist("created_by")),
        priority=_texts(params.getlist("priority")),
        routine=_ints(params.getlist("routine")),
        due_from=_day(params.get("due_from"), "due_from"),
        due_to=_day(params.get("due_to"), "due_to"),
        overdue=_boolean(params.get("overdue")),
        has_proof=_boolean(params.get("has_proof")),
        needs_confirmation=_boolean(params.get("needs_confirmation")),
        q=params.get("q", "")[:100],
    )


def order(tasks, ordering: str | None):
    """DRF-style `ordering` over the columns the table sorts by."""
    if not ordering or ordering not in ORDERINGS:
        return tasks.order_by("due_at", "pk")
    descending = ordering.startswith("-")
    field = ordering.lstrip("-")
    if field == "assignee":
        fields = ["assignee__first_name", "assignee__last_name"]
    elif field == "priority":
        rank = Case(
            *[When(priority=key, then=Value(value)) for key, value in PRIORITY_RANK.items()],
            output_field=IntegerField(),
        )
        tasks = tasks.annotate(priority_rank=rank)
        # "priority" ascending reads most urgent first.
        return tasks.order_by("-priority_rank" if descending else "priority_rank", "due_at", "pk")
    else:
        fields = [field]
    return tasks.order_by(
        *[
            (F(name).desc(nulls_last=True) if descending else F(name).asc(nulls_last=True))
            for name in fields
        ],
        "pk",
    )


class TaskOwnerViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, OwnerViewSet):
    """Every task the caller may see, and what they may do with one."""

    serializer_class = TaskRowSerializer
    perm = None  # the task's own rules decide, after visibility (§4.5: per rules.allowed_actions)
    perms_by_action = {
        "list": Perm.TASKS_VIEW_ALL,
        "board": Perm.TASKS_VIEW_ALL,
        "calendar": Perm.TASKS_VIEW_ALL,
        "summary": Perm.TASKS_VIEW_ALL,
        "create": Perm.TASKS_ASSIGN,
        "partial_update": AnyOf(Perm.TASKS_ASSIGN, Perm.TASKS_TEMPLATES),
        "bulk": AnyOf(Perm.TASKS_ASSIGN, Perm.TASKS_CONFIRM),
        "reassign": AnyOf(Perm.TASKS_ASSIGN, Perm.TASKS_TEMPLATES),
        "cancel": AnyOf(Perm.TASKS_ASSIGN, Perm.TASKS_TEMPLATES),
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Task.objects.none()
        return dashboard.with_rows(queries.visible_tasks(self.membership))

    def get_serializer_context(self):
        return super().get_serializer_context() | {"now": timezone.now()}

    def _filtered(self):
        filters = parse_filters(self.request.query_params)
        tasks = queries.filtered(
            self.company, viewer=self.membership, filters=filters, branch_ids=None
        )
        return dashboard.with_rows(tasks)

    def _detail(self, task: Task) -> dict:
        """The task after an action. A checker without tasks.view_all stops seeing work once
        it's checked; they still get the result of what they just did."""
        task = self.get_queryset().filter(pk=task.pk).first() or dashboard.with_rows(
            Task.objects.select_related(*queries.TASK_RELATIONS)
        ).get(pk=task.pk)
        return TaskDetailSerializer(task, context=self.get_serializer_context()).data

    @extend_schema(
        parameters=[*LIST_FILTERS, OpenApiParameter("ordering")],
        responses=TaskRowSerializer(many=True),
    )
    def list(self, request, company_id):
        tasks = order(self._filtered(), request.query_params.get("ordering"))
        page = self.paginate_queryset(tasks)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @extend_schema(responses=TaskDetailSerializer)
    def retrieve(self, request, company_id, pk):
        return Response(self._detail(self.get_object()))

    @extend_schema(
        request=TaskCreateSerializer,
        responses={
            201: inline_serializer(
                "TasksCreatedResponse",
                {
                    "created": serializers.IntegerField(),
                    "ids": serializers.ListField(child=serializers.IntegerField()),
                },
            )
        },
    )
    def create(self, request, company_id):
        """One task per person: the people chosen, plus everyone holding the positions or working
        in the branches chosen (the creator is left out of groups)."""
        data = TaskCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        fields = dict(data.validated_data)
        people = self._people(
            fields.pop("assignee_ids"), fields.pop("position_ids"), fields.pop("branch_ids")
        )
        tasks = services.create_for_many(by=self.membership, people=people, **fields)
        return Response(
            {"created": len(tasks), "ids": [task.pk for task in tasks]},
            status=status.HTTP_201_CREATED,
        )

    def _people(self, assignee_ids, position_ids, branch_ids) -> list[Membership]:
        company = self.company
        registered = Membership.objects.for_company(company).filter(
            status=Membership.Status.APPROVED, onboarded_at__isnull=False
        )
        chosen = list(registered.filter(pk__in=assignee_ids).select_related("user", "company"))
        if len(chosen) != len(set(assignee_ids)):
            raise DomainError(_("Some of the people picked don't work here."))
        group = registered.none()
        if position_ids:
            if Position.objects.for_company(company).filter(pk__in=position_ids).count() != len(
                set(position_ids)
            ):
                raise DomainError(_("That isn't part of your company."))
            group = group | registered.filter(position_id__in=position_ids)
        if branch_ids:
            if Branch.objects.filter(company=company, pk__in=branch_ids).count() != len(
                set(branch_ids)
            ):
                raise DomainError(_("That isn't part of your company."))
            group = group | registered.filter(home_branch_id__in=branch_ids)
        scope = self.branch_scope
        from_groups = list(
            restrict(group, scope, field="branches")
            .exclude(pk=self.membership.pk)
            .distinct()
            .select_related("user", "company")
        )
        if (position_ids or branch_ids) and not from_groups and not chosen:
            raise DomainError(
                _("Nobody you may give work to holds those positions or works there.")
            )
        return chosen + from_groups

    @extend_schema(request=TaskUpdateSerializer, responses=TaskDetailSerializer)
    def partial_update(self, request, company_id, pk):
        changes = TaskUpdateSerializer(data=request.data, partial=True)
        changes.is_valid(raise_exception=True)
        task = services.update_task(self.get_object(), by=self.membership, **changes.validated_data)
        return Response(self._detail(task))

    @extend_schema(request=None, responses=TaskDetailSerializer)
    @action(detail=True, methods=["post"])
    def confirm(self, request, company_id, pk):
        task = services.confirm_task(self.get_object(), by=self.membership)
        return Response(self._detail(task))

    @extend_schema(request=ReasonSerializer, responses=TaskDetailSerializer)
    @action(detail=True, methods=["post"], url_path="return")
    def send_back(self, request, company_id, pk):
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        task = services.return_task(
            self.get_object(), by=self.membership, reason=data.validated_data["reason"]
        )
        return Response(self._detail(task))

    @extend_schema(request=None, responses=TaskDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, company_id, pk):
        task = services.cancel_task(self.get_object(), by=self.membership)
        return Response(self._detail(task))

    @extend_schema(request=ReassignSerializer, responses=TaskDetailSerializer)
    @action(detail=True, methods=["post"])
    def reassign(self, request, company_id, pk):
        data = ReassignSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        assignee = self._member(data.validated_data["assignee_id"])
        task = services.reassign_task(self.get_object(), by=self.membership, assignee=assignee)
        return Response(self._detail(task))

    @extend_schema(
        request=None,
        responses=inline_serializer(
            "TaskNudgeResponse", {"nudged_at": serializers.DateTimeField()}
        ),
    )
    @action(detail=True, methods=["post"])
    def nudge(self, request, company_id, pk):
        task = self.get_object()
        services.nudge(task, by=self.membership)
        task.refresh_from_db(fields=["last_nudged_at"])
        return Response({"nudged_at": task.last_nudged_at})

    @extend_schema(request=CommentSerializer, responses={201: CommentRowSerializer})
    @action(detail=True, methods=["post"])
    def comment(self, request, company_id, pk):
        data = CommentSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        comment = services.add_comment(
            self.get_object(), by=self.membership, text=data.validated_data["text"]
        )
        return Response(CommentRowSerializer(comment).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=MoveSerializer, responses=TaskDetailSerializer)
    @action(detail=True, methods=["post"])
    def move(self, request, company_id, pk):
        """A board drag: the column means one transition (start, finish, confirm, send back)."""
        data = MoveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        task = services.move_task(
            self.get_object(),
            by=self.membership,
            to=data.validated_data["to"],
            reason=data.validated_data["reason"],
        )
        return Response(self._detail(task))

    @extend_schema(
        responses=inline_serializer(
            "TaskTimelineEntry",
            {
                "at": serializers.DateTimeField(),
                "kind": serializers.CharField(),
                "action": serializers.CharField(),
                "actor": serializers.DictField(allow_null=True),
                "text": serializers.CharField(),
                "meta": serializers.DictField(),
            },
            many=True,
        )
    )
    @action(detail=True, methods=["get"])
    def timeline(self, request, company_id, pk):
        """Comments, reminders and audited changes, oldest first."""
        task = self.get_object()
        entries = dashboard.timeline(task, self.membership)
        return Response([entry | {"actor": person(entry["actor"])} for entry in entries])

    @extend_schema(request=BulkSerializer, responses=BulkResponseSerializer)
    @action(detail=False, methods=["post"])
    def bulk(self, request, company_id):
        """One action on many tasks; each succeeds or fails on its own."""
        data = BulkSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        payload = dict(data.validated_data["payload"])
        if "assignee_id" in payload:
            payload["assignee"] = self._member(payload.pop("assignee_id"))
        results = services.bulk(
            by=self.membership,
            ids=data.validated_data["ids"],
            action=data.validated_data["action"],
            payload=payload,
        )
        done = sum(result.ok for result in results)
        return Response(
            {
                "done": done,
                "failed": len(results) - done,
                "results": [{"id": r.id, "ok": r.ok, "error": r.error} for r in results],
            }
        )

    @extend_schema(
        parameters=LIST_FILTERS,
        responses=inline_serializer(
            "TaskBoard",
            {
                "columns": inline_serializer(
                    "TaskBoardColumn",
                    {
                        "id": serializers.CharField(),
                        "count": serializers.IntegerField(),
                        "items": TaskRowSerializer(many=True),
                    },
                    many=True,
                )
            },
        ),
    )
    @action(detail=False, methods=["get"])
    def board(self, request, company_id):
        """To do, In progress, Waiting, Sent back, Done (last 7 days), each capped at 60 cards."""
        now = timezone.now()
        columns = dashboard.board(self._filtered(), now, self.company)
        context = self.get_serializer_context()
        return Response(
            {
                "columns": [
                    column
                    | {"items": TaskRowSerializer(column["items"], many=True, context=context).data}
                    for column in columns
                ]
            }
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("from", required=True),
            OpenApiParameter("to", required=True),
            *LIST_FILTERS,
        ],
        responses=inline_serializer(
            "TaskCalendar",
            {
                "days": inline_serializer(
                    "TaskCalendarDay",
                    {
                        "date": serializers.DateField(),
                        "total": serializers.IntegerField(),
                        "done": serializers.IntegerField(),
                        "review": serializers.IntegerField(),
                        "open": serializers.IntegerField(),
                        "late": serializers.IntegerField(),
                    },
                    many=True,
                ),
                "items": TaskRowSerializer(many=True),
                "truncated": serializers.BooleanField(),
            },
        ),
    )
    @action(detail=False, methods=["get"])
    def calendar(self, request, company_id):
        """Due tasks per day between `from` and `to` (at most 62 days)."""
        start, end = _range(request.query_params)
        data = dashboard.calendar(self._filtered(), self.company, start, end, timezone.now())
        data["items"] = TaskRowSerializer(
            data["items"], many=True, context=self.get_serializer_context()
        ).data
        return Response(data)

    @extend_schema(
        parameters=[OpenApiParameter("assignee", int), OpenApiParameter("branch", int, many=True)],
        responses=inline_serializer(
            "TaskSummary",
            {
                "today": serializers.DateField(),
                "done_today": serializers.IntegerField(),
                "total_today": serializers.IntegerField(),
                "late_now": serializers.IntegerField(),
                "review": serializers.IntegerField(),
                "open": serializers.IntegerField(),
                "on_time_percent": serializers.FloatField(allow_null=True),
                "on_time_previous": serializers.FloatField(allow_null=True),
                "done_7d": serializers.IntegerField(),
                "done_prev_7d": serializers.IntegerField(),
                "series": serializers.ListField(child=serializers.DictField()),
            },
        ),
    )
    @action(detail=False, methods=["get"])
    def summary(self, request, company_id):
        """KPI numbers (personal tasks never count): today, late now, waiting for a check,
        7-day on-time % against the 7 days before, a 14-day series."""
        assignee = _ints(request.query_params.getlist("assignee"))
        branches = _ints(request.query_params.getlist("branch"))
        data = dashboard.summary(
            self.membership,
            timezone.now(),
            branch_ids=branches or None,
            assignee_id=assignee[0] if assignee else None,
        )
        return Response(data)

    @extend_schema(responses=TaskDetailSerializer(many=True))
    @action(detail=False, methods=["get"])
    def reviews(self, request, company_id):
        """Work waiting for the caller's check, oldest first, with proof photos."""
        tasks = dashboard.with_rows(queries.awaiting_review_by(self.membership)).order_by(
            "completed_at", "pk"
        )
        page = self.paginate_queryset(tasks)
        return self.get_paginated_response(
            TaskDetailSerializer(page, many=True, context=self.get_serializer_context()).data
        )

    @extend_schema(
        responses=inline_serializer(
            "TaskOptions",
            {
                "people": serializers.ListField(child=serializers.DictField()),
                "positions": serializers.ListField(child=serializers.DictField()),
                "routines": serializers.ListField(child=serializers.DictField()),
                "policies": serializers.ListField(child=serializers.DictField()),
            },
        )
    )
    @action(detail=False, methods=["get"])
    def options(self, request, company_id):
        """What the pickers offer: people the caller may give work to (their branch scope),
        positions, routines and reminder policies."""
        company = self.company
        people = restrict(
            Membership.objects.for_company(company).filter(
                status=Membership.Status.APPROVED, onboarded_at__isnull=False
            ),
            self.branch_scope,
            field="branches",
        ).select_related("user", "position", "home_branch")
        return Response(
            {
                "people": [
                    person(member)
                    | {
                        "branch": member.home_branch.name if member.home_branch_id else None,
                        "branch_id": member.home_branch_id,
                        "position_id": member.position_id,
                    }
                    for member in sorted(people, key=lambda m: str(m).lower())
                ],
                "positions": [
                    {"id": p.pk, "name": p.name}
                    for p in Position.objects.for_company(company).order_by("order", "name")
                ],
                "routines": [
                    {"id": t.pk, "title": t.title}
                    for t in TaskTemplate.objects.for_company(company)
                    .filter(personal=False)
                    .order_by("title")
                ],
                "policies": [
                    {"id": p.pk, "name": p.name, "is_default": p.is_default}
                    for p in ReminderPolicy.objects.for_company(company)
                ],
            }
        )

    def _member(self, member_id: int) -> Membership:
        member = (
            Membership.objects.for_company(self.company)
            .select_related("user", "company", "position")
            .filter(pk=member_id)
            .first()
        )
        if member is None:
            raise DomainError(_("That person isn't in your company."))
        return member


def _range(params, *, max_days: int = 62) -> tuple[date, date]:
    start = _day(params.get("from"), "from")
    end = _day(params.get("to"), "to")
    if start is None or end is None:
        raise exceptions.ValidationError({"from": [_("Give from and to.")]})
    if end < start:
        raise exceptions.ValidationError({"to": [_("The last day can't be before the first.")]})
    if (end - start).days + 1 > max_days:
        raise exceptions.ValidationError(
            {"to": [_("Pick at most %(days)d days.") % {"days": max_days}]}
        )
    return start, end


class ProofWallView(OwnerAPIView):
    """Today's (or a day's) proof photos, newest first, to group by branch and routine."""

    perm = Perm.TASKS_VIEW_ALL

    @extend_schema(
        parameters=[
            OpenApiParameter("day"),
            OpenApiParameter("branch", int),
            OpenApiParameter("routine", int),
        ],
        responses=inline_serializer(
            "TaskProofWall", {"day": serializers.DateField(), "items": TaskRowSerializer(many=True)}
        ),
    )
    def get(self, request, company_id):
        day = _day(request.query_params.get("day"), "day") or queries.company_today(self.company)
        branch = _ints(request.query_params.getlist("branch"))
        routine = _ints(request.query_params.getlist("routine"))
        tasks = dashboard.proofs(
            self.membership,
            day,
            branch_ids=branch or None,
            routine_id=routine[0] if routine else None,
        )
        context = {"membership": self.membership, "now": timezone.now()}
        return Response(
            {"day": day, "items": TaskRowSerializer(tasks, many=True, context=context).data}
        )


class RoutineViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """Routines (daily templates) and onboarding templates (`?onboarding=true`)."""

    serializer_class = RoutineSerializer
    perm = Perm.TASKS_TEMPLATES
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TaskTemplate.objects.none()
        templates = (
            TaskTemplate.objects.for_company(self.company)
            .filter(personal=False)
            .select_related(
                "branch", "reminder_policy", "escalate_to__user", "escalate_to__position", "company"
            )
            .prefetch_related("assignees__user", "assignees__position", "positions")
        )
        scope = self.branch_scope
        if scope is not None:
            templates = templates.filter(branch_id__in=scope)
        return templates

    @extend_schema(
        parameters=[
            OpenApiParameter("onboarding", bool),
            OpenApiParameter("q"),
            OpenApiParameter("active", bool),
        ],
        responses=RoutineSerializer(many=True),
    )
    def list(self, request, company_id):
        templates = self.get_queryset().filter(
            onboarding=_boolean(request.query_params.get("onboarding")) or False
        )
        active = _boolean(request.query_params.get("active"))
        if active is not None:
            templates = templates.filter(is_active=active)
        if q := request.query_params.get("q", "").strip():
            templates = templates.filter(title__icontains=q)
        templates = list(templates.order_by("-is_active", "due_time", "title"))
        stats = dashboard.routine_stats(templates, self.company, timezone.now())
        context = self.get_serializer_context() | {"stats": stats}
        return Response(RoutineSerializer(templates, many=True, context=context).data)

    def retrieve(self, request, company_id, pk):
        template = self.get_object()
        stats = dashboard.routine_stats([template], self.company, timezone.now())
        return Response(
            RoutineSerializer(
                template, context=self.get_serializer_context() | {"stats": stats}
            ).data
        )

    @extend_schema(request=RoutineWriteSerializer, responses={201: RoutineSerializer})
    def create(self, request, company_id):
        fields = self._fields(request.data, partial=False)
        template = services.create_template(by=self.membership, **fields)
        return Response(
            RoutineSerializer(self.get_queryset().get(pk=template.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=RoutineWriteSerializer, responses=RoutineSerializer)
    def partial_update(self, request, company_id, pk):
        template = self.get_object()
        fields = self._fields(request.data, partial=True)
        template = services.update_template(template, by=self.membership, **fields)
        return Response(RoutineSerializer(self.get_queryset().get(pk=template.pk)).data)

    @transaction.atomic
    def perform_destroy(self, template):
        services.delete_template(template, by=self.membership)

    def _fields(self, data, *, partial: bool) -> dict:
        serializer = RoutineWriteSerializer(data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        company = self.company
        if not partial:
            for required in ("title", "due_time"):
                if required not in fields:
                    raise exceptions.ValidationError({required: [_("This field is required.")]})
        if "branch_id" in fields:
            branch_id = fields.pop("branch_id")
            fields["branch"] = _one(Branch.objects.filter(company=company), branch_id)
        if "reminder_policy_id" in fields:
            fields["reminder_policy"] = _one(
                ReminderPolicy.objects.for_company(company), fields.pop("reminder_policy_id")
            )
        if "escalate_to_id" in fields:
            fields["escalate_to"] = _one(
                Membership.objects.for_company(company), fields.pop("escalate_to_id")
            )
        if "assignee_ids" in fields:
            ids = set(fields.pop("assignee_ids"))
            people = list(
                Membership.objects.for_company(company).filter(pk__in=ids).select_related("company")
            )
            if len(people) != len(ids):
                raise DomainError(_("Some of the people picked don't work here."))
            fields["assignees"] = people
        if "position_ids" in fields:
            ids = set(fields.pop("position_ids"))
            positions = list(Position.objects.for_company(company).filter(pk__in=ids))
            if len(positions) != len(ids):
                raise DomainError(_("That isn't part of your company."))
            fields["positions"] = positions
        return fields

    @extend_schema(
        parameters=[OpenApiParameter("day", description="Default: tomorrow.")],
        responses=inline_serializer(
            "RoutinePreview",
            {
                "day": serializers.DateField(),
                "due": serializers.BooleanField(),
                "holiday": serializers.BooleanField(),
                "people": serializers.ListField(child=serializers.DictField()),
            },
        ),
    )
    @action(detail=True, methods=["get"])
    def preview(self, request, company_id, pk):
        """Who would get it on `day`, by the same rules as daily generation."""
        template = self.get_object()
        day = _day(request.query_params.get("day"), "day") or queries.company_today(
            self.company
        ) + timedelta(days=1)
        data = generation.preview(template, day)
        return Response(
            {
                "day": day,
                "due": data["due"],
                "holiday": data["holiday"],
                "people": [
                    {"member": person(row["member"]), "gets": row["gets"], "reason": row["reason"]}
                    for row in data["people"]
                ],
            }
        )

    @extend_schema(
        parameters=[OpenApiParameter("from"), OpenApiParameter("to")],
        responses=inline_serializer(
            "RoutineCompliance",
            {
                "range": serializers.DictField(),
                "totals": serializers.DictField(),
                "series": serializers.ListField(child=serializers.DictField()),
                "people": serializers.ListField(child=serializers.DictField()),
            },
        ),
    )
    @action(detail=True, methods=["get"])
    def compliance(self, request, company_id, pk):
        """Made, on time, late and missed per day and per person (default: the last 30 days)."""
        template = self.get_object()
        today = queries.company_today(self.company)
        params = request.query_params
        if params.get("from") or params.get("to"):
            start, end = _range(params, max_days=366)
        else:
            start, end = today - timedelta(days=29), today
        data = dashboard.routine_compliance(template, start, end, timezone.now())
        data["people"] = [row | {"member": person(row["member"])} for row in data["people"]]
        return Response({"range": {"from": start, "to": end}, **data})


def _one(queryset, pk):
    if pk is None:
        return None
    found = queryset.filter(pk=pk).first()
    if found is None:
        raise DomainError(_("That isn't part of your company."))
    return found
