"""Employee (mini app) endpoints of projects; routed in `urls.py` under
`/api/v1/companies/<id>/` (docs/PLAN-OWNER.md §13.3):

- `projects/`: my projects (the ones I lead or work on), with progress and health;
- `projects/{id}/board/`: the board (read), `projects/{id}/cards/{task}/move/`: move my own
  card (or any, for people who edit the board);
- `projects/{id}/updates/`: the updates feed (leads and members post);
- `projects/time/`: my own time this week, logging and deleting it;
- `projects/timer/`: my running timer, start and stop.
"""

from __future__ import annotations

from datetime import date
from functools import cached_property

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import exceptions, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.members.api import IsCompanyMember
from apps.projects import queries, services
from apps.projects import serializers as s
from apps.projects.models import Project, RunningTimer, TimeEntry
from apps.projects.owner_api import board_payload
from apps.tasks.models import Task


class EmployeeView(APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember)

    def handle_exception(self, exc):
        if isinstance(exc, services.ProjectError):
            return Response(
                {"detail": str(exc), "code": exc.code}, status=status.HTTP_400_BAD_REQUEST
            )
        if isinstance(exc, ObjectDoesNotExist):
            exc = exceptions.NotFound()
        return super().handle_exception(exc)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if "project_id" in kwargs:
            self.project  # noqa: B018 (a project I'm not on answers 404 before anything else)

    @cached_property
    def project(self) -> Project:
        return queries.get_visible(self.membership, self.kwargs["project_id"], archived=False)


class MyProjectsView(EmployeeView):
    @extend_schema(responses=s.ProjectItemSerializer(many=True))
    def get(self, request, company_id):
        projects = list(queries.my_projects(self.membership).select_related("branch", "client"))
        order = {
            Project.Status.ACTIVE: 0,
            Project.Status.PLANNING: 1,
            Project.Status.ON_HOLD: 2,
            Project.Status.COMPLETED: 3,
            Project.Status.CANCELLED: 4,
        }
        projects.sort(key=lambda p: (order.get(p.status, 9), p.due_on or date.max, p.name))
        queries.prime_access(projects, self.membership)
        facts = queries.summaries(projects)
        items = [s.project_item(p, facts[p.pk], self.membership) for p in projects]
        mine = {
            row["project_id"]: row["n"]
            for row in Task.objects.filter(
                project__in=projects, assignee=self.membership, status__in=Task.OPEN_STATUSES
            )
            .values("project_id")
            .annotate(n=Count("pk"))
        }
        for item in items:
            item["my_open"] = mine.get(item["id"], 0)
        return Response(items)


class EmployeeBoardView(EmployeeView):
    @extend_schema(responses=s.ProjectsBoardSerializer)
    def get(self, request, company_id, project_id):
        return Response(board_payload(self, self.project))


class EmployeeMoveView(EmployeeView):
    @extend_schema(request=s.ProjectsMoveSerializer, responses=s.ProjectsMoveResultSerializer)
    def post(self, request, company_id, project_id, task_id):
        project = self.project
        serializer = s.ProjectsMoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before = queries.board_cards(project, self.membership).get(pk=task_id)
        task = services.move_card(
            before,
            project.lists.get(pk=serializer.validated_data["list"]),
            serializer.validated_data.get("position"),
            by=self.membership,
        )
        message = ""
        if before.status != task.status:
            message = _("Sent for a check.") if task.status == Task.Status.REVIEW else _("Done.")
        task = (
            Task.objects.filter(pk=task.pk)
            .select_related("assignee__user", "card", "project_list")
            .prefetch_related("label_links")
            .get()
        )
        return Response(
            {
                "card": s.card_row(
                    task,
                    project,
                    self.membership,
                    minutes=queries.logged_minutes([task.pk]).get(task.pk, 0),
                    can_edit=queries.can_edit_cards(project, self.membership),
                ),
                "message": message,
            }
        )


class EmployeeUpdatesView(EmployeeView):
    @extend_schema(responses=s.ProjectsUpdateSerializer(many=True))
    def get(self, request, company_id, project_id):
        updates = self.project.updates.select_related("author__user")[:50]
        return Response([s.update_row(u) for u in updates])

    @extend_schema(
        request=s.ProjectsUpdateWriteSerializer, responses={201: s.ProjectsUpdateSerializer}
    )
    def post(self, request, company_id, project_id):
        serializer = s.ProjectsUpdateWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        update = services.post_update(
            self.project,
            by=self.membership,
            health=serializer.validated_data["health"],
            text=serializer.validated_data.get("text", ""),
        )
        return Response(s.update_row(update), status=status.HTTP_201_CREATED)


class MyTimeView(EmployeeView):
    """My time for a week (default this week): entries, per-day totals, and logging."""

    @extend_schema(
        parameters=[OpenApiParameter("week", str)],
        responses=inline_serializer(
            "ProjectsMyWeek",
            {
                "start": serializers.DateField(),
                "end": serializers.DateField(),
                "days": serializers.ListField(child=serializers.IntegerField()),
                "total": serializers.IntegerField(),
                "entries": s.ProjectsTimeEntrySerializer(many=True),
            },
        ),
    )
    def get(self, request, company_id):
        today = queries.local_today(self.membership.company)
        try:
            day = (
                date.fromisoformat(request.query_params["week"])
                if request.query_params.get("week")
                else today
            )
        except ValueError as exc:
            raise exceptions.ValidationError({"week": ["YYYY-MM-DD"]}) from exc
        start, end = queries.week_bounds(day)
        entries = list(
            TimeEntry.objects.filter(membership=self.membership, day__range=(start, end))
            .select_related("membership__user", "project", "task")
            .order_by("-day", "-pk")
        )
        days = [0] * 7
        for entry in entries:
            days[(entry.day - start).days] += entry.minutes
        return Response(
            {
                "start": start,
                "end": end,
                "days": days,
                "total": sum(days),
                "entries": [s.time_row(e, self.membership) for e in entries],
            }
        )

    @extend_schema(
        request=s.ProjectsTimeWriteSerializer, responses={201: s.ProjectsTimeEntrySerializer}
    )
    def post(self, request, company_id):
        serializer = s.ProjectsTimeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project = (
            queries.get_visible(self.membership, data["project"]) if data.get("project") else None
        )
        task = None
        if data.get("task"):
            task = Task.objects.select_related("project").get(
                pk=data["task"], company_id=company_id
            )
        entry = services.log_time(
            self.membership,
            day=data["day"],
            minutes=data["minutes"],
            project=project,
            task=task,
            note=data.get("note", ""),
            billable=data.get("billable", False),
        )
        entry = TimeEntry.objects.select_related("membership__user", "project", "task").get(
            pk=entry.pk
        )
        return Response(s.time_row(entry, self.membership), status=status.HTTP_201_CREATED)


class MyTimeDetailView(EmployeeView):
    @extend_schema(responses={204: None})
    def delete(self, request, company_id, entry_id):
        entry = TimeEntry.objects.get(pk=entry_id, membership=self.membership)
        services.delete_time_entry(entry, by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyTimerView(EmployeeView):
    """My running timer (`{"timer": null}` when none), and starting it on a task or project."""

    def current(self):
        timer = (
            RunningTimer.objects.filter(membership=self.membership)
            .select_related("membership__user", "task__card", "task__project", "project")
            .first()
        )
        return s.timer_row(timer) if timer else None

    @extend_schema(
        responses=inline_serializer(
            "ProjectsMyTimer", {"timer": s.ProjectsTimerSerializer(allow_null=True)}
        )
    )
    def get(self, request, company_id):
        return Response({"timer": self.current()})

    @extend_schema(
        request=s.ProjectsTimerStartSerializer,
        responses={
            201: inline_serializer(
                "ProjectsMyTimerStarted", {"timer": s.ProjectsTimerSerializer(allow_null=True)}
            )
        },
    )
    def post(self, request, company_id):
        serializer = s.ProjectsTimerStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project = (
            queries.get_visible(self.membership, data["project"]) if data.get("project") else None
        )
        task = None
        if data.get("task"):
            task = Task.objects.select_related("project").get(
                pk=data["task"], company_id=company_id
            )
        services.start_timer(self.membership, task=task, project=project, note=data.get("note", ""))
        return Response({"timer": self.current()}, status=status.HTTP_201_CREATED)


class MyTimerStopView(EmployeeView):
    @extend_schema(request=None, responses={200: s.ProjectsTimeEntrySerializer, 204: None})
    def post(self, request, company_id):
        entry = services.stop_timer(self.membership)
        if entry is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        entry = TimeEntry.objects.select_related("membership__user", "project", "task").get(
            pk=entry.pk
        )
        return Response(s.time_row(entry, self.membership))
