"""Owner endpoints of reminders (docs/PLAN-OWNER.md §4.5): reminder policies with their texts
per step, the reminder log and the people who blocked the bot."""

from datetime import date

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_field,
    inline_serializer,
)
from rest_framework import exceptions, mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.console.base import AnyOf, OwnerAPIView, OwnerViewSet
from apps.core.api import Pagination
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.scope import restrict
from apps.reminders import services
from apps.reminders.models import ReminderLog, ReminderPolicy
from apps.reminders.services import LIMITS
from apps.tasks import queries as task_queries
from apps.tasks.models import Task, TaskTemplate
from apps.tasks.owner_serializers import person


class ReminderTextSerializer(serializers.Serializer):
    from_step = serializers.IntegerField(min_value=1, max_value=100)
    text = serializers.CharField(max_length=services.MAX_TEXT_LENGTH)


def _bounded(name: str, **kwargs) -> serializers.IntegerField:
    low, high = LIMITS[name]
    return serializers.IntegerField(min_value=low, max_value=high, **kwargs)


class PolicySerializer(serializers.ModelSerializer):
    texts = serializers.SerializerMethodField()
    usage = serializers.SerializerMethodField()

    class Meta:
        model = ReminderPolicy
        fields = (
            "id",
            "name",
            "is_default",
            "heads_up_minutes",
            "repeat_every_minutes",
            "max_reminders",
            "escalate_after",
            "quiet_from",
            "quiet_until",
            "quiet_days",
            "snooze_minutes",
            "max_snoozes",
            "replace_previous",
            "texts",
            "usage",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(ReminderTextSerializer(many=True))
    def get_texts(self, policy: ReminderPolicy) -> list[dict]:
        return [{"from_step": text.from_step, "text": text.text} for text in policy.texts.all()]

    @extend_schema_field(
        inline_serializer(
            "ReminderPolicyUsage",
            {"routines": serializers.IntegerField(), "open_tasks": serializers.IntegerField()},
        )
    )
    def get_usage(self, policy: ReminderPolicy) -> dict:
        """How many routines and open tasks follow it (the default also covers those with none)."""
        return self.context.get("usage", {}).get(policy.pk, {"routines": 0, "open_tasks": 0})


class PolicyWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    heads_up_minutes = _bounded("heads_up_minutes", required=False)
    repeat_every_minutes = _bounded("repeat_every_minutes", required=False)
    max_reminders = _bounded("max_reminders", required=False)
    escalate_after = _bounded("escalate_after", required=False)
    quiet_from = serializers.TimeField(allow_null=True, required=False)
    quiet_until = serializers.TimeField(allow_null=True, required=False)
    quiet_days = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6), required=False
    )
    snooze_minutes = _bounded("snooze_minutes", required=False)
    max_snoozes = _bounded("max_snoozes", required=False)
    replace_previous = serializers.BooleanField(required=False)
    texts = ReminderTextSerializer(many=True, required=False)


class ReminderPolicyOwnerViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, OwnerViewSet
):
    """How hard the bot chases late work. Needs reminders.configure."""

    serializer_class = PolicySerializer
    perm = Perm.REMINDERS_CONFIGURE
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ReminderPolicy.objects.none()
        return ReminderPolicy.objects.for_company(self.company).prefetch_related("texts")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "company", None) is not None:
            context["usage"] = _usage(self.company)
        return context

    def _respond(self, policy: ReminderPolicy, code=status.HTTP_200_OK) -> Response:
        policy = self.get_queryset().get(pk=policy.pk)
        return Response(
            PolicySerializer(policy, context=self.get_serializer_context()).data, status=code
        )

    @extend_schema(request=PolicyWriteSerializer, responses={201: PolicySerializer})
    def create(self, request, company_id):
        data = PolicyWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        fields = dict(data.validated_data)
        if "name" not in fields:
            raise exceptions.ValidationError({"name": [_("This field is required.")]})
        policy = services.create_policy(by=self.membership, **fields)
        self.bump("reminders.policies")
        return self._respond(policy, status.HTTP_201_CREATED)

    @extend_schema(request=PolicyWriteSerializer, responses=PolicySerializer)
    def partial_update(self, request, company_id, pk):
        data = PolicyWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        policy = services.update_policy(
            self.get_object(), by=self.membership, **data.validated_data
        )
        self.bump("reminders.policies")
        return self._respond(policy)

    def perform_destroy(self, policy):
        services.delete_policy(policy, by=self.membership)
        self.bump("reminders.policies")

    @extend_schema(request=None, responses=PolicySerializer)
    @action(detail=True, methods=["post"], url_path="make-default")
    def make_default(self, request, company_id, pk):
        policy = services.make_default(self.get_object(), by=self.membership)
        self.bump("reminders.policies")
        return self._respond(policy)


def _usage(company) -> dict[int, dict]:
    routines = dict(
        TaskTemplate.objects.for_company(company)
        .filter(personal=False, reminder_policy__isnull=False)
        .values("reminder_policy")
        .annotate(n=Count("pk"))
        .values_list("reminder_policy", "n")
    )
    open_tasks = dict(
        Task.objects.for_company(company)
        .filter(status__in=Task.OPEN_STATUSES, reminder_policy__isnull=False)
        .values("reminder_policy")
        .annotate(n=Count("pk"))
        .values_list("reminder_policy", "n")
    )
    default = ReminderPolicy.objects.for_company(company).filter(is_default=True).first()
    if default is not None:  # it also covers every routine and task without a policy of its own
        routines[default.pk] = routines.get(default.pk, 0) + (
            TaskTemplate.objects.for_company(company)
            .filter(personal=False, reminder_policy__isnull=True)
            .count()
        )
        open_tasks[default.pk] = open_tasks.get(default.pk, 0) + (
            Task.objects.for_company(company)
            .filter(
                status__in=Task.OPEN_STATUSES, reminder_policy__isnull=True, due_at__isnull=False
            )
            .filter(Q(template__isnull=True) | Q(template__reminder_policy__isnull=True))
            .count()
        )
    keys = set(routines) | set(open_tasks)
    return {
        pk: {"routines": routines.get(pk, 0), "open_tasks": open_tasks.get(pk, 0)} for pk in keys
    }


class ReminderLogView(OwnerAPIView):
    """Every reminder, escalation and blocked notice the bot sent, newest first."""

    # Whoever tunes reminders, or sees every task they are about.
    perm = AnyOf(Perm.REMINDERS_CONFIGURE, Perm.TASKS_VIEW_ALL)

    @extend_schema(
        parameters=[
            OpenApiParameter("kind", enum=list(ReminderLog.Kind.values)),
            OpenApiParameter("delivered", bool),
            OpenApiParameter("from"),
            OpenApiParameter("to"),
            OpenApiParameter("q", description="Task title or the person's name."),
            OpenApiParameter("page", int),
            OpenApiParameter("page_size", int),
        ],
        responses=inline_serializer(
            "ReminderLogPage",
            {
                "count": serializers.IntegerField(),
                "next": serializers.CharField(allow_null=True),
                "previous": serializers.CharField(allow_null=True),
                "results": serializers.ListField(child=serializers.DictField()),
            },
        ),
    )
    def get(self, request, company_id):
        params = request.query_params
        visible = task_queries.visible_tasks(self.membership).values("pk")
        logs = (
            ReminderLog.objects.filter(task__company=self.company, task__in=visible)
            .select_related("task__branch", "recipient__user", "recipient__position")
            .order_by("-sent_at", "-pk")
        )
        if kind := params.get("kind"):
            logs = logs.filter(kind=kind)
        if params.get("delivered") in ("true", "false", "1", "0"):
            logs = logs.filter(delivered=params.get("delivered") in ("true", "1"))
        if q := params.get("q", "").strip():
            logs = logs.filter(
                Q(task__title__icontains=q)
                | Q(recipient__first_name__icontains=q)
                | Q(recipient__last_name__icontains=q)
            )
        start, end = _day(params.get("from")), _day(params.get("to"))
        if start:
            logs = logs.filter(sent_at__gte=task_queries.day_bounds(self.company, start)[0])
        if end:
            logs = logs.filter(sent_at__lt=task_queries.day_bounds(self.company, end)[1])
        paginator = Pagination()
        page = paginator.paginate_queryset(logs, request, view=self)
        return paginator.get_paginated_response([_log_row(log) for log in page])


def _log_row(log: ReminderLog) -> dict:
    task = log.task
    return {
        "id": log.pk,
        "kind": log.kind,
        "step": log.step,
        "sent_at": log.sent_at,
        "delivered": log.delivered,
        "error": log.error,
        "recipient": person(log.recipient),
        "task": {"id": task.pk, "title": task.title, "status": task.status},
        "branch": {"id": task.branch.pk, "name": task.branch.name, "code": task.branch.code}
        if task.branch_id
        else None,
    }


def _day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise exceptions.ValidationError({"from": [_("Use a day like 2026-10-20.")]}) from None


class BlockedBotView(OwnerAPIView):
    """People who blocked the employee bot: reminders can't reach them."""

    perm = Perm.MEMBERS_VIEW

    @extend_schema(
        responses=inline_serializer(
            "ReminderBlockedPerson",
            {
                "member": serializers.DictField(),
                "blocked_at": serializers.DateTimeField(),
                "branch": serializers.CharField(allow_null=True),
                "open_tasks": serializers.IntegerField(),
                "late_tasks": serializers.IntegerField(),
            },
            many=True,
        )
    )
    def get(self, request, company_id):
        now = timezone.now()
        people = (
            restrict(
                Membership.objects.for_company(self.company).filter(
                    status=Membership.Status.APPROVED, user__employee_bot_blocked_at__isnull=False
                ),
                self.branch_scope,
                field="branches",
            )
            .select_related("user", "position", "home_branch")
            .annotate(
                open_tasks=Count(
                    "tasks", filter=Q(tasks__status__in=Task.OPEN_STATUSES), distinct=True
                ),
                late_tasks=Count(
                    "tasks",
                    filter=Q(tasks__status__in=Task.OPEN_STATUSES, tasks__due_at__lt=now),
                    distinct=True,
                ),
            )
        )
        rows = [
            {
                "member": person(member),
                "blocked_at": member.user.employee_bot_blocked_at,
                "branch": member.home_branch.name if member.home_branch_id else None,
                "open_tasks": member.open_tasks,
                "late_tasks": member.late_tasks,
            }
            for member in people.order_by("-user__employee_bot_blocked_at")
        ]
        return Response(rows)
