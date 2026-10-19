from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import DomainError
from apps.members.api import IsCompanyMember, MemberBriefSerializer, requires
from apps.members.models import Membership, Position
from apps.members.permissions import Perm
from apps.tasks import queries, rules, services, stats
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


class TaskSerializer(serializers.ModelSerializer):
    assignee = MemberBriefSerializer()
    created_by = MemberBriefSerializer(allow_null=True)
    checklist = ChecklistItemSerializer(many=True)
    repeat_weekdays = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = (
            "id",
            "kind",
            "title",
            "description",
            "status",
            "priority",
            "due_at",
            "for_date",
            "proof",
            "needs_confirmation",
            "proof_text",
            "proof_photo",
            "assignee",
            "created_by",
            "checklist",
            "repeat_weekdays",
            "started_at",
            "completed_at",
            "confirmed_at",
            "is_overdue",
            "actions",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.IntegerField(), allow_null=True))
    def get_repeat_weekdays(self, task: Task) -> list[int] | None:
        """0 = Monday … 6 = Sunday, when the task repeats."""
        template = task.template
        return template.weekdays if template is not None and template.is_active else None

    def get_is_overdue(self, task: Task) -> bool:
        return task.is_overdue()

    @extend_schema_field(serializers.ListField(child=serializers.ChoiceField(list(rules.Action))))
    def get_actions(self, task: Task) -> list[str]:
        """What the signed-in member may do with this task right now."""
        return [str(a) for a in rules.allowed_actions(task, self.context["membership"])]


class TaskCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(allow_blank=True, default="")
    assignee_id = serializers.IntegerField(
        allow_null=True, default=None, help_text="Leave empty for a personal task."
    )
    due_at = serializers.DateTimeField(allow_null=True, default=None)
    priority = serializers.ChoiceField(Task.Priority.choices, default=Task.Priority.NORMAL)
    proof = serializers.ChoiceField(Proof.choices, default=Proof.NONE)
    needs_confirmation = serializers.BooleanField(default=False)
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
        if photo is None:
            return photo
        if photo.size > MAX_PHOTO_BYTES:
            raise serializers.ValidationError(_("The photo is too large (10 MB at most)."))
        if not (photo.content_type or "").startswith("image/"):
            raise serializers.ValidationError(_("The proof must be an image."))
        return photo


class ReturnSerializer(serializers.Serializer):
    reason = serializers.CharField()


class CancelSerializer(serializers.Serializer):
    stop_repeating = serializers.BooleanField(default=False)


class ChecklistToggleSerializer(serializers.Serializer):
    is_done = serializers.BooleanField()


class CommentSerializer(serializers.ModelSerializer):
    author = MemberBriefSerializer(allow_null=True, read_only=True)

    class Meta:
        model = TaskComment
        fields = ("id", "author", "text", "created_at")
        read_only_fields = ("id", "author", "created_at")


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
        elif scope == "review":
            tasks = queries.awaiting_review_by(member)
        else:
            tasks = queries.visible_tasks(member)
            if scope == "mine":
                tasks = tasks.filter(assignee=member)
            elif scope == "created":
                tasks = tasks.filter(created_by=member).exclude(assignee=member)
        if statuses := self.request.query_params.get("status"):
            tasks = tasks.filter(status__in=statuses.split(","))
        if kind := self.request.query_params.get("kind"):
            tasks = tasks.filter(kind=kind)
        return tasks.prefetch_related("checklist")

    def get_serializer_context(self):
        return super().get_serializer_context() | {"membership": getattr(self, "membership", None)}

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "scope",
                enum=["today", "mine", "created", "review"],
                description="today: open tasks due today or late; review: waiting for you.",
            ),
            OpenApiParameter("status", description="Comma-separated statuses."),
            OpenApiParameter("kind", enum=list(Task.Kind.values)),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

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
    def confirm(self, request, company_id, pk):
        return self._respond(services.confirm_task(self.get_object(), by=self.membership))

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
        text = self._validated(CommentSerializer)["text"]
        comment = services.add_comment(task, by=self.membership, text=text)
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
            .filter(personal=False)
            .prefetch_related("assignees", "positions")
        )

    def get_serializer_context(self):
        membership = getattr(self, "membership", None)
        return super().get_serializer_context() | {
            "company": membership.company if membership else None
        }

    def perform_create(self, serializer):
        serializer.save(company=self.membership.company, created_by=self.membership)


class SummarySerializer(serializers.Serializer):
    today_total = serializers.IntegerField()
    today_done = serializers.IntegerField()
    late = serializers.IntegerField()
    streak_days = serializers.IntegerField()
    unread_activity = serializers.IntegerField()
    awaiting_review = serializers.IntegerField()


class SummaryView(APIView):
    """Home screen numbers for the signed-in member."""

    permission_classes = (IsAuthenticated, IsCompanyMember)

    @extend_schema(responses=SummarySerializer)
    def get(self, request, company_id):
        return Response(stats.summary(self.membership, timezone.now()))


class TaskBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ("id", "title", "status")


class ActivitySerializer(serializers.ModelSerializer):
    actor = MemberBriefSerializer(allow_null=True)
    task = TaskBriefSerializer()
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = ("id", "kind", "task", "actor", "text", "is_read", "created_at")

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
