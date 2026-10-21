"""Shapes of the projects API, shared by the owner endpoints and the mini app's.

Output serializers render plain dicts built by the views (and document them for
drf-spectacular); money is always a string, days are company-local `YYYY-MM-DD`.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework import serializers

from apps.core.money import MoneySerializerField
from apps.members.models import Membership
from apps.projects import queries
from apps.projects.models import (
    Health,
    Label,
    Milestone,
    Project,
    ProjectFile,
    ProjectLink,
    ProjectList,
    ProjectMember,
    ProjectUpdate,
    RunningTimer,
    TimeEntry,
)
from apps.tasks import rules as task_rules
from apps.tasks.models import Proof, Task


class ProjectPriorityField(serializers.CharField):
    """A project's priority (low, normal, high) as a plain string."""

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if value not in Project.Priority.values:
            raise serializers.ValidationError(f"One of {', '.join(Project.Priority.values)}.")
        return value


class TaskPriorityField(serializers.CharField):
    """The task app's priority values as a plain string (see ProjectsCardSerializer.priority)."""

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if value not in Task.Priority.values:
            raise serializers.ValidationError(f"One of {', '.join(Task.Priority.values)}.")
        return value


def money(value) -> str | None:
    return None if value is None else f"{value:.2f}"


def person(member: Membership | None) -> dict | None:
    if member is None:
        return None
    user = member.user
    return {
        "id": member.pk,
        "name": str(member),
        "photo_url": user.photo.url if user.photo else None,
    }


class ProjectsPersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)


class ProjectsRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class ProjectsProgressSerializer(serializers.Serializer):
    done = serializers.IntegerField()
    total = serializers.IntegerField()
    overdue = serializers.IntegerField()
    percent = serializers.IntegerField()


class ProjectsReportedSerializer(serializers.Serializer):
    health = serializers.ChoiceField(Health.choices)
    text = serializers.CharField()
    at = serializers.DateTimeField()
    author = ProjectsPersonSerializer(allow_null=True)


class ProjectsNextMilestoneSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    due_on = serializers.DateField(allow_null=True)


class ProjectItemSerializer(serializers.Serializer):
    """A project on the index (cards or table)."""

    id = serializers.IntegerField()
    key = serializers.CharField()
    name = serializers.CharField()
    color = serializers.CharField()
    icon = serializers.CharField()
    status = serializers.ChoiceField(Project.Status.choices)
    # low, normal, high (a plain string: the task app's priorities own the "priority" enum)
    priority = serializers.CharField()
    visibility = serializers.ChoiceField(Project.Visibility.choices)
    lead = ProjectsPersonSerializer(allow_null=True)
    branch = ProjectsRefSerializer(allow_null=True)
    client = ProjectsRefSerializer(allow_null=True)
    start_on = serializers.DateField(allow_null=True)
    due_on = serializers.DateField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)
    archived_at = serializers.DateTimeField(allow_null=True)
    progress = ProjectsProgressSerializer()
    health = serializers.ChoiceField(Health.choices, allow_null=True)
    reported = ProjectsReportedSerializer(allow_null=True)
    members = ProjectsPersonSerializer(many=True)
    member_count = serializers.IntegerField()
    next_milestone = ProjectsNextMilestoneSerializer(allow_null=True)
    my_role = serializers.CharField(allow_null=True)
    currency = serializers.CharField()
    budget = MoneySerializerField(positive=False, allow_null=True)
    budget_currency = serializers.CharField()
    spent = MoneySerializerField(positive=False, allow_null=True, required=False)
    burn = serializers.IntegerField(allow_null=True, required=False)


def project_item(project: Project, facts: dict, viewer: Membership) -> dict:
    """An index row. Spent and burn only for people who see the project's money."""
    reported = facts.get("reported")
    next_milestone = facts.get("next_milestone")
    members = facts.get("members", [])
    role = queries.role_of(project, viewer)
    show_money = queries.sees_money(project, viewer)
    item = {
        "id": project.pk,
        "key": project.key,
        "name": project.name,
        "color": project.color,
        "icon": project.icon,
        "status": project.status,
        "priority": project.priority,
        "visibility": project.visibility,
        "lead": person(project.lead),
        "branch": {"id": project.branch_id, "name": project.branch.name}
        if project.branch_id
        else None,
        "client": {"id": project.client_id, "name": project.client.name}
        if project.client_id
        else None,
        "start_on": project.start_on,
        "due_on": project.due_on,
        "completed_at": project.completed_at,
        "archived_at": project.archived_at,
        "progress": facts["progress"],
        "health": facts["health"],
        "reported": {
            "health": reported.health,
            "text": reported.text[:280],
            "at": reported.created_at,
            "author": person(reported.author),
        }
        if reported
        else None,
        "members": [person(m) for m in members[:8]],
        "member_count": len(members),
        "next_milestone": {
            "id": next_milestone.pk,
            "name": next_milestone.name,
            "due_on": next_milestone.due_on,
        }
        if next_milestone
        else None,
        "my_role": role,
        "currency": project.company.base_currency,
        # The budget is money too: only for people who see the project's money.
        "budget": money(project.budget) if show_money else None,
        "budget_currency": project.budget_currency,
    }
    if show_money:
        item["spent"] = money(facts["spent"])
        item["burn"] = facts["burn"]
    return item


class ProjectWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    key = serializers.CharField(max_length=6, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    color = serializers.CharField(required=False, allow_blank=True, max_length=16)
    icon = serializers.CharField(required=False, allow_blank=True, max_length=40)
    status = serializers.ChoiceField(Project.Status.choices, required=False)
    priority = ProjectPriorityField(required=False)
    visibility = serializers.ChoiceField(Project.Visibility.choices, required=False)
    lead = serializers.IntegerField(required=False, allow_null=True)
    branch = serializers.IntegerField(required=False, allow_null=True)
    client = serializers.IntegerField(required=False, allow_null=True)
    start_on = serializers.DateField(required=False, allow_null=True)
    due_on = serializers.DateField(required=False, allow_null=True)
    budget = MoneySerializerField(positive=False, required=False, allow_null=True, min_value=0)
    budget_currency = serializers.ChoiceField([("UZS", "UZS"), ("USD", "USD")], required=False)
    member_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class ProjectsListSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    position = serializers.FloatField()
    is_done = serializers.BooleanField()
    wip_limit = serializers.IntegerField(allow_null=True)


def list_row(row: ProjectList) -> dict:
    return {
        "id": row.pk,
        "name": row.name,
        "position": row.position,
        "is_done": row.is_done,
        "wip_limit": row.wip_limit,
    }


class ProjectsLabelSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    color = serializers.CharField()


def label_row(label: Label) -> dict:
    return {"id": label.pk, "name": label.name, "color": label.color}


class ProjectsMilestoneSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField()
    due_on = serializers.DateField(allow_null=True)
    status = serializers.ChoiceField(Milestone.Status.choices)
    completed_at = serializers.DateTimeField(allow_null=True)
    position = serializers.FloatField()
    done = serializers.IntegerField()
    total = serializers.IntegerField()
    percent = serializers.IntegerField()
    overdue = serializers.BooleanField()


def milestone_row(milestone: Milestone, counts: dict | None, today) -> dict:
    counts = counts or {"done": 0, "total": 0, "percent": 0}
    return {
        "id": milestone.pk,
        "name": milestone.name,
        "description": milestone.description,
        "due_on": milestone.due_on,
        "status": milestone.status,
        "completed_at": milestone.completed_at,
        "position": milestone.position,
        "done": counts["done"],
        "total": counts["total"],
        "percent": counts["percent"],
        "overdue": milestone.status == Milestone.Status.OPEN
        and milestone.due_on is not None
        and milestone.due_on < today,
    }


class ProjectsCapabilitiesSerializer(serializers.Serializer):
    manage = serializers.BooleanField()
    edit_cards = serializers.BooleanField()
    post_update = serializers.BooleanField()
    see_money = serializers.BooleanField()
    add_expense = serializers.BooleanField()
    see_labour = serializers.BooleanField()
    see_all_time = serializers.BooleanField()


class ProjectDetailSerializer(ProjectItemSerializer):
    description = serializers.CharField()
    created_at = serializers.DateTimeField()
    created_by = ProjectsPersonSerializer(allow_null=True)
    lists = ProjectsListSerializer(many=True)
    labels = ProjectsLabelSerializer(many=True)
    milestones = ProjectsMilestoneSerializer(many=True)
    capabilities = ProjectsCapabilitiesSerializer()


class ProjectsCardSerializer(serializers.Serializer):
    """A card on the board, the list view or the mini app."""

    id = serializers.IntegerField()
    number = serializers.IntegerField(allow_null=True)
    key = serializers.CharField()
    title = serializers.CharField()
    list_id = serializers.IntegerField(allow_null=True)
    position = serializers.FloatField()
    status = serializers.ChoiceField(Task.Status.choices)
    # The task app's priorities (low, normal, high, urgent); a plain string so the schema keeps
    # one enum per choice set.
    priority = serializers.CharField()
    due_at = serializers.DateTimeField(allow_null=True)
    start_on = serializers.DateField(allow_null=True)
    assignee = ProjectsPersonSerializer(allow_null=True)
    label_ids = serializers.ListField(child=serializers.IntegerField())
    milestone_id = serializers.IntegerField(allow_null=True)
    checklist_done = serializers.IntegerField()
    checklist_total = serializers.IntegerField()
    comments = serializers.IntegerField()
    proof = serializers.ChoiceField(Proof.choices)
    proof_thumb = serializers.CharField(allow_null=True)
    needs_confirmation = serializers.BooleanField()
    overdue = serializers.BooleanField()
    completed_at = serializers.DateTimeField(allow_null=True)
    minutes = serializers.IntegerField()
    can_move = serializers.BooleanField()


def card_row(
    task: Task,
    project: Project,
    viewer: Membership,
    *,
    minutes: int = 0,
    can_edit: bool = False,
    now: datetime | None = None,
) -> dict:
    now = now or timezone.now()
    card = getattr(task, "card", None)
    labels = getattr(task, "label_links", None)
    label_ids = [link.label_id for link in labels.all()] if labels is not None else []
    checklist_total = getattr(task, "checklist_total", None)
    if checklist_total is None:
        items = list(task.checklist.all())
        checklist_total = len(items)
        checklist_done = sum(1 for item in items if item.is_done)
    else:
        checklist_done = task.checklist_done
    comments = getattr(task, "comment_count", None)
    if comments is None:
        comments = task.comments.count()
    return {
        "id": task.pk,
        "number": card.number if card else None,
        "key": queries.card_key(project, task),
        "title": task.title,
        "list_id": task.project_list_id,
        "position": task.list_position,
        "status": task.status,
        "priority": task.priority,
        "due_at": task.due_at,
        "start_on": card.start_on if card else None,
        "assignee": person(task.assignee),
        "label_ids": label_ids,
        "milestone_id": task.milestone_id,
        "checklist_done": checklist_done,
        "checklist_total": checklist_total,
        "comments": comments,
        "proof": task.proof,
        "proof_thumb": task.proof_photo.url if task.proof_photo else None,
        "needs_confirmation": task.needs_confirmation,
        "overdue": task.is_overdue(now),
        "completed_at": task.completed_at,
        "minutes": minutes,
        "can_move": can_edit or task.assignee_id == viewer.pk,
    }


class ProjectsBoardSerializer(serializers.Serializer):
    project = ProjectItemSerializer()
    lists = ProjectsListSerializer(many=True)
    cards = ProjectsCardSerializer(many=True)
    labels = ProjectsLabelSerializer(many=True)
    milestones = ProjectsMilestoneSerializer(many=True)
    people = ProjectsPersonSerializer(many=True)
    capabilities = ProjectsCapabilitiesSerializer()


class ProjectsChecklistItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    text = serializers.CharField()
    is_done = serializers.BooleanField()


class ProjectsCommentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    author = ProjectsPersonSerializer(allow_null=True)
    text = serializers.CharField()
    created_at = serializers.DateTimeField()


class ProjectsTimeEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    person = ProjectsPersonSerializer()
    project = ProjectsRefSerializer(allow_null=True)
    project_key = serializers.CharField(allow_null=True)
    task = ProjectsRefSerializer(allow_null=True)
    day = serializers.DateField()
    minutes = serializers.IntegerField()
    note = serializers.CharField()
    billable = serializers.BooleanField()
    source = serializers.ChoiceField(TimeEntry.Source.choices)
    created_at = serializers.DateTimeField()
    can_edit = serializers.BooleanField()


def time_row(entry: TimeEntry, viewer: Membership, *, manages: set[int] | None = None) -> dict:
    manages = manages or set()
    return {
        "id": entry.pk,
        "person": person(entry.membership),
        "project": {"id": entry.project_id, "name": entry.project.name}
        if entry.project_id
        else None,
        "project_key": entry.project.key if entry.project_id else None,
        "task": {"id": entry.task_id, "name": entry.task.title} if entry.task_id else None,
        "day": entry.day,
        "minutes": entry.minutes,
        "note": entry.note,
        "billable": entry.billable,
        "source": entry.source,
        "created_at": entry.created_at,
        "can_edit": entry.membership_id == viewer.pk or (entry.project_id in manages),
    }


class ProjectsCardDetailSerializer(ProjectsCardSerializer):
    description = serializers.CharField()
    created_at = serializers.DateTimeField()
    created_by = ProjectsPersonSerializer(allow_null=True)
    checklist = ProjectsChecklistItemSerializer(many=True)
    recent_comments = ProjectsCommentSerializer(many=True)
    time = ProjectsTimeEntrySerializer(many=True)
    actions = serializers.ListField(child=serializers.CharField())
    can_edit_task = serializers.BooleanField()
    proof_text = serializers.CharField()
    proof_photo = serializers.CharField(allow_null=True)


def card_detail(task: Task, project: Project, viewer: Membership, *, can_edit: bool) -> dict:
    """A card in full. Its time entries are listed per person only for people who may see
    everyone's time on the project (the total is part of the card for everyone)."""
    entries = TimeEntry.objects.filter(task=task)
    if not queries.sees_time_of_others(project, viewer):
        entries = entries.filter(membership=viewer)
    entries = list(
        entries.select_related("membership__user", "project", "task").order_by("-day", "-pk")[:20]
    )
    row = card_row(
        task,
        project,
        viewer,
        minutes=queries.logged_minutes([task.pk]).get(task.pk, 0),
        can_edit=can_edit,
    )
    comments = list(task.comments.select_related("author__user").order_by("-created_at")[:20])
    return row | {
        "description": task.description,
        "created_at": task.created_at,
        "created_by": person(task.created_by),
        "checklist": [
            {"id": i.pk, "text": i.text, "is_done": i.is_done} for i in task.checklist.all()
        ],
        "recent_comments": [
            {"id": c.pk, "author": person(c.author), "text": c.text, "created_at": c.created_at}
            for c in reversed(comments)
        ],
        "time": [time_row(e, viewer) for e in entries],
        "actions": [str(a) for a in task_rules.allowed_actions(task, viewer)],
        "can_edit_task": task_rules.can_manage(task, viewer),
        "proof_text": task.proof_text,
        "proof_photo": task.proof_photo.url if task.proof_photo else None,
    }


class ProjectsCardCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    list = serializers.IntegerField(required=False, allow_null=True)
    assignee = serializers.IntegerField(required=False, allow_null=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    priority = TaskPriorityField(required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    milestone = serializers.IntegerField(required=False, allow_null=True)
    label_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    checklist = serializers.ListField(child=serializers.CharField(max_length=200), required=False)
    proof = serializers.ChoiceField(Proof.choices, required=False)
    needs_confirmation = serializers.BooleanField(required=False)
    start_on = serializers.DateField(required=False, allow_null=True)


class ProjectsCardUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    priority = TaskPriorityField(required=False)
    milestone = serializers.IntegerField(required=False, allow_null=True)
    label_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    start_on = serializers.DateField(required=False, allow_null=True)


class ProjectsMoveSerializer(serializers.Serializer):
    list = serializers.IntegerField()
    position = serializers.FloatField(
        required=False, allow_null=True, help_text="Leave out to put the card at the end."
    )


class ProjectsMoveResultSerializer(serializers.Serializer):
    card = ProjectsCardSerializer()
    message = serializers.CharField(allow_blank=True)


class ProjectsScheduleSerializer(serializers.Serializer):
    start_on = serializers.DateField()
    end_on = serializers.DateField()


class ProjectsListWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=60, required=False)
    wip_limit = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=999
    )


class ProjectsReorderSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField())


class ProjectsMilestoneWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    due_on = serializers.DateField(required=False, allow_null=True)
    status = serializers.ChoiceField(Milestone.Status.choices, required=False)
    position = serializers.FloatField(required=False)


class ProjectsLabelWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=30, required=False)
    color = serializers.CharField(max_length=16, required=False, allow_blank=True)


class ProjectsMemberSerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True)
    person = ProjectsPersonSerializer()
    position = serializers.CharField(allow_blank=True)
    role = serializers.ChoiceField(ProjectMember.Role.choices)
    open = serializers.IntegerField()
    review = serializers.IntegerField()
    done = serializers.IntegerField()
    overdue = serializers.IntegerField()
    week_minutes = serializers.IntegerField()


def member_row(row: dict) -> dict:
    membership = row["membership"]
    return {
        "id": row["id"],
        "person": person(membership),
        "position": membership.position.name if membership.position_id else "",
        "role": row["role"],
        "open": row["open"],
        "review": row["review"],
        "done": row["done"],
        "overdue": row["overdue"],
        "week_minutes": row["week_minutes"],
    }


class ProjectsMemberAddSerializer(serializers.Serializer):
    membership = serializers.IntegerField()
    role = serializers.ChoiceField(ProjectMember.Role.choices, required=False)


class ProjectsMemberRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(ProjectMember.Role.choices)


class ProjectsUpdateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    health = serializers.ChoiceField(Health.choices)
    text = serializers.CharField()
    author = ProjectsPersonSerializer(allow_null=True)
    created_at = serializers.DateTimeField()


def update_row(update: ProjectUpdate) -> dict:
    return {
        "id": update.pk,
        "health": update.health,
        "text": update.text,
        "author": person(update.author),
        "created_at": update.created_at,
    }


class ProjectsUpdateWriteSerializer(serializers.Serializer):
    health = serializers.ChoiceField(Health.choices)
    text = serializers.CharField(required=False, allow_blank=True, max_length=4000)


class ProjectsFileSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.CharField()
    size = serializers.IntegerField()
    url = serializers.CharField()
    uploaded_by = ProjectsPersonSerializer(allow_null=True)
    created_at = serializers.DateTimeField()
    can_delete = serializers.BooleanField()


def file_row(row: ProjectFile, *, url: str, can_delete: bool) -> dict:
    return {
        "id": row.pk,
        "name": row.name,
        "kind": row.kind,
        "size": row.size,
        "url": url,
        "uploaded_by": person(row.uploaded_by),
        "created_at": row.created_at,
        "can_delete": can_delete,
    }


class ProjectsLinkSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    url = serializers.CharField()
    added_by = ProjectsPersonSerializer(allow_null=True)
    created_at = serializers.DateTimeField()
    can_delete = serializers.BooleanField()


def link_row(link: ProjectLink, *, can_delete: bool) -> dict:
    return {
        "id": link.pk,
        "title": link.title,
        "url": link.url,
        "added_by": person(link.added_by),
        "created_at": link.created_at,
        "can_delete": can_delete,
    }


class ProjectsLinkWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120, required=False, allow_blank=True)
    url = serializers.CharField(max_length=500)


class ProjectsTimeWriteSerializer(serializers.Serializer):
    day = serializers.DateField()
    minutes = serializers.IntegerField(min_value=1, max_value=1440)
    project = serializers.IntegerField(required=False, allow_null=True)
    task = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)
    billable = serializers.BooleanField(required=False)
    person = serializers.IntegerField(required=False, allow_null=True)


class ProjectsTimeUpdateSerializer(serializers.Serializer):
    day = serializers.DateField(required=False)
    minutes = serializers.IntegerField(min_value=1, max_value=1440, required=False)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)
    billable = serializers.BooleanField(required=False)


class ProjectsTimerSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    person = ProjectsPersonSerializer()
    project = ProjectsRefSerializer(allow_null=True)
    project_key = serializers.CharField(allow_null=True)
    task = ProjectsRefSerializer(allow_null=True)
    task_key = serializers.CharField(allow_null=True)
    started_at = serializers.DateTimeField()
    note = serializers.CharField()


def timer_row(timer: RunningTimer) -> dict:
    project = timer.project or (
        timer.task.project if timer.task_id and timer.task.project_id else None
    )
    task_key = None
    if timer.task_id and project is not None:
        task_key = queries.card_key(project, timer.task)
    return {
        "id": timer.pk,
        "person": person(timer.membership),
        "project": {"id": project.pk, "name": project.name} if project else None,
        "project_key": project.key if project else None,
        "task": {"id": timer.task_id, "name": timer.task.title} if timer.task_id else None,
        "task_key": task_key,
        "started_at": timer.started_at,
        "note": timer.note,
    }


class ProjectsTimerStartSerializer(serializers.Serializer):
    project = serializers.IntegerField(required=False, allow_null=True)
    task = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)


class ProjectsTimeGridRowSerializer(serializers.Serializer):
    person = ProjectsPersonSerializer()
    days = serializers.ListField(child=serializers.IntegerField())
    total = serializers.IntegerField()
    billable = serializers.IntegerField()


class ProjectsTimeWeekSerializer(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    days = serializers.ListField(child=serializers.DateField())
    rows = ProjectsTimeGridRowSerializer(many=True)
    totals = serializers.ListField(child=serializers.IntegerField())
    total = serializers.IntegerField()
    billable = serializers.IntegerField()
    entries = ProjectsTimeEntrySerializer(many=True)
    running = ProjectsTimerSerializer(many=True)


class ProjectsExpenseSerializer(serializers.Serializer):
    amount = MoneySerializerField()
    account = serializers.IntegerField()
    category = serializers.IntegerField()
    occurred_on = serializers.DateField()
    description = serializers.CharField(required=False, allow_blank=True, max_length=300)
    counterparty = serializers.IntegerField(required=False, allow_null=True)


class ProjectsSettingsSerializer(serializers.Serializer):
    default_lists = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False
    )
    weekly_nudge = serializers.BooleanField(required=False)
    nudge_weekday = serializers.IntegerField(min_value=0, max_value=6, required=False)
    at_risk_days = serializers.IntegerField(min_value=1, max_value=90, required=False)
    at_risk_percent = serializers.IntegerField(min_value=1, max_value=100, required=False)


def local_day(value: datetime | None, tz: ZoneInfo):
    return timezone.localtime(value, tz).date() if value else None
