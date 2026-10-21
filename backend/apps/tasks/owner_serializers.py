"""Shapes of the tasks owner endpoints (docs/PLAN-OWNER.md §4.5). Money is a string, moments are
ISO 8601, days company-local `YYYY-MM-DD`; people are `{id, name, photo_url}` (their membership)."""

from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.money import MoneySerializerField
from apps.members.models import Membership
from apps.reminders.policies import escalation_recipients, policy_for
from apps.tasks import generation, rules
from apps.tasks.models import ChecklistItem, Proof, Task, TaskComment, TaskTemplate


def person(member: Membership | None) -> dict | None:
    """A person as the dashboard's PersonRef reads them."""
    if member is None:
        return None
    user = member.user
    return {
        "id": member.pk,
        "name": str(member),
        "photo_url": user.photo.url if user.photo else None,
        "position": member.position.name if member.position_id else None,
    }


def file_url(file) -> str | None:
    return file.url if file else None


class PersonRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)
    position = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "TasksPersonRef"


class BranchRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()

    class Meta:
        ref_name = "TasksBranchRef"


class NamedRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class ProjectRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    key = serializers.CharField()
    name = serializers.CharField()
    # The card's number on the project's board ("OPEN-14" is key and number); null until the
    # board has numbered it.
    number = serializers.IntegerField(allow_null=True)


class ProgressSerializer(serializers.Serializer):
    done = serializers.IntegerField()
    total = serializers.IntegerField()


class TaskRowSerializer(serializers.ModelSerializer):
    """A task in the owner's table, board, calendar and photo wall."""

    assignee = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    branch = serializers.SerializerMethodField()
    routine = serializers.SerializerMethodField()
    project = serializers.SerializerMethodField()
    checklist = serializers.SerializerMethodField()
    has_proof = serializers.SerializerMethodField()
    proof_thumb = serializers.SerializerMethodField()
    proof_photo = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    reward = MoneySerializerField(allow_null=True)
    moves = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = (
            "id",
            "kind",
            "title",
            "status",
            "priority",
            "due_at",
            "for_date",
            "is_overdue",
            "assignee",
            "created_by",
            "branch",
            "routine",
            "project",
            "proof",
            "needs_confirmation",
            "has_proof",
            "proof_thumb",
            "proof_photo",
            "checklist",
            "reward",
            "started_at",
            "completed_at",
            "confirmed_at",
            "created_at",
            "moves",
        )
        read_only_fields = fields

    @extend_schema_field(PersonRefSerializer)
    def get_assignee(self, task: Task) -> dict:
        return person(task.assignee)

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_created_by(self, task: Task) -> dict | None:
        return person(task.created_by)

    @extend_schema_field(BranchRefSerializer(allow_null=True))
    def get_branch(self, task: Task) -> dict | None:
        branch = task.branch
        return {"id": branch.pk, "name": branch.name, "code": branch.code} if branch else None

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_routine(self, task: Task) -> dict | None:
        template = task.template
        if template is None or template.personal:
            return None
        return {"id": template.pk, "title": template.title, "onboarding": template.onboarding}

    @extend_schema_field(ProjectRefSerializer(allow_null=True))
    def get_project(self, task: Task) -> dict | None:
        project = task.project if task.project_id else None
        if project is None:
            return None
        card = getattr(task, "card", None)  # apps.projects' Card, loaded with the task
        number = card.number if card is not None else None
        return {"id": project.pk, "key": project.key, "name": project.name, "number": number}

    @extend_schema_field(ProgressSerializer)
    def get_checklist(self, task: Task) -> dict:
        items = list(task.checklist.all())
        return {"done": sum(item.is_done for item in items), "total": len(items)}

    def get_has_proof(self, task: Task) -> bool:
        return bool(task.proof_photo) or bool(task.proof_text)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_proof_thumb(self, task: Task) -> str | None:
        return file_url(task.proof_thumb) or file_url(task.proof_photo)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_proof_photo(self, task: Task) -> str | None:
        return file_url(task.proof_photo)

    def get_is_overdue(self, task: Task) -> bool:
        return task.is_overdue(self.context.get("now"))

    @extend_schema_field(serializers.ListField(child=serializers.ChoiceField(list(rules.Column))))
    def get_moves(self, task: Task) -> list[str]:
        """Board columns the caller may drag this card to."""
        member = self.context.get("membership")
        return rules.board_moves(task, member) if member is not None else []


class TaskReviewSerializer(TaskRowSerializer):
    """A card of the reviews queue: the row plus what was written and reported. No comments or
    reminder plan, so the queue answers in a fixed number of queries."""

    class Meta(TaskRowSerializer.Meta):
        fields = (*TaskRowSerializer.Meta.fields, "description", "proof_text")
        read_only_fields = fields


class ChecklistRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChecklistItem
        fields = ("id", "text", "is_done")
        read_only_fields = fields


class CommentRowSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = TaskComment
        fields = ("id", "author", "text", "created_at")
        read_only_fields = fields

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_author(self, comment: TaskComment) -> dict | None:
        return person(comment.author)


class ReminderPlanSerializer(serializers.Serializer):
    policy = NamedRefSerializer()
    heads_up_minutes = serializers.IntegerField()
    every_minutes = serializers.IntegerField()
    max_reminders = serializers.IntegerField(help_text="0 = until it's done.")
    escalate_after = serializers.IntegerField(help_text="0 = nobody is told.")
    sent = serializers.IntegerField()
    next_at = serializers.DateTimeField(allow_null=True)
    escalated_at = serializers.DateTimeField(allow_null=True)
    escalate_to = PersonRefSerializer(many=True)
    snoozed_until = serializers.DateTimeField(allow_null=True)
    snoozes_left = serializers.IntegerField()


class TaskDetailSerializer(TaskRowSerializer):
    """Everything the task drawer shows."""

    confirmed_by = serializers.SerializerMethodField()
    checklist_items = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    reminders = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()

    class Meta(TaskRowSerializer.Meta):
        fields = (
            *TaskRowSerializer.Meta.fields,
            "description",
            "proof_text",
            "confirmed_by",
            "checklist_items",
            "comments",
            "reminders",
            "actions",
            "last_nudged_at",
        )
        read_only_fields = fields

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_confirmed_by(self, task: Task) -> dict | None:
        return person(task.confirmed_by)

    @extend_schema_field(ChecklistRowSerializer(many=True))
    def get_checklist_items(self, task: Task) -> list[dict]:
        return ChecklistRowSerializer(task.checklist.all(), many=True).data

    @extend_schema_field(CommentRowSerializer(many=True))
    def get_comments(self, task: Task) -> list[dict]:
        comments = task.comments.select_related("author__user", "author__position")
        return CommentRowSerializer(comments, many=True).data

    @extend_schema_field(ReminderPlanSerializer(allow_null=True))
    def get_reminders(self, task: Task) -> dict | None:
        """How the bot chases it; None for work without a deadline."""
        if task.due_at is None:
            return None
        policy = policy_for(task)
        personal = task.kind == Task.Kind.PERSONAL
        return {
            "policy": {"id": policy.pk, "name": policy.name},
            "heads_up_minutes": policy.heads_up_minutes,
            "every_minutes": policy.repeat_every_minutes,
            "max_reminders": 1 if personal else policy.max_reminders,
            "escalate_after": 0 if personal else policy.escalate_after,
            "sent": task.reminders_sent,
            "next_at": task.next_reminder_at if task.is_open else None,
            "escalated_at": task.escalated_at,
            "escalate_to": [] if personal else [person(m) for m in escalation_recipients(task)],
            "snoozed_until": task.snoozed_until,
            "snoozes_left": max(0, policy.max_snoozes - task.snooze_count),
        }

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_actions(self, task: Task) -> list[str]:
        """What the caller may do: start, complete, confirm, return, edit, cancel, reassign,
        nudge, comment."""
        return rules.owner_actions(task, self.context["membership"])


# Writes ------------------------------------------------------------------------------------


class TaskCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(allow_blank=True, default="")
    due_at = serializers.DateTimeField(allow_null=True, default=None)
    priority = serializers.ChoiceField(Task.Priority.choices, default=Task.Priority.NORMAL)
    proof = serializers.ChoiceField(Proof.choices, default=Proof.NONE)
    needs_confirmation = serializers.BooleanField(default=False)
    checklist = serializers.ListField(
        child=serializers.CharField(max_length=200), default=list, max_length=50
    )
    reward = MoneySerializerField(allow_null=True, default=None)
    assignee_ids = serializers.ListField(child=serializers.IntegerField(), default=list)
    position_ids = serializers.ListField(child=serializers.IntegerField(), default=list)
    branch_ids = serializers.ListField(child=serializers.IntegerField(), default=list)

    def validate(self, attrs):
        if not (attrs["assignee_ids"] or attrs["position_ids"] or attrs["branch_ids"]):
            raise serializers.ValidationError(
                {"assignee_ids": [_("Pick people, positions or branches.")]}
            )
        return attrs


class TaskUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(allow_blank=True, required=False)
    due_at = serializers.DateTimeField(allow_null=True, required=False)
    priority = serializers.ChoiceField(Task.Priority.choices, required=False)
    reward = MoneySerializerField(allow_null=True, required=False)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000)

    class Meta:
        ref_name = "TasksReason"


class ReassignSerializer(serializers.Serializer):
    assignee_id = serializers.IntegerField()


class CommentSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=2000)


class MoveSerializer(serializers.Serializer):
    to = serializers.ChoiceField(list(rules.Column))
    reason = serializers.CharField(allow_blank=True, default="", max_length=1000)


class BulkPayloadSerializer(serializers.Serializer):
    assignee_id = serializers.IntegerField(required=False)
    due_at = serializers.DateTimeField(required=False)
    shift_days = serializers.IntegerField(required=False, min_value=-60, max_value=60)
    priority = serializers.ChoiceField(Task.Priority.choices, required=False)


class BulkSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), min_length=1, max_length=200)
    action = serializers.ChoiceField(
        ["reassign", "reschedule", "priority", "cancel", "confirm", "nudge"]
    )
    payload = BulkPayloadSerializer(default=dict)

    class Meta:
        ref_name = "TasksBulk"

    def validate(self, attrs):
        payload, action = attrs["payload"], attrs["action"]
        needs = {
            "reassign": ("assignee_id",),
            "priority": ("priority",),
        }.get(action, ())
        for name in needs:
            if name not in payload:
                raise serializers.ValidationError(
                    {"payload": [_("%(name)s is required.") % {"name": name}]}
                )
        if action == "reschedule" and "due_at" not in payload and "shift_days" not in payload:
            raise serializers.ValidationError({"payload": [_("Give due_at or shift_days.")]})
        return attrs


class BulkResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    ok = serializers.BooleanField()
    error = serializers.CharField(allow_blank=True)

    class Meta:
        ref_name = "TasksBulkResult"


class BulkResponseSerializer(serializers.Serializer):
    done = serializers.IntegerField()
    failed = serializers.IntegerField()
    results = BulkResultSerializer(many=True)


# Routines ----------------------------------------------------------------------------------


class RoutineGiveSerializer(serializers.Serializer):
    people = serializers.IntegerField()
    due_at = serializers.DateTimeField()


class RoutineTodaySerializer(serializers.Serializer):
    """Today, on a routine's own page: why it makes no tasks today (null when it does), and
    "Give today's task now" (who would get it, by when) when it was made after today's
    deadline."""

    date = serializers.DateField()
    reason = serializers.CharField(allow_null=True)
    give = RoutineGiveSerializer(allow_null=True)


class RoutineSerializer(serializers.ModelSerializer):
    branch = serializers.SerializerMethodField()
    assignees = serializers.SerializerMethodField()
    positions = serializers.SerializerMethodField()
    reminder_policy = serializers.SerializerMethodField()
    escalate_to = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()
    next_run = serializers.SerializerMethodField()
    today = serializers.SerializerMethodField()

    class Meta:
        model = TaskTemplate
        fields = (
            "id",
            "title",
            "description",
            "weekdays",
            "due_time",
            "starts_on",
            "is_active",
            "onboarding",
            "due_after_days",
            "proof",
            "needs_confirmation",
            "checklist",
            "branch",
            "assignees",
            "positions",
            "reminder_policy",
            "escalate_to",
            "stats",
            "next_run",
            "today",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(BranchRefSerializer(allow_null=True))
    def get_branch(self, template: TaskTemplate) -> dict | None:
        branch = template.branch
        return {"id": branch.pk, "name": branch.name, "code": branch.code} if branch else None

    @extend_schema_field(PersonRefSerializer(many=True))
    def get_assignees(self, template: TaskTemplate) -> list[dict]:
        return [person(member) for member in template.assignees.all()]

    @extend_schema_field(NamedRefSerializer(many=True))
    def get_positions(self, template: TaskTemplate) -> list[dict]:
        return [{"id": p.pk, "name": p.name} for p in template.positions.all()]

    @extend_schema_field(NamedRefSerializer(allow_null=True))
    def get_reminder_policy(self, template: TaskTemplate) -> dict | None:
        policy = template.reminder_policy
        return {"id": policy.pk, "name": policy.name} if policy else None

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_escalate_to(self, template: TaskTemplate) -> dict | None:
        return person(template.escalate_to)

    @extend_schema_field(serializers.DictField())
    def get_stats(self, template: TaskTemplate) -> dict | None:
        """30-day completion and a 14-day sparkline, when the list computed them."""
        return self.context.get("stats", {}).get(template.pk)

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_next_run(self, template: TaskTemplate) -> str | None:
        """When its next tasks are due, by daily generation's rules (holidays included); null
        for paused and onboarding routines."""
        runs = self.context.get("next_runs")
        if runs is not None and template.pk in runs:
            value = runs[template.pk]
        else:
            value = generation.next_run(template, self.context.get("now") or timezone.now())
        return serializers.DateTimeField().to_representation(value) if value else None

    @extend_schema_field(RoutineTodaySerializer(allow_null=True))
    def get_today(self, template: TaskTemplate) -> dict | None:
        """Only on a routine's own answers (detail, create, edit), not in the list."""
        today = self.context.get("today", {}).get(template.pk)
        return RoutineTodaySerializer(today).data if today is not None else None


class RoutineWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(allow_blank=True, required=False)
    weekdays = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6), required=False
    )
    due_time = serializers.TimeField(required=False)
    starts_on = serializers.DateField(allow_null=True, required=False)
    is_active = serializers.BooleanField(required=False)
    onboarding = serializers.BooleanField(required=False)
    due_after_days = serializers.IntegerField(min_value=0, max_value=90, required=False)
    proof = serializers.ChoiceField(Proof.choices, required=False)
    needs_confirmation = serializers.BooleanField(required=False)
    checklist = serializers.ListField(
        child=serializers.CharField(max_length=200, allow_blank=True), required=False, max_length=50
    )
    branch_id = serializers.IntegerField(allow_null=True, required=False)
    assignee_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    position_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    reminder_policy_id = serializers.IntegerField(allow_null=True, required=False)
    escalate_to_id = serializers.IntegerField(allow_null=True, required=False)


class GiveTodayInputSerializer(serializers.Serializer):
    due_time = serializers.TimeField(
        required=False, help_text="Today, in the company's timezone. Default: in two hours."
    )


def now_context() -> dict:
    return {"now": timezone.now()}


# Routine work (the Routines page) ----------------------------------------------------------


def routine_ref(template: TaskTemplate) -> dict:
    """A routine as the Routines page's Today, History and To confirm name it."""
    branch = template.branch
    return {
        "id": template.pk,
        "title": template.title,
        "due_time": template.due_time.strftime("%H:%M"),
        "branch": {"id": branch.pk, "name": branch.name, "code": branch.code} if branch else None,
        "proof": template.proof,
        "needs_confirmation": template.needs_confirmation,
        "is_active": template.is_active,
    }


def run_row(task: Task, state: str, member: Membership) -> dict:
    """One person's run of a routine on a day: how it stands (`dashboard.run_state`), when it
    was finished and whether in time, its proof, and whether `member` may confirm it."""
    items = list(task.checklist.all())
    completed = task.completed_at
    branch = task.branch
    return {
        "id": task.pk,
        "member": person(task.assignee),
        "branch": {"id": branch.pk, "name": branch.name, "code": branch.code} if branch else None,
        "state": state,
        "status": task.status,
        "due_at": task.due_at,
        "completed_at": completed,
        "on_time": completed <= task.due_at if completed and task.due_at else None,
        "proof": task.proof,
        "proof_text": task.proof_text,
        "proof_thumb": file_url(task.proof_thumb) or file_url(task.proof_photo),
        "proof_photo": file_url(task.proof_photo),
        "checklist": {"done": sum(item.is_done for item in items), "total": len(items)},
        "can_confirm": task.status == Task.Status.REVIEW and rules.can_review(task, member),
    }
