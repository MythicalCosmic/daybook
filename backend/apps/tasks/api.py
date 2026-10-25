from datetime import date
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core import uploads
from apps.core.exceptions import DomainError
from apps.core.money import MoneySerializerField
from apps.members.api import IsCompanyMember, MemberBriefSerializer, requires
from apps.members.models import Membership, Position
from apps.members.permissions import Perm
from apps.reminders.models import ReminderLog
from apps.reminders.policies import escalation_recipients, policy_for
from apps.tasks import dashboard, dates, queries, quickadd, rules, services, stats
from apps.tasks.conf import REVIEW_RULE_HELP
from apps.tasks.models import (
    Activity,
    ChecklistItem,
    Proof,
    Repeat,
    Task,
    TaskComment,
    TaskTemplate,
    Weekday,
)

MAX_PHOTO_BYTES = 10 * 1024 * 1024


class ChecklistItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChecklistItem
        fields = ("id", "text", "is_done")
        read_only_fields = fields


class ReminderInfoSerializer(serializers.Serializer):
    every_minutes = serializers.IntegerField()
    sent = serializers.IntegerField()
    max_reminders = serializers.IntegerField(help_text="0 = until it's done.")
    escalate_after = serializers.IntegerField(help_text="0 = the manager is never told.")
    next_at = serializers.DateTimeField(allow_null=True)
    escalated_at = serializers.DateTimeField(allow_null=True)
    escalate_to = serializers.CharField(allow_null=True, help_text="Name, when it's one person.")
    snooze_minutes = serializers.IntegerField()
    snoozes_left = serializers.IntegerField()
    snoozed_until = serializers.DateTimeField(allow_null=True)
    sent_times = serializers.ListField(
        child=serializers.DateTimeField(),
        help_text="When the reminders the assignee got went out, oldest first.",
    )


class TaskCardSerializer(serializers.Serializer):
    project_id = serializers.IntegerField()
    project_key = serializers.CharField(help_text='"RENO"')
    number = serializers.IntegerField()
    key = serializers.CharField(help_text='The card\'s key, "RENO-14".')


class TaskBlockerSerializer(serializers.Serializer):
    reason_code = serializers.ChoiceField(Task.Blocker.choices)
    note = serializers.CharField(allow_blank=True)
    at = serializers.DateTimeField()


class TaskExtensionSerializer(serializers.Serializer):
    until = serializers.DateTimeField()
    note = serializers.CharField(allow_blank=True)
    at = serializers.DateTimeField()


def blocker_of(task: Task) -> dict | None:
    """The open "can't do it" of a task (both APIs), or None."""
    if task.blocked_at is None:
        return None
    return {"reason_code": task.blocker, "note": task.blocker_note, "at": task.blocked_at}


def extension_of(task: Task) -> dict | None:
    """The open "need more time" request of a task (both APIs), or None."""
    if task.extension_until is None:
        return None
    return {
        "until": task.extension_until,
        "note": task.extension_note,
        "at": task.extension_asked_at,
    }


class TaskSerializer(serializers.ModelSerializer):
    assignee = MemberBriefSerializer()
    created_by = MemberBriefSerializer(allow_null=True)
    confirmed_by = MemberBriefSerializer(allow_null=True)
    checklist = ChecklistItemSerializer(many=True)
    card = serializers.SerializerMethodField()
    reminder = serializers.SerializerMethodField()
    repeat_weekdays = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()
    reward = MoneySerializerField(allow_null=True, read_only=True)
    proof_thumb = serializers.SerializerMethodField()
    routine = serializers.SerializerMethodField()
    blocker = serializers.SerializerMethodField()
    extension = serializers.SerializerMethodField()
    returned_reason = serializers.SerializerMethodField()
    returned_by = serializers.SerializerMethodField()
    accepted_automatically = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = (
            "id",
            "kind",
            "routine",
            "title",
            "description",
            "status",
            "priority",
            "due_at",
            "for_date",
            "proof",
            "needs_confirmation",
            "accept_with_proof",
            "accepted_automatically",
            "proof_text",
            "proof_photo",
            "proof_thumb",
            "reward",
            "assignee",
            "created_by",
            "checklist",
            "card",
            "reminder",
            "repeat_weekdays",
            "started_at",
            "completed_at",
            "confirmed_at",
            "confirmed_by",
            "is_overdue",
            "actions",
            "snoozed_until",
            "seen_at",
            "blocker",
            "extension",
            "returned_reason",
            "returned_by",
            "created_at",
        )
        read_only_fields = fields

    def get_accepted_automatically(self, task: Task) -> bool:
        """Done and accepted without anyone checking it: at once (no check asked for, or the
        company's rule took its proof), or after the company's wait (`confirmed_at` is then
        when). The person who did it reads "Accepted"."""
        return rules.accepted_automatically(task)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_returned_reason(self, task: Task) -> str | None:
        """Why it was sent back, while it's back with the assignee (single-task responses)."""
        sent_back = self._sent_back(task)
        return sent_back[0] if sent_back else None

    @extend_schema_field(MemberBriefSerializer(allow_null=True))
    def get_returned_by(self, task: Task) -> dict | None:
        """Who sent it back (single-task responses)."""
        sent_back = self._sent_back(task)
        if not sent_back or sent_back[1] is None:
            return None
        return MemberBriefSerializer(sent_back[1]).data

    def _sent_back(self, task: Task) -> tuple[str, Membership | None] | None:
        """The last "sent back" of a task back with its assignee: the reason and who said it."""
        if not self.context.get("detail") or task.status != Task.Status.RETURNED:
            return None
        cache = self.context.setdefault("_sent_back", {})
        if task.pk not in cache:
            row = (
                AuditLog.objects.filter(
                    target_type="task", target_id=task.pk, action=AuditLog.Action.TASK_RETURNED
                )
                .order_by("-created_at", "-pk")
                .first()
            )
            who = None
            if row is not None and row.actor_id is not None:
                who = (
                    Membership.objects.filter(company_id=task.company_id, user_id=row.actor_id)
                    .select_related("user", "position")
                    .first()
                )
            cache[task.pk] = ((row.details or {}).get("reason", ""), who) if row else None
        return cache[task.pk]

    @extend_schema_field(TaskBlockerSerializer(allow_null=True))
    def get_blocker(self, task: Task) -> dict | None:
        """The assignee's "can't do it", while nobody has answered it."""
        return blocker_of(task)

    @extend_schema_field(TaskExtensionSerializer(allow_null=True))
    def get_extension(self, task: Task) -> dict | None:
        """The later deadline the assignee asked for, while nobody has decided."""
        return extension_of(task)

    @extend_schema_field(TaskCardSerializer(allow_null=True))
    def get_card(self, task: Task) -> dict | None:
        """The project card this task is (apps.projects), or null. Lists load it with
        `queries.TASK_RELATIONS`, so it costs no query."""
        card = getattr(task, "card", None) if task.project_id else None
        if card is None:
            return None
        key = task.project.key
        return {
            "project_id": task.project_id,
            "project_key": key,
            "number": card.number,
            "key": f"{key}-{card.number}",
        }

    @extend_schema_field(ReminderInfoSerializer(allow_null=True))
    def get_reminder(self, task: Task) -> dict | None:
        """How the bot chases this task. Only on single-task responses, to keep lists cheap."""
        if not self.context.get("detail") or not task.is_open or task.due_at is None:
            return None
        policy = policy_for(task)
        personal = task.kind == Task.Kind.PERSONAL
        recipients = [] if personal else escalation_recipients(task)
        return {
            "every_minutes": policy.repeat_every_minutes,
            "sent": task.reminders_sent,
            "max_reminders": policy.max_reminders,
            "escalate_after": 0 if personal else policy.escalate_after,
            "next_at": task.next_reminder_at,
            "escalated_at": task.escalated_at,
            "escalate_to": str(recipients[0]) if len(recipients) == 1 else None,
            "snooze_minutes": policy.snooze_minutes,
            "snoozes_left": max(0, policy.max_snoozes - task.snooze_count),
            "snoozed_until": task.snoozed_until,
            "sent_times": list(
                task.reminder_log.filter(
                    kind=ReminderLog.Kind.REMINDER, recipient_id=task.assignee_id, delivered=True
                )
                .order_by("sent_at")
                .values_list("sent_at", flat=True)
            ),
        }

    @extend_schema_field(serializers.ListField(child=serializers.IntegerField(), allow_null=True))
    def get_repeat_weekdays(self, task: Task) -> list[int] | None:
        """0 = Monday … 6 = Sunday, when the task repeats."""
        template = task.template
        return template.weekdays if template is not None and template.is_active else None

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_routine(self, task: Task) -> int | None:
        """The routine (task template) that made this daily task, so the mini app can group a
        routine's runs; null for one-off work and for a person's own repeating task."""
        return task.template_id if task.kind == Task.Kind.DAILY else None

    def get_is_overdue(self, task: Task) -> bool:
        return task.is_overdue()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_proof_thumb(self, task: Task) -> str | None:
        """A 400 px preview of the proof photo for lists (the photo itself until it's made)."""
        file = task.proof_thumb or task.proof_photo
        if not file:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(file.url) if request else file.url

    @extend_schema_field(serializers.ListField(child=serializers.ChoiceField(list(rules.Action))))
    def get_actions(self, task: Task) -> list[str]:
        """What the signed-in member may do with this task right now."""
        return [str(a) for a in rules.allowed_actions(task, self.context["membership"])]


class CalendarDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    total = serializers.IntegerField()
    done = serializers.IntegerField()
    review = serializers.IntegerField()
    open = serializers.IntegerField()
    late = serializers.IntegerField()


class CalendarSerializer(serializers.Serializer):
    days = CalendarDaySerializer(many=True, help_text="Only days with something due.")
    tasks = TaskSerializer(many=True)


CALENDAR_LIMIT = 200


def _calendar_range(params) -> tuple[date, date]:
    try:
        start = date.fromisoformat(params.get("from", ""))
        end = date.fromisoformat(params.get("to", ""))
    except ValueError:
        raise serializers.ValidationError(
            {"from": [_("Give from and to as YYYY-MM-DD.")]}
        ) from None
    if end < start or (end - start).days > 41:
        raise serializers.ValidationError(
            {"to": [_("Pick up to 42 days, the last after the first.")]}
        )
    return start, end


class TaskCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(allow_blank=True, default="")
    assignee_id = serializers.IntegerField(
        allow_null=True, default=None, help_text="Leave empty for a personal task."
    )
    due_at = serializers.DateTimeField(allow_null=True, default=None)
    priority = serializers.ChoiceField(Task.Priority.choices, default=Task.Priority.NORMAL)
    proof = serializers.ChoiceField(Proof.choices, default=Proof.NONE)
    needs_confirmation = serializers.BooleanField(
        allow_null=True,
        default=None,
        help_text=REVIEW_RULE_HELP,
    )
    checklist = serializers.ListField(
        child=serializers.CharField(max_length=200), default=list, max_length=50
    )
    repeat = serializers.ChoiceField(
        Repeat.choices, default=Repeat.NONE, help_text="Personal tasks only; needs due_at."
    )


class TaskUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(allow_blank=True, required=False)
    due_at = serializers.DateTimeField(allow_null=True, required=False)
    priority = serializers.ChoiceField(Task.Priority.choices, required=False)


class CompleteSerializer(serializers.Serializer):
    proof_text = serializers.CharField(allow_blank=True, default="")
    proof_photo = serializers.FileField(required=False, allow_null=True)

    def validate_proof_photo(self, photo):
        """Decoded and re-encoded as a JPEG with a server-chosen name; anything that isn't a
        picture (an SVG, an HTML page) is refused, whatever its name or content type says."""
        if photo is None:
            return photo
        try:
            return uploads.sanitize_image(photo, max_bytes=MAX_PHOTO_BYTES)
        except uploads.InvalidUpload as exc:
            raise serializers.ValidationError(str(exc)) from exc


class ReturnSerializer(serializers.Serializer):
    reason = serializers.CharField()


class ConfirmManySerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=100
    )


class ConfirmManyResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    ok = serializers.BooleanField()
    error = serializers.CharField(allow_blank=True)


class ConfirmManyResponseSerializer(serializers.Serializer):
    done = serializers.IntegerField()
    failed = serializers.IntegerField()
    results = ConfirmManyResultSerializer(many=True)


class CancelSerializer(serializers.Serializer):
    stop_repeating = serializers.BooleanField(default=False)


class ChecklistToggleSerializer(serializers.Serializer):
    is_done = serializers.BooleanField()


class CommentSerializer(serializers.ModelSerializer):
    author = MemberBriefSerializer(allow_null=True, read_only=True)
    mentions = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
        max_length=services.MAX_MENTIONS,
        help_text="Membership ids of people to notify: on the task or working in its branch.",
    )

    class Meta:
        model = TaskComment
        fields = ("id", "author", "text", "created_at", "mentions")
        read_only_fields = ("id", "author", "created_at")


class TaskParseInputSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=500, allow_blank=True)


class TaskParseSerializer(serializers.Serializer):
    title = serializers.CharField(help_text="What was typed without the words read as a date.")
    due_at = serializers.DateTimeField(allow_null=True)
    due_label = serializers.CharField(
        allow_null=True,
        help_text="Ready to show in the person's language: Ertaga, 22-oktabr (payshanba), 18:00.",
    )
    priority = serializers.ChoiceField(Task.Priority.choices, allow_null=True)
    repeat = serializers.ChoiceField(
        [Repeat.DAILY, Repeat.WEEKDAYS, Repeat.WEEKLY], allow_null=True
    )
    repeat_weekdays = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6),
        allow_null=True,
        help_text="0 = Monday; for weekly, the due day's weekday.",
    )
    rolled = serializers.BooleanField(
        default=False,
        help_text="A time alone that had already passed today: due_at is that time tomorrow.",
    )
    past = serializers.BooleanField(
        default=False,
        help_text='The typed moment has already passed ("bugun 01:00" at 03:00): due_at is '
        "empty; offer passed_at's time tomorrow, as the bot does.",
    )
    passed_at = serializers.DateTimeField(
        allow_null=True, default=None, help_text="That moment, when past is true."
    )


class SnoozeSerializer(serializers.Serializer):
    preset = serializers.ChoiceField(
        services.SNOOZE_PRESETS,
        required=False,
        allow_null=True,
        help_text="15m or 1h hold the reminders (the deadline stays); tomorrow_morning moves "
        "one's own task to 09:00 tomorrow. Empty: the policy's own length.",
    )


class BlockerReportSerializer(serializers.Serializer):
    reason_code = serializers.ChoiceField(Task.Blocker.choices)
    note = serializers.CharField(allow_blank=True, default="", max_length=300)


class BlockerResolveSerializer(serializers.Serializer):
    action = serializers.ChoiceField(services.BlockerAction.ALL)
    assignee_id = serializers.IntegerField(required=False, allow_null=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)


class ExtensionRequestSerializer(serializers.Serializer):
    until = serializers.DateTimeField()
    note = serializers.CharField(allow_blank=True, default="", max_length=300)


class ExtensionDecideSerializer(serializers.Serializer):
    approve = serializers.BooleanField()


class ParseThrottle(UserRateThrottle):
    """Quick add parses as people type (after a 250 ms pause): generous, but bounded."""

    scope = "task_parse"
    rate = "120/min"


def parsed(text: str, company) -> dict:
    """What `text` says about when, in the company's time and the caller's language (contract 1
    of the task-polish backlog; the employee and owner APIs both answer with this)."""
    local_now = timezone.localtime(timezone.now(), ZoneInfo(company.timezone))
    lang = translation.get_language()
    found = quickadd.parse(text, now=local_now, lang=lang)
    due = found.due_at
    return {
        "title": found.title,
        "due_at": due,
        "due_label": dates.due_label(due, local_now, lang) if due else None,
        "priority": found.priority,
        "repeat": found.repeat,
        "repeat_weekdays": list(found.repeat_weekdays) if found.repeat_weekdays else None,
        "rolled": found.rolled,
        "past": found.past,
        "passed_at": found.passed,
    }


class TaskViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Tasks of one company, as the signed-in member may see them."""

    permission_classes = (IsAuthenticated, IsCompanyMember)
    serializer_class = TaskSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Task.objects.none()
        member = self.membership
        scope = self.request.query_params.get("scope")
        if scope == "today":
            tasks = queries.todays_tasks(member, timezone.now())
        elif scope == "board":
            tasks = queries.board_tasks(member, timezone.now())
        elif scope == "review":
            tasks = queries.awaiting_review_by(member)
        else:
            tasks = queries.visible_tasks(member)
            if scope == "mine":
                tasks = tasks.filter(assignee=member)
            elif scope == "created":
                tasks = tasks.filter(created_by=member).exclude(assignee=member)
        if self.request.query_params.get("given_by") == "me":
            tasks = tasks.filter(created_by=member).exclude(assignee=member)
        if statuses := self.request.query_params.get("status"):
            tasks = tasks.filter(status__in=statuses.split(","))
        if kind := self.request.query_params.get("kind"):
            tasks = tasks.filter(kind=kind)
        if q := self.request.query_params.get("q", "").strip()[:100]:
            tasks = tasks.filter(Q(title__icontains=q) | Q(description__icontains=q))
        return tasks.prefetch_related("checklist")

    def get_serializer_context(self):
        return super().get_serializer_context() | {
            "membership": getattr(self, "membership", None),
            "detail": self.action != "list",
        }

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "scope",
                enum=["today", "board", "mine", "created", "review"],
                description=(
                    "today: open tasks due today or late; board: your open tasks plus "
                    "today's finished; review: waiting for you to check."
                ),
            ),
            OpenApiParameter("status", description="Comma-separated statuses."),
            OpenApiParameter("kind", enum=list(Task.Kind.values)),
            OpenApiParameter("q", description="Words in the title or description."),
            OpenApiParameter(
                "given_by", enum=["me"], description="me: tasks I gave to someone else."
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        """One task. The assignee opening it the first time marks it seen (`seen_at`)."""
        task = self.get_object()
        services.mark_seen(task, by=self.membership)
        return Response(TaskSerializer(task, context=self.get_serializer_context()).data)

    @extend_schema(request=TaskParseInputSerializer, responses=TaskParseSerializer)
    @action(detail=False, methods=["post"], throttle_classes=[ParseThrottle])
    def parse(self, request, company_id):
        """What a quick-add text says (a deadline, a repeat, urgency) and the title without
        those words. Nothing is saved: the client sends `due_at` when it creates the task."""
        text = self._validated(TaskParseInputSerializer)["text"]
        return Response(TaskParseSerializer(parsed(text, self.membership.company)).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("from", required=True, description="First day, YYYY-MM-DD."),
            OpenApiParameter("to", required=True, description="Last day, YYYY-MM-DD (≤ 42 days)."),
        ],
        responses=CalendarSerializer,
    )
    @action(detail=False, methods=["get"])
    def calendar(self, request, company_id):
        """The signed-in member's own tasks due between two days, with counts per day (the
        mini app's week calendar)."""
        start, end = _calendar_range(request.query_params)
        mine = queries.visible_tasks(self.membership).filter(assignee=self.membership)
        data = dashboard.calendar(mine, self.membership.company, start, end, timezone.now())
        tasks = data["items"][:CALENDAR_LIMIT]
        return Response(
            {
                "days": data["days"],
                "tasks": TaskSerializer(
                    tasks, many=True, context=self.get_serializer_context() | {"detail": False}
                ).data,
            }
        )

    @extend_schema(request=TaskCreateSerializer, responses={201: TaskSerializer})
    def create(self, request, company_id):
        data = self._validated(TaskCreateSerializer)
        assignee = self._member(data.pop("assignee_id"))
        task = services.create_task(by=self.membership, assignee=assignee, **data)
        return Response(self._serialize(task), status=status.HTTP_201_CREATED)

    @extend_schema(request=TaskUpdateSerializer, responses=TaskSerializer)
    def partial_update(self, request, company_id, pk):
        changes = self._validated(TaskUpdateSerializer)
        task = services.update_task(self.get_object(), by=self.membership, **changes)
        return Response(self._serialize(task))

    @extend_schema(request=None, responses=TaskSerializer)
    @action(detail=True, methods=["post"])
    def start(self, request, company_id, pk):
        return self._respond(services.start_task(self.get_object(), by=self.membership))

    @extend_schema(request=CompleteSerializer, responses=TaskSerializer)
    @action(detail=True, methods=["post"], parser_classes=(MultiPartParser, FormParser, JSONParser))
    def complete(self, request, company_id, pk):
        data = self._validated(CompleteSerializer)
        task = services.complete_task(
            self.get_object(),
            by=self.membership,
            proof_text=data["proof_text"],
            proof_photo=data.get("proof_photo"),
        )
        return self._respond(task)

    @extend_schema(request=None, responses=TaskSerializer)
    @action(detail=True, methods=["post"])
    def reopen(self, request, company_id, pk):
        """Undo a Done: the person who did it, within a minute, before anyone accepted it."""
        return self._respond(services.reopen_task(self.get_object(), by=self.membership))

    @extend_schema(request=SnoozeSerializer, responses=TaskSerializer)
    @action(detail=True, methods=["post"])
    def snooze(self, request, company_id, pk):
        preset = self._validated(SnoozeSerializer).get("preset")
        task = services.snooze_task(self.get_object(), by=self.membership, preset=preset)
        return self._respond(task)

    @extend_schema(request=BlockerReportSerializer, responses=TaskSerializer)
    @action(detail=True, methods=["post"])
    def blocker(self, request, company_id, pk):
        """ "Can't do it": the reminders pause and whoever gave it hears, with the reason."""
        data = self._validated(BlockerReportSerializer)
        task = services.report_blocker(
            self.get_object(),
            by=self.membership,
            reason_code=data["reason_code"],
            note=data["note"],
        )
        return self._respond(task)

    @extend_schema(request=BlockerResolveSerializer, responses=TaskSerializer)
    @action(detail=True, methods=["post"], url_path="blocker/resolve")
    def resolve_blocker(self, request, company_id, pk):
        """Answer a "can't do it": someone else (`assignee_id`), a new deadline (`due_at`) or
        cancel. Whoever gave it, or holds tasks.assign or tasks.confirm for its branch."""
        data = self._validated(BlockerResolveSerializer)
        task = services.resolve_blocker(
            self.get_object(),
            by=self.membership,
            action=data["action"],
            assignee_id=data.get("assignee_id"),
            due_at=data.get("due_at"),
        )
        return self._respond(task)

    @extend_schema(request=ExtensionRequestSerializer, responses=TaskSerializer)
    @action(detail=True, methods=["post"])
    def extension(self, request, company_id, pk):
        """ "Need more time": ask whoever gave it for a later deadline (`until`)."""
        data = self._validated(ExtensionRequestSerializer)
        task = services.request_extension(
            self.get_object(), by=self.membership, until=data["until"], note=data["note"]
        )
        return self._respond(task)

    @extend_schema(request=ExtensionDecideSerializer, responses=TaskSerializer)
    @action(detail=True, methods=["post"], url_path="extension/decide")
    def decide_extension(self, request, company_id, pk):
        """Approve (the deadline moves) or decline (it stays) a request for more time."""
        approve = self._validated(ExtensionDecideSerializer)["approve"]
        task = services.decide_extension(self.get_object(), by=self.membership, approve=approve)
        return self._respond(task)

    @extend_schema(request=None, responses=TaskSerializer)
    @action(detail=True, methods=["post"])
    def confirm(self, request, company_id, pk):
        return self._respond(services.confirm_task(self.get_object(), by=self.membership))

    # Its own operation id: the generated one is the same as confirming one task's.
    @extend_schema(
        operation_id="v1_companies_tasks_confirm_many",
        request=ConfirmManySerializer,
        responses=ConfirmManyResponseSerializer,
    )
    @action(detail=False, methods=["post"], url_path="confirm", url_name="confirm-many")
    def confirm_many(self, request, company_id):
        """Confirm several finished tasks at once (a routine's runs, from the mini app's "Confirm
        all"). Each is confirmed on its own, by the same rules and with the same audit row as
        confirming it alone: only someone who may check it, never the person who did it. One
        refusal never stops the others; the result says how each went."""
        ids = self._validated(ConfirmManySerializer)["ids"]
        results = services.bulk(
            by=self.membership, ids=ids, action=services.BulkAction.CONFIRM, payload={}
        )
        done = sum(result.ok for result in results)
        return Response(
            {
                "done": done,
                "failed": len(results) - done,
                "results": [{"id": r.id, "ok": r.ok, "error": r.error} for r in results],
            }
        )

    @extend_schema(request=ReturnSerializer, responses=TaskSerializer)
    @action(detail=True, methods=["post"], url_path="return")
    def send_back(self, request, company_id, pk):
        reason = self._validated(ReturnSerializer)["reason"]
        task = services.return_task(self.get_object(), by=self.membership, reason=reason)
        return self._respond(task)

    @extend_schema(request=CancelSerializer, responses=TaskSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, company_id, pk):
        stop_repeating = self._validated(CancelSerializer)["stop_repeating"]
        task = services.cancel_task(
            self.get_object(), by=self.membership, stop_repeating=stop_repeating
        )
        return self._respond(task)

    @extend_schema(request=ChecklistToggleSerializer, responses=TaskSerializer)
    @action(detail=True, methods=["post"], url_path=r"checklist/(?P<item_id>\d+)")
    def checklist_item(self, request, company_id, pk, item_id):
        task = self.get_object()
        item = task.checklist.filter(pk=item_id).first()
        if item is None:
            raise DomainError(_("That checklist item doesn't exist."))
        done = self._validated(ChecklistToggleSerializer)["is_done"]
        services.toggle_checklist_item(item, by=self.membership, done=done)
        return self._respond(task)

    @extend_schema(methods=["GET"], responses=CommentSerializer(many=True))
    @extend_schema(methods=["POST"], request=CommentSerializer, responses={201: CommentSerializer})
    @action(detail=True, methods=["get", "post"])
    def comments(self, request, company_id, pk):
        task = self.get_object()
        if request.method == "GET":
            comments = task.comments.select_related("author__user", "author__position")
            return Response(CommentSerializer(comments, many=True).data)
        data = self._validated(CommentSerializer)
        comment = services.add_comment(
            task, by=self.membership, text=data["text"], mentions=data.get("mentions", [])
        )
        return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)

    def _validated(self, serializer_class) -> dict:
        serializer = serializer_class(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        return dict(serializer.validated_data)

    def _member(self, member_id: int | None) -> Membership | None:
        if member_id is None:
            return None
        member = (
            Membership.objects.for_company(self.membership.company)
            .select_related("user", "role", "company")
            .filter(pk=member_id)
            .first()
        )
        if member is None:
            raise DomainError(_("That person isn't in your company."))
        return member

    def _serialize(self, task: Task) -> dict:
        task = queries.visible_tasks(self.membership).prefetch_related("checklist").get(pk=task.pk)
        return TaskSerializer(task, context=self.get_serializer_context()).data

    def _respond(self, task: Task) -> Response:
        return Response(self._serialize(task))


class TaskTemplateSerializer(serializers.ModelSerializer):
    assignee_ids = serializers.PrimaryKeyRelatedField(
        source="assignees", many=True, required=False, queryset=Membership.objects.none()
    )
    position_ids = serializers.PrimaryKeyRelatedField(
        source="positions", many=True, required=False, queryset=Position.objects.none()
    )
    weekdays = serializers.ListField(
        child=serializers.ChoiceField(Weekday.choices), allow_empty=False, required=False
    )
    needs_confirmation = serializers.BooleanField(
        allow_null=True,
        required=False,
        help_text=REVIEW_RULE_HELP,
    )

    class Meta:
        model = TaskTemplate
        fields = (
            "id",
            "title",
            "description",
            "weekdays",
            "due_time",
            "assignee_ids",
            "position_ids",
            "proof",
            "needs_confirmation",
            "is_active",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only people and positions of this company can be picked.
        if company := self.context.get("company"):
            self.fields["assignee_ids"].child_relation.queryset = Membership.objects.for_company(
                company
            ).filter(status=Membership.Status.APPROVED)
            self.fields["position_ids"].child_relation.queryset = Position.objects.for_company(
                company
            )

    def validate_weekdays(self, weekdays):
        return sorted(set(weekdays))


class TaskTemplateViewSet(viewsets.ModelViewSet):
    """Recurring tasks. Needs tasks.templates."""

    permission_classes = (IsAuthenticated, IsCompanyMember, requires(Perm.TASKS_TEMPLATES))
    serializer_class = TaskTemplateSerializer
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TaskTemplate.objects.none()
        # Employees' own repeating tasks are theirs, not part of the company's templates.
        return (
            TaskTemplate.objects.for_company(self.membership.company)
            .filter(personal=False, onboarding=False)
            .prefetch_related("assignees", "positions")
        )

    def get_serializer_context(self):
        membership = getattr(self, "membership", None)
        return super().get_serializer_context() | {
            "company": membership.company if membership else None
        }

    @transaction.atomic
    def perform_create(self, serializer):
        template = serializer.save(company=self.membership.company, created_by=self.membership)
        self._audit(AuditLog.Action.TEMPLATE_CREATED, template)

    @transaction.atomic
    def perform_update(self, serializer):
        before = audit.snapshot(serializer.instance)
        template = serializer.save()
        if changes := audit.diff(before, audit.snapshot(template)):
            self._audit(AuditLog.Action.TEMPLATE_CHANGED, template, changes=changes)

    @transaction.atomic
    def perform_destroy(self, template):
        self._audit(AuditLog.Action.TEMPLATE_DELETED, template)
        template.delete()

    def _audit(self, action: AuditLog.Action, template: TaskTemplate, **details) -> None:
        audit.record(
            action,
            company_id=template.company_id,
            actor=self.request.user,
            target=template,
            **details,
        )


class DaySerializer(serializers.Serializer):
    date = serializers.DateField()
    state = serializers.ChoiceField(
        ["done", "missed", "free", "today"],
        help_text="done: all finished that day; missed: something wasn't; free: nothing was due.",
    )


class OffTodaySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(["holiday", "time_off"])
    name = serializers.CharField(help_text="The holiday's name; empty for time off.")
    until = serializers.DateField(help_text="The last day off.")


class SummarySerializer(serializers.Serializer):
    today_total = serializers.IntegerField()
    today_done = serializers.IntegerField()
    late = serializers.IntegerField()
    streak_days = serializers.IntegerField()
    week = DaySerializer(many=True, help_text="The last seven days, oldest first.")
    month_done = serializers.IntegerField(help_text="Tasks finished this calendar month.")
    month_on_time_percent = serializers.IntegerField(
        allow_null=True, help_text="Of this month's tasks with a deadline, finished in time."
    )
    quiet_from = serializers.TimeField(allow_null=True, help_text="No reminders from…")
    quiet_until = serializers.TimeField(allow_null=True, help_text="…until.")
    unread_activity = serializers.IntegerField()
    awaiting_review = serializers.IntegerField()
    off_today = OffTodaySerializer(
        allow_null=True, help_text="Set when today is a holiday or the person's time off."
    )


class SummaryView(APIView):
    """Home screen numbers for the signed-in member."""

    permission_classes = (IsAuthenticated, IsCompanyMember)

    @extend_schema(responses=SummarySerializer)
    def get(self, request, company_id):
        return Response(SummarySerializer(stats.summary(self.membership, timezone.now())).data)


class TaskBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ("id", "title", "status")
        read_only_fields = fields


class ActivitySerializer(serializers.ModelSerializer):
    actor = MemberBriefSerializer(allow_null=True)
    task = TaskBriefSerializer()
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = ("id", "kind", "task", "actor", "text", "is_read", "created_at")
        read_only_fields = fields

    def get_is_read(self, activity: Activity) -> bool:
        return activity.read_at is not None


class MarkedSerializer(serializers.Serializer):
    marked = serializers.IntegerField()


class ActivityViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """The signed-in member's feed, newest first."""

    permission_classes = (IsAuthenticated, IsCompanyMember)
    serializer_class = ActivitySerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Activity.objects.none()
        return Activity.objects.filter(recipient=self.membership).select_related(
            "task", "actor__user", "actor__position"
        )

    @extend_schema(request=None, responses=MarkedSerializer)
    @action(detail=False, methods=["post"])
    def read(self, request, company_id):
        """Mark the whole feed as read."""
        return Response({"marked": services.mark_feed_read(self.membership)})
