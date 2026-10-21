"""Owner dashboard endpoints of projects (docs/PLAN-OWNER.md §13.3); routed in `owner_urls.py`.

Every endpoint needs `dashboard.access` (the console base) and then works on the projects the
caller may see (`queries.visible_projects`): another company's or a hidden project answers 404.
Writes go through `services`, which check what the caller may do there (403 otherwise), audit
and bump the `projects.projects` / `projects.time` pulse keys after commit.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import cached_property
from zoneinfo import ZoneInfo

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import exceptions, serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.console.base import OwnerAPIView
from apps.core import files
from apps.core.api import Pagination
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.scope import restrict
from apps.projects import conf, queries, services
from apps.projects import serializers as s
from apps.projects.models import (
    Health,
    Label,
    Milestone,
    Project,
    ProjectFile,
    ProjectList,
    ProjectMember,
    TimeEntry,
)
from apps.tasks import rules as task_rules
from apps.tasks.models import Task


class ProjectsView(OwnerAPIView):
    """Base: `ProjectError` answers 400 with its `code`; a project (or row) the caller can't
    see answers 404; `self.project` is the URL's project."""

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
            # A project the caller can't see answers 404 before anything else (a bad payload
            # included), exactly like another company's id.
            self.project  # noqa: B018

    @cached_property
    def project(self) -> Project:
        return queries.get_visible(self.membership, self.kwargs["project_id"])

    def facts(self, projects: list[Project]) -> dict:
        return queries.summaries(projects)

    def item(self, project: Project) -> dict:
        return s.project_item(project, self.facts([project])[project.pk], self.membership)

    def member_of_company(self, pk, *, project: Project | None = None) -> Membership | None:
        """An approved member of the company the caller may pick: someone in their branch scope
        (§2.6), themselves, or someone already on `project`. Anyone else answers 404."""
        if pk in (None, ""):
            return None
        people = Membership.objects.select_related("user").filter(
            company=self.company, status=Membership.Status.APPROVED
        )
        allowed = Q(pk__in=restrict(people, self.branch_scope, field="branches").values("pk"))
        allowed |= Q(pk=self.membership.pk)
        if project is not None:
            allowed |= Q(pk__in=project.members.values("membership_id")) | Q(pk=project.lead_id)
        return people.filter(allowed).get(pk=pk)

    def branch(self, pk):
        """A branch of the company inside the caller's scope (404 otherwise)."""
        if pk in (None, ""):
            return None
        branches = self.company.branches.all()
        if self.branch_scope is not None:
            branches = branches.filter(pk__in=self.branch_scope)
        return branches.get(pk=pk)

    def today(self) -> date:
        return queries.local_today(self.company)


def _client(company, pk):
    if pk in (None, ""):
        return None
    from apps.finance.models import Counterparty

    return Counterparty.objects.get(pk=pk, company=company)


# Index ----------------------------------------------------------------------------------

LIST_PARAMS = [
    OpenApiParameter(
        "status", str, many=True, description="planning, active, on_hold, completed, cancelled"
    ),
    OpenApiParameter("health", str, many=True, description="on_track, at_risk, off_track"),
    OpenApiParameter("lead", int, many=True),
    OpenApiParameter("branch", int, many=True),
    OpenApiParameter("client", int, many=True),
    OpenApiParameter("label", str, description="Projects with a label of this name"),
    OpenApiParameter("q", str),
    OpenApiParameter("mine", bool, description="Only projects I lead or work on"),
    OpenApiParameter("archived", bool, description="Archived projects instead of live ones"),
    OpenApiParameter(
        "ordering", str, description="name, -name, due_on, -due_on, created_at, -created_at"
    ),
]


def _multi(params, key) -> list[str]:
    values = []
    for raw in params.getlist(key):
        values += [v for v in raw.split(",") if v]
    return values


class ProjectListView(ProjectsView):
    """Projects: the index (filters, progress, health, budget burn) and creating one."""

    @extend_schema(parameters=LIST_PARAMS, responses=s.ProjectItemSerializer(many=True))
    def get(self, request, company_id):
        params = request.query_params
        archived = params.get("archived") in ("1", "true")
        projects = queries.visible_projects(self.membership, archived=archived)
        if archived:
            projects = projects.filter(archived_at__isnull=False)
        if statuses := _multi(params, "status"):
            projects = projects.filter(status__in=statuses)
        if leads := _multi(params, "lead"):
            projects = projects.filter(lead_id__in=[int(v) for v in leads if v.isdigit()])
        if branches := _multi(params, "branch"):
            projects = projects.filter(branch_id__in=[int(v) for v in branches if v.isdigit()])
        if clients := _multi(params, "client"):
            projects = projects.filter(client_id__in=[int(v) for v in clients if v.isdigit()])
        if label := params.get("label"):
            projects = projects.filter(labels__name__iexact=label).distinct()
        if q := (params.get("q") or "").strip():
            projects = projects.filter(
                Q(name__icontains=q) | Q(key__icontains=q) | Q(description__icontains=q)
            )
        if params.get("mine") in ("1", "true"):
            projects = projects.filter(pk__in=queries.my_projects(self.membership).values("pk"))
        ordering = params.get("ordering") or ""
        allowed = {"name", "-name", "due_on", "-due_on", "created_at", "-created_at", "key", "-key"}
        projects = projects.order_by(ordering if ordering in allowed else "position", "name")
        projects = projects.select_related("company", "lead__user", "branch", "client")
        page = Pagination()
        page.max_page_size = 500
        if health := set(_multi(params, "health")):
            # Health is worked out, not stored: filter every match first, then page.
            every = list(projects)
            facts = self.facts(every)
            rows = page.paginate_queryset(
                [p for p in every if facts[p.pk]["health"] in health], request, view=self
            )
        else:
            rows = page.paginate_queryset(projects, request, view=self)
            facts = self.facts(rows)
        queries.prime_access(rows, self.membership)
        items = [s.project_item(p, facts[p.pk], self.membership) for p in rows]
        return page.get_paginated_response(items)

    @extend_schema(request=s.ProjectWriteSerializer, responses={201: s.ProjectDetailSerializer})
    def post(self, request, company_id):
        data = _valid(s.ProjectWriteSerializer, request.data)
        project = services.create_project(
            self.company,
            by=self.membership,
            name=data["name"],
            key=data.get("key") or "",
            description=data.get("description", ""),
            color=data.get("color", ""),
            icon=data.get("icon", ""),
            status=data.get("status", Project.Status.PLANNING),
            priority=data.get("priority", Project.Priority.NORMAL),
            visibility=data.get("visibility", Project.Visibility.MEMBERS),
            lead=self.member_of_company(data.get("lead")),
            branch=self.branch(data.get("branch")),
            client=_client(self.company, data.get("client")),
            start_on=data.get("start_on"),
            due_on=data.get("due_on"),
            budget=data.get("budget"),
            budget_currency=data.get("budget_currency"),
            member_ids=[self.member_of_company(pk).pk for pk in data.get("member_ids", [])],
        )
        project = queries.get_visible(self.membership, project.pk)
        return Response(_detail(self, project), status=status.HTTP_201_CREATED)


def _valid(serializer_class, data, *, partial=False):
    serializer = serializer_class(data=data, partial=partial)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class SummaryView(ProjectsView):
    """Numbers for the index's KPI strip."""

    @extend_schema(
        responses=inline_serializer(
            "ProjectsSummary",
            {
                "active": serializers.IntegerField(),
                "planning": serializers.IntegerField(),
                "at_risk": serializers.IntegerField(),
                "off_track": serializers.IntegerField(),
                "overdue_cards": serializers.IntegerField(),
                "due_this_week": serializers.IntegerField(),
                "hours_this_week": serializers.IntegerField(),
                "budget": serializers.CharField(allow_null=True),
                "spent": serializers.CharField(allow_null=True),
                "currency": serializers.CharField(),
            },
        )
    )
    def get(self, request, company_id):
        projects = list(
            queries.visible_projects(self.membership).select_related(
                "company", "lead", "branch", "client"
            )
        )
        live = [p for p in projects if p.status in Project.LIVE_STATUSES]
        queries.prime_access(live, self.membership)
        facts = self.facts(live)
        today = self.today()
        week_start, week_end = queries.week_bounds(today)
        money_visible = [p for p in live if queries.sees_money(p, self.membership)]
        budget = sum((facts[p.pk]["budget_base"] or 0 for p in money_visible), start=0)
        spent = sum((facts[p.pk]["spent"] for p in money_visible), start=0)
        minutes = (
            queries.time_entries(self.membership, start=week_start, end=week_end)
            .filter(project__in=[p.pk for p in live])
            .values_list("minutes", flat=True)
        )
        return Response(
            {
                "active": sum(1 for p in live if p.status == Project.Status.ACTIVE),
                "planning": sum(1 for p in live if p.status == Project.Status.PLANNING),
                "at_risk": sum(1 for p in live if facts[p.pk]["health"] == Health.AT_RISK),
                "off_track": sum(1 for p in live if facts[p.pk]["health"] == Health.OFF_TRACK),
                "overdue_cards": sum(facts[p.pk]["progress"]["overdue"] for p in live),
                "due_this_week": sum(
                    1 for p in live if p.due_on is not None and week_start <= p.due_on <= week_end
                ),
                "hours_this_week": round(sum(minutes) / 60),
                "budget": s.money(budget) if money_visible else None,
                "spent": s.money(spent) if money_visible else None,
                "currency": self.company.base_currency,
            }
        )


class PeopleView(ProjectsView):
    """People the caller may put on a project (approved members in their branch scope)."""

    @extend_schema(
        responses=inline_serializer(
            "ProjectsPeopleRow",
            {
                "id": serializers.IntegerField(),
                "name": serializers.CharField(),
                "photo_url": serializers.CharField(allow_null=True),
                "position": serializers.CharField(),
            },
            many=True,
        )
    )
    def get(self, request, company_id):
        people = restrict(
            Membership.objects.for_company(self.company)
            .filter(status=Membership.Status.APPROVED)
            .select_related("user", "position"),
            self.branch_scope,
            field="branches",
        )
        rows = [
            s.person(m) | {"position": m.position.name if m.position_id else ""} for m in people
        ]
        rows.sort(key=lambda r: r["name"].lower())
        return Response(rows)


class OptionsView(ProjectsView):
    """Choices for the project form: branches and clients."""

    @extend_schema(
        responses=inline_serializer(
            "ProjectsOptions",
            {
                "branches": s.ProjectsRefSerializer(many=True),
                "clients": s.ProjectsRefSerializer(many=True),
                "currency": serializers.CharField(),
                "can_create": serializers.BooleanField(),
            },
        )
    )
    def get(self, request, company_id):
        branches = self.company.branches.filter(is_active=True).order_by("order", "name")
        if self.branch_scope is not None:
            branches = branches.filter(pk__in=self.branch_scope)
        clients = []
        if self.membership.has_perm(Perm.FINANCE_VIEW) or self.membership.has_perm(
            Perm.PROJECTS_MANAGE
        ):
            from apps.finance.models import Counterparty

            clients = [
                {"id": c.pk, "name": c.name}
                for c in Counterparty.objects.for_company(self.company)
                .filter(is_active=True)
                .order_by("name")[:500]
            ]
        return Response(
            {
                "branches": [{"id": b.pk, "name": b.name} for b in branches],
                "clients": clients,
                "currency": self.company.base_currency,
                "can_create": self.membership.has_perm(Perm.PROJECTS_MANAGE),
            }
        )


# One project ----------------------------------------------------------------------------


def _detail(view: ProjectsView, project: Project) -> dict:
    today = view.today()
    progress = queries.progress(project)
    counts = {row["id"]: row for row in progress["milestones"]}
    return view.item(project) | {
        "description": project.description,
        "created_at": project.created_at,
        "created_by": s.person(project.created_by),
        "lists": [s.list_row(row) for row in project.lists.all()],
        "labels": [s.label_row(label) for label in project.labels.all()],
        "milestones": [
            s.milestone_row(m, counts.get(m.pk), today) for m in project.milestones.all()
        ],
        "capabilities": queries.capabilities(project, view.membership),
    }


class ProjectDetailView(ProjectsView):
    @extend_schema(responses=s.ProjectDetailSerializer)
    def get(self, request, company_id, project_id):
        return Response(_detail(self, self.project))

    @extend_schema(request=s.ProjectWriteSerializer, responses=s.ProjectDetailSerializer)
    def patch(self, request, company_id, project_id):
        data = dict(_valid(s.ProjectWriteSerializer, request.data, partial=True))
        data.pop("member_ids", None)
        if "lead" in data:
            data["lead"] = self.member_of_company(data["lead"], project=self.project)
        if "branch" in data:
            data["branch"] = self.branch(data["branch"])
        if "client" in data:
            data["client"] = _client(self.company, data["client"])
        services.update_project(self.project, by=self.membership, **data)
        return Response(_detail(self, queries.get_visible(self.membership, project_id)))


class ArchiveView(ProjectsView):
    restore = False

    @extend_schema(request=None, responses=s.ProjectDetailSerializer)
    def post(self, request, company_id, project_id):
        action = services.restore_project if self.restore else services.archive_project
        action(self.project, by=self.membership)
        return Response(_detail(self, queries.get_visible(self.membership, project_id)))


# Board and cards ------------------------------------------------------------------------


def _board_cards(view: ProjectsView, project: Project, *, can_edit: bool) -> list[dict]:
    tasks = list(queries.board_cards(project, view.membership))
    minutes = queries.logged_minutes([t.pk for t in tasks])
    now = timezone.now()
    return [
        s.card_row(
            t, project, view.membership, minutes=minutes.get(t.pk, 0), can_edit=can_edit, now=now
        )
        for t in tasks
    ]


def board_payload(view, project: Project) -> dict:
    """Lists with their cards in one go, plus what the board's filters and quick add need."""
    member = view.membership
    caps = queries.capabilities(project, member)
    today = queries.local_today(project.company)
    progress = queries.progress(project)
    counts = {row["id"]: row for row in progress["milestones"]}
    people = [row["membership"] for row in queries.members_with_load(project)]
    return {
        "project": s.project_item(project, queries.summaries([project])[project.pk], member),
        "lists": [s.list_row(row) for row in project.lists.all()],
        "cards": _board_cards(view, project, can_edit=caps["edit_cards"]),
        "labels": [s.label_row(label) for label in project.labels.all()],
        "milestones": [
            s.milestone_row(m, counts.get(m.pk), today) for m in project.milestones.all()
        ],
        "people": [s.person(m) for m in people],
        "capabilities": caps,
    }


class BoardView(ProjectsView):
    @extend_schema(responses=s.ProjectsBoardSerializer)
    def get(self, request, company_id, project_id):
        return Response(board_payload(self, self.project))


class CardListView(ProjectsView):
    """The List tab (every card, cancelled ones too with `?cancelled=1`), and quick add."""

    @extend_schema(responses=s.ProjectsCardSerializer(many=True))
    def get(self, request, company_id, project_id):
        project = self.project
        caps = queries.capabilities(project, self.membership)
        return Response(_board_cards(self, project, can_edit=caps["edit_cards"]))

    @extend_schema(
        request=s.ProjectsCardCreateSerializer, responses={201: s.ProjectsCardSerializer}
    )
    def post(self, request, company_id, project_id):
        project = self.project
        data = _valid(s.ProjectsCardCreateSerializer, request.data)
        task = services.create_card(
            project,
            by=self.membership,
            title=data["title"],
            project_list=project.lists.get(pk=data["list"]) if data.get("list") else None,
            assignee=self.member_of_company(data.get("assignee"), project=project),
            due_at=data.get("due_at"),
            priority=data.get("priority", Task.Priority.NORMAL),
            description=data.get("description", ""),
            milestone=project.milestones.get(pk=data["milestone"])
            if data.get("milestone")
            else None,
            label_ids=data.get("label_ids", []),
            checklist=data.get("checklist", []),
            proof=data.get("proof", "none"),
            needs_confirmation=data.get("needs_confirmation", False),
            start_on=data.get("start_on"),
        )
        return Response(_card(self, project, task), status=status.HTTP_201_CREATED)


def _card(view, project: Project, task: Task) -> dict:
    task = (
        Task.objects.filter(pk=task.pk)
        .select_related("assignee__user", "card", "project_list", "milestone")
        .prefetch_related("label_links")
        .first()
    )
    return s.card_row(
        task,
        project,
        view.membership,
        minutes=queries.logged_minutes([task.pk]).get(task.pk, 0),
        can_edit=queries.can_edit_cards(project, view.membership),
    )


class CardDetailView(ProjectsView):
    def get_task(self) -> Task:
        return queries.board_cards(self.project, self.membership).get(pk=self.kwargs["task_id"])

    @extend_schema(responses=s.ProjectsCardDetailSerializer)
    def get(self, request, company_id, project_id, task_id):
        task = (
            Task.objects.filter(pk=self.get_task().pk)
            .select_related(
                "assignee__user", "created_by__user", "card", "project_list", "milestone", "company"
            )
            .prefetch_related("label_links", "checklist")
            .get()
        )
        return Response(
            s.card_detail(
                task,
                self.project,
                self.membership,
                can_edit=queries.can_edit_cards(self.project, self.membership),
            )
        )

    @extend_schema(request=s.ProjectsCardUpdateSerializer, responses=s.ProjectsCardSerializer)
    def patch(self, request, company_id, project_id, task_id):
        project = self.project
        data = dict(_valid(s.ProjectsCardUpdateSerializer, request.data, partial=True))
        if "milestone" in data:
            data["milestone"] = (
                project.milestones.get(pk=data["milestone"]) if data["milestone"] else None
            )
        task = services.update_card(self.get_task(), by=self.membership, **data)
        return Response(_card(self, project, task))


class CardMoveView(CardDetailView):
    @extend_schema(request=s.ProjectsMoveSerializer, responses=s.ProjectsMoveResultSerializer)
    def post(self, request, company_id, project_id, task_id):
        project = self.project
        data = _valid(s.ProjectsMoveSerializer, request.data)
        before = self.get_task()
        task = services.move_card(
            before, project.lists.get(pk=data["list"]), data.get("position"), by=self.membership
        )
        message = ""
        if before.status != task.status and task.status == Task.Status.REVIEW:
            message = str(_("Sent for a check."))
        elif before.status != task.status and task.status == Task.Status.DONE:
            message = str(_("Done."))
        return Response({"card": _card(self, project, task), "message": message})


class CardScheduleView(CardDetailView):
    """Timeline drag: the planned start and the deadline."""

    @extend_schema(request=s.ProjectsScheduleSerializer, responses=s.ProjectsCardSerializer)
    def post(self, request, company_id, project_id, task_id):
        data = _valid(s.ProjectsScheduleSerializer, request.data)
        task = services.reschedule_card(
            self.get_task(), by=self.membership, start_on=data["start_on"], end_on=data["end_on"]
        )
        return Response(_card(self, self.project, task))


# Lists, milestones, labels --------------------------------------------------------------


class ListsView(ProjectsView):
    @extend_schema(responses=s.ProjectsListSerializer(many=True))
    def get(self, request, company_id, project_id):
        return Response([s.list_row(row) for row in self.project.lists.all()])

    @extend_schema(request=s.ProjectsListWriteSerializer, responses={201: s.ProjectsListSerializer})
    def post(self, request, company_id, project_id):
        data = _valid(s.ProjectsListWriteSerializer, request.data)
        row = services.create_list(
            self.project,
            by=self.membership,
            name=data.get("name", ""),
            wip_limit=data.get("wip_limit"),
        )
        return Response(s.list_row(row), status=status.HTTP_201_CREATED)


class ListReorderView(ProjectsView):
    @extend_schema(
        request=s.ProjectsReorderSerializer, responses=s.ProjectsListSerializer(many=True)
    )
    def post(self, request, company_id, project_id):
        data = _valid(s.ProjectsReorderSerializer, request.data)
        rows = services.reorder_lists(self.project, data["ids"], by=self.membership)
        return Response([s.list_row(row) for row in rows])


class ListDetailView(ProjectsView):
    def get_row(self) -> ProjectList:
        return self.project.lists.get(pk=self.kwargs["list_id"])

    @extend_schema(request=s.ProjectsListWriteSerializer, responses=s.ProjectsListSerializer)
    def patch(self, request, company_id, project_id, list_id):
        data = _valid(s.ProjectsListWriteSerializer, request.data, partial=True)
        return Response(
            s.list_row(services.update_list(self.get_row(), by=self.membership, **data))
        )

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, project_id, list_id):
        services.delete_list(self.get_row(), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MilestonesView(ProjectsView):
    @extend_schema(responses=s.ProjectsMilestoneSerializer(many=True))
    def get(self, request, company_id, project_id):
        project = self.project
        counts = {row["id"]: row for row in queries.progress(project)["milestones"]}
        today = self.today()
        return Response(
            [s.milestone_row(m, counts.get(m.pk), today) for m in project.milestones.all()]
        )

    @extend_schema(
        request=s.ProjectsMilestoneWriteSerializer, responses={201: s.ProjectsMilestoneSerializer}
    )
    def post(self, request, company_id, project_id):
        data = _valid(s.ProjectsMilestoneWriteSerializer, request.data)
        milestone = services.create_milestone(
            self.project,
            by=self.membership,
            name=data.get("name", ""),
            due_on=data.get("due_on"),
            description=data.get("description", ""),
        )
        return Response(
            s.milestone_row(milestone, None, self.today()), status=status.HTTP_201_CREATED
        )


class MilestoneDetailView(ProjectsView):
    def get_row(self) -> Milestone:
        return self.project.milestones.get(pk=self.kwargs["milestone_id"])

    @extend_schema(
        request=s.ProjectsMilestoneWriteSerializer, responses=s.ProjectsMilestoneSerializer
    )
    def patch(self, request, company_id, project_id, milestone_id):
        data = _valid(s.ProjectsMilestoneWriteSerializer, request.data, partial=True)
        milestone = services.update_milestone(self.get_row(), by=self.membership, **data)
        counts = {row["id"]: row for row in queries.progress(self.project)["milestones"]}
        return Response(s.milestone_row(milestone, counts.get(milestone.pk), self.today()))

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, project_id, milestone_id):
        services.delete_milestone(self.get_row(), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LabelsView(ProjectsView):
    @extend_schema(responses=s.ProjectsLabelSerializer(many=True))
    def get(self, request, company_id, project_id):
        return Response([s.label_row(label) for label in self.project.labels.all()])

    @extend_schema(
        request=s.ProjectsLabelWriteSerializer, responses={201: s.ProjectsLabelSerializer}
    )
    def post(self, request, company_id, project_id):
        data = _valid(s.ProjectsLabelWriteSerializer, request.data)
        label = services.create_label(
            self.project, by=self.membership, name=data.get("name", ""), color=data.get("color", "")
        )
        return Response(s.label_row(label), status=status.HTTP_201_CREATED)


class LabelDetailView(ProjectsView):
    def get_row(self) -> Label:
        return self.project.labels.get(pk=self.kwargs["label_id"])

    @extend_schema(request=s.ProjectsLabelWriteSerializer, responses=s.ProjectsLabelSerializer)
    def patch(self, request, company_id, project_id, label_id):
        data = _valid(s.ProjectsLabelWriteSerializer, request.data, partial=True)
        return Response(
            s.label_row(services.update_label(self.get_row(), by=self.membership, **data))
        )

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, project_id, label_id):
        services.delete_label(self.get_row(), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


# Members --------------------------------------------------------------------------------


class MembersView(ProjectsView):
    @extend_schema(responses=s.ProjectsMemberSerializer(many=True))
    def get(self, request, company_id, project_id):
        return Response([s.member_row(row) for row in queries.members_with_load(self.project)])

    @extend_schema(
        request=s.ProjectsMemberAddSerializer,
        responses={201: s.ProjectsMemberSerializer(many=True)},
    )
    def post(self, request, company_id, project_id):
        data = _valid(s.ProjectsMemberAddSerializer, request.data)
        services.add_member(
            self.project,
            self.member_of_company(data["membership"], project=self.project),
            by=self.membership,
            role=data.get("role", ProjectMember.Role.MEMBER),
        )
        return Response(
            [s.member_row(row) for row in queries.members_with_load(self.project)],
            status=status.HTTP_201_CREATED,
        )


class MemberDetailView(ProjectsView):
    def get_row(self) -> ProjectMember:
        return self.project.members.select_related("membership__user", "project").get(
            pk=self.kwargs["row_id"]
        )

    @extend_schema(
        request=s.ProjectsMemberRoleSerializer, responses=s.ProjectsMemberSerializer(many=True)
    )
    def patch(self, request, company_id, project_id, row_id):
        data = _valid(s.ProjectsMemberRoleSerializer, request.data)
        services.set_member_role(self.get_row(), by=self.membership, role=data["role"])
        return Response([s.member_row(row) for row in queries.members_with_load(self.project)])

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, project_id, row_id):
        services.remove_member(self.project, self.get_row().membership, by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


# Updates, files, links ------------------------------------------------------------------


class UpdatesView(ProjectsView):
    @extend_schema(responses=s.ProjectsUpdateSerializer(many=True))
    def get(self, request, company_id, project_id):
        updates = self.project.updates.select_related("author__user")[:100]
        return Response([s.update_row(u) for u in updates])

    @extend_schema(
        request=s.ProjectsUpdateWriteSerializer, responses={201: s.ProjectsUpdateSerializer}
    )
    def post(self, request, company_id, project_id):
        data = _valid(s.ProjectsUpdateWriteSerializer, request.data)
        update = services.post_update(
            self.project, by=self.membership, health=data["health"], text=data.get("text", "")
        )
        return Response(s.update_row(update), status=status.HTTP_201_CREATED)


def _file_url(request, row: ProjectFile) -> str:
    return files.signed_url(
        row.file,
        user=request.user,
        company_id=row.project.company_id,
        check=f"projects.file:{row.pk}",
        filename=row.name,
    )


class FilesView(ProjectsView):
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    @extend_schema(responses=s.ProjectsFileSerializer(many=True))
    def get(self, request, company_id, project_id):
        project = self.project
        manage = queries.can_manage(project, self.membership)
        rows = project.files.select_related("uploaded_by__user", "project")
        return Response(
            [
                s.file_row(
                    row,
                    url=_file_url(request, row),
                    can_delete=manage or row.uploaded_by_id == self.membership.pk,
                )
                for row in rows
            ]
        )

    @extend_schema(
        request={
            "multipart/form-data": inline_serializer(
                "ProjectsFileUpload",
                {"file": serializers.FileField(), "name": serializers.CharField(required=False)},
            )
        },
        responses={201: s.ProjectsFileSerializer},
    )
    def post(self, request, company_id, project_id):
        upload = request.FILES.get("file")
        if upload is None:
            raise exceptions.ValidationError({"file": [str(_("Attach a file."))]})
        row = services.add_file(
            self.project, by=self.membership, upload=upload, name=request.data.get("name", "")
        )
        return Response(
            s.file_row(row, url=_file_url(request, row), can_delete=True),
            status=status.HTTP_201_CREATED,
        )


class FileDetailView(ProjectsView):
    @extend_schema(responses={204: None})
    def delete(self, request, company_id, project_id, file_id):
        services.delete_file(self.project.files.get(pk=file_id), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LinksView(ProjectsView):
    @extend_schema(responses=s.ProjectsLinkSerializer(many=True))
    def get(self, request, company_id, project_id):
        project = self.project
        manage = queries.can_manage(project, self.membership)
        return Response(
            [
                s.link_row(link, can_delete=manage or link.added_by_id == self.membership.pk)
                for link in project.links.select_related("added_by__user")
            ]
        )

    @extend_schema(request=s.ProjectsLinkWriteSerializer, responses={201: s.ProjectsLinkSerializer})
    def post(self, request, company_id, project_id):
        data = _valid(s.ProjectsLinkWriteSerializer, request.data)
        link = services.add_link(
            self.project, by=self.membership, title=data.get("title", ""), url=data["url"]
        )
        return Response(s.link_row(link, can_delete=True), status=status.HTTP_201_CREATED)


class LinkDetailView(ProjectsView):
    @extend_schema(responses={204: None})
    def delete(self, request, company_id, project_id, link_id):
        services.delete_link(self.project.links.get(pk=link_id), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


# Money ----------------------------------------------------------------------------------


class FinancialsView(ProjectsView):
    """Budget vs actual, linked ledger rows, receivables, labour (payroll.view) and margin."""

    @extend_schema(
        responses=inline_serializer(
            "ProjectsFinancials",
            {
                "currency": serializers.CharField(),
                "budget": serializers.CharField(allow_null=True),
                "budget_original": serializers.CharField(allow_null=True),
                "budget_currency": serializers.CharField(),
                "spent": serializers.CharField(),
                "income": serializers.CharField(),
                "receivable": serializers.CharField(),
                "labour_cost": serializers.CharField(allow_null=True, required=False),
                "margin": serializers.CharField(),
                "margin_includes_labour": serializers.BooleanField(),
                "burn": serializers.IntegerField(allow_null=True),
                "remaining": serializers.CharField(allow_null=True),
                "by_category": serializers.ListField(child=serializers.DictField()),
                "by_month": serializers.ListField(child=serializers.DictField()),
                "transactions": serializers.ListField(child=serializers.DictField()),
            },
        )
    )
    def get(self, request, company_id, project_id):
        project = self.project
        if not queries.sees_money(project, self.membership):
            raise exceptions.PermissionDenied(str(_("You can't see this project's money.")))
        data = queries.financials(project, viewer=self.membership)
        return Response(_money_strings(data))


def _money_strings(value):
    from decimal import Decimal

    if isinstance(value, Decimal):
        return s.money(value)
    if isinstance(value, dict):
        return {k: _money_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_money_strings(v) for v in value]
    return value


class ExpenseView(ProjectsView):
    """ "Add expense to project": a ledger expense through `finance.services`."""

    @extend_schema(
        request=s.ProjectsExpenseSerializer,
        responses={
            201: inline_serializer(
                "ProjectsExpense",
                {"id": serializers.IntegerField(), "base_amount": serializers.CharField()},
            )
        },
    )
    def post(self, request, company_id, project_id):
        from apps.finance.models import Category, Counterparty, MoneyAccount

        if not self.membership.has_perm(Perm.FINANCE_RECORD):
            raise exceptions.PermissionDenied(str(_("You can't record expenses.")))
        data = _valid(s.ProjectsExpenseSerializer, request.data)
        txn = services.add_expense(
            self.project,
            by=self.membership,
            amount=data["amount"],
            account=MoneyAccount.objects.get(pk=data["account"], company=self.company),
            category=Category.objects.get(pk=data["category"], company=self.company),
            occurred_on=data["occurred_on"],
            description=data.get("description", ""),
            counterparty=Counterparty.objects.get(pk=data["counterparty"], company=self.company)
            if data.get("counterparty")
            else None,
        )
        return Response(
            {"id": txn.pk, "base_amount": s.money(txn.base_amount)}, status=status.HTTP_201_CREATED
        )


class ExpenseOptionsView(ProjectsView):
    @extend_schema(
        responses=inline_serializer(
            "ProjectsExpenseOptions",
            {
                "accounts": serializers.ListField(child=serializers.DictField()),
                "categories": serializers.ListField(child=serializers.DictField()),
                "counterparties": serializers.ListField(child=serializers.DictField()),
            },
        )
    )
    def get(self, request, company_id, project_id):
        from apps.finance.models import Category, Counterparty

        self.project  # noqa: B018 (404 for a project the caller can't see)
        if not self.membership.has_perm(Perm.FINANCE_RECORD):
            raise exceptions.PermissionDenied(str(_("You can't record expenses.")))
        accounts = services.expense_accounts(self.membership).order_by("order", "name")
        categories = Category.objects.for_company(self.company).filter(
            kind="expense", is_active=True
        )
        if not self.membership.has_perm(Perm.PAYROLL_VIEW):
            categories = categories.filter(is_sensitive=False)
        return Response(
            {
                "accounts": [
                    {
                        "id": a.pk,
                        "name": a.name,
                        "currency": a.currency,
                        "kind": a.kind,
                        "balance": s.money(a.balance),
                    }
                    for a in accounts
                ],
                "categories": [
                    {"id": c.pk, "name": c.name, "parent_id": c.parent_id, "color": c.color}
                    for c in categories.order_by("order", "name")
                ],
                "counterparties": [
                    {"id": c.pk, "name": c.name}
                    for c in Counterparty.objects.for_company(self.company)
                    .filter(is_active=True)
                    .order_by("name")[:500]
                ],
            }
        )


# Timeline and roadmap -------------------------------------------------------------------


def _bar_progress(task: Task) -> int:
    if task.status == Task.Status.DONE:
        return 100
    if task.status == Task.Status.REVIEW:
        return 80
    if task.status == Task.Status.IN_PROGRESS:
        return 40
    return 0


class TimelineView(ProjectsView):
    """Gantt rows: each card from its planned start to its deadline, and the milestones."""

    @extend_schema(
        responses=inline_serializer(
            "ProjectsTimeline",
            {
                "rows": serializers.ListField(child=serializers.DictField()),
                "milestones": serializers.ListField(child=serializers.DictField()),
                "project": inline_serializer(
                    "ProjectsTimelineSpan",
                    {"start": serializers.DateField(), "end": serializers.DateField()},
                ),
            },
        )
    )
    def get(self, request, company_id, project_id):
        project = self.project
        tz = ZoneInfo(self.company.timezone)
        can_edit = queries.can_edit_cards(project, self.membership)
        tasks = queries.board_cards(project, self.membership)
        rows = []
        for task in tasks:
            start, end = queries.card_dates(task, tz)
            rows.append(
                {
                    "id": task.pk,
                    "key": queries.card_key(project, task),
                    "title": task.title,
                    "status": task.status,
                    "list": task.project_list.name if task.project_list_id else "",
                    "list_id": task.project_list_id,
                    "milestone_id": task.milestone_id,
                    "assignee": s.person(task.assignee),
                    "start": start,
                    "end": end,
                    "has_due": task.due_at is not None,
                    "progress": _bar_progress(task),
                    # Moving the bar changes the deadline: the task app decides who may.
                    "editable": can_edit
                    and task.is_open
                    and task_rules.can_manage(task, self.membership),
                    "overdue": task.is_overdue(),
                }
            )
        rows.sort(key=lambda r: (r["start"], r["end"], r["id"]))
        start, end = queries.project_dates(project, today=self.today())
        return Response(
            {
                "project": {"start": start, "end": end},
                "rows": rows,
                "milestones": [
                    {
                        "id": m.pk,
                        "name": m.name,
                        "date": m.due_on,
                        "done": m.status == Milestone.Status.DONE,
                    }
                    for m in project.milestones.exclude(due_on__isnull=True)
                ],
            }
        )


class RoadmapView(ProjectsView):
    """Every visible project on one timeline (live ones; finished too with `?all=1`)."""

    @extend_schema(
        parameters=[OpenApiParameter("all", bool)],
        responses=inline_serializer(
            "ProjectsRoadmap", {"rows": serializers.ListField(child=serializers.DictField())}
        ),
    )
    def get(self, request, company_id):
        projects = queries.visible_projects(self.membership).select_related(
            "company", "lead__user", "branch", "client"
        )
        if request.query_params.get("all") not in ("1", "true"):
            projects = projects.filter(status__in=Project.LIVE_STATUSES)
        projects = list(projects.order_by("start_on", "due_on", "name"))
        queries.prime_access(projects, self.membership)
        facts = self.facts(projects)
        today = self.today()
        milestones: dict[int, list[dict]] = {}
        for m in (
            Milestone.objects.filter(project__in=projects)
            .exclude(due_on__isnull=True)
            .order_by("due_on")
        ):
            milestones.setdefault(m.project_id, []).append(
                {
                    "id": m.pk,
                    "name": m.name,
                    "date": m.due_on,
                    "done": m.status == Milestone.Status.DONE,
                }
            )
        rows = []
        for project in projects:
            start, end = queries.project_dates(project, today=today)
            item = s.project_item(project, facts[project.pk], self.membership)
            rows.append(
                item
                | {
                    "start": start,
                    "end": end,
                    "editable": queries.can_manage(project, self.membership),
                    "milestones": milestones.get(project.pk, []),
                }
            )
        return Response(_money_strings({"rows": rows}))


class RoadmapScheduleView(ProjectsView):
    """Roadmap drag: a project's start and due dates."""

    @extend_schema(request=s.ProjectsScheduleSerializer, responses=s.ProjectItemSerializer)
    def post(self, request, company_id, project_id):
        data = _valid(s.ProjectsScheduleSerializer, request.data)
        if data["end_on"] < data["start_on"]:
            raise services.ProjectError(str(_("The end can't be before the start.")))
        services.update_project(
            self.project, by=self.membership, start_on=data["start_on"], due_on=data["end_on"]
        )
        return Response(self.item(queries.get_visible(self.membership, project_id)))


# Time -----------------------------------------------------------------------------------


def week_payload(
    member: Membership, *, start: date, project: Project | None, person_ids: list[int] | None
) -> dict:
    end = start + timedelta(days=6)
    entries = list(
        queries.time_entries(
            member, start=start, end=end, project=project, person_ids=person_ids
        ).order_by("-day", "-pk")
    )
    manages = set(queries.managed_projects(member).values_list("pk", flat=True))
    grid: dict[int, dict] = {}
    for entry in entries:
        row = grid.setdefault(
            entry.membership_id,
            {"person": s.person(entry.membership), "days": [0] * 7, "total": 0, "billable": 0},
        )
        index = (entry.day - start).days
        row["days"][index] += entry.minutes
        row["total"] += entry.minutes
        if entry.billable:
            row["billable"] += entry.minutes
    rows = sorted(grid.values(), key=lambda r: (-r["total"], r["person"]["name"].lower()))
    totals = [sum(r["days"][i] for r in rows) for i in range(7)]
    timers = queries.running_timers(member, project=project)
    return {
        "start": start,
        "end": end,
        "days": [start + timedelta(days=i) for i in range(7)],
        "rows": rows,
        "totals": totals,
        "total": sum(totals),
        "billable": sum(r["billable"] for r in rows),
        "entries": [s.time_row(e, member, manages=manages) for e in entries[:300]],
        "running": [s.timer_row(t) for t in timers],
    }


TIME_PARAMS = [
    OpenApiParameter(
        "week", str, description="Any day of the week (YYYY-MM-DD); default this week"
    ),
    OpenApiParameter("project", int),
    OpenApiParameter("person", int, many=True),
]


class TimeView(ProjectsView):
    """The week grid per person (own time, everyone's on projects one manages, and all with
    `projects.time_view`), with totals; logging time."""

    @extend_schema(parameters=TIME_PARAMS, responses=s.ProjectsTimeWeekSerializer)
    def get(self, request, company_id):
        params = request.query_params
        try:
            day = date.fromisoformat(params["week"]) if params.get("week") else self.today()
        except ValueError as exc:
            raise exceptions.ValidationError({"week": ["YYYY-MM-DD"]}) from exc
        start, _end = queries.week_bounds(day)
        project = None
        if params.get("project"):
            project = queries.get_visible(self.membership, params["project"])
        people = [int(v) for v in _multi(params, "person") if v.isdigit()]
        return Response(
            week_payload(self.membership, start=start, project=project, person_ids=people or None)
        )

    @extend_schema(
        request=s.ProjectsTimeWriteSerializer, responses={201: s.ProjectsTimeEntrySerializer}
    )
    def post(self, request, company_id):
        data = _valid(s.ProjectsTimeWriteSerializer, request.data)
        project = (
            queries.get_visible(self.membership, data["project"]) if data.get("project") else None
        )
        task = None
        if data.get("task"):
            task = Task.objects.select_related("project").get(pk=data["task"], company=self.company)
            if task.project_id and not queries.can_view(task.project, self.membership):
                raise exceptions.NotFound()
        entry = services.log_time(
            self.membership,
            day=data["day"],
            minutes=data["minutes"],
            project=project,
            task=task,
            note=data.get("note", ""),
            billable=data.get("billable", False),
            membership=self.member_of_company(
                data.get("person"), project=project or (task.project if task else None)
            )
            if data.get("person")
            else None,
        )
        entry = TimeEntry.objects.select_related("membership__user", "project", "task").get(
            pk=entry.pk
        )
        return Response(s.time_row(entry, self.membership), status=status.HTTP_201_CREATED)


class TimeDetailView(ProjectsView):
    def get_entry(self) -> TimeEntry:
        today = self.today()
        return queries.time_entries(
            self.membership, start=today - timedelta(days=3660), end=today + timedelta(days=1)
        ).get(pk=self.kwargs["entry_id"])

    @extend_schema(request=s.ProjectsTimeUpdateSerializer, responses=s.ProjectsTimeEntrySerializer)
    def patch(self, request, company_id, entry_id):
        data = _valid(s.ProjectsTimeUpdateSerializer, request.data, partial=True)
        entry = services.update_time_entry(self.get_entry(), by=self.membership, **data)
        return Response(s.time_row(entry, self.membership))

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, entry_id):
        services.delete_time_entry(self.get_entry(), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TimersView(ProjectsView):
    """Who is tracking time now (as far as the caller may see), and starting one's own timer."""

    @extend_schema(responses=s.ProjectsTimerSerializer(many=True))
    def get(self, request, company_id):
        return Response([s.timer_row(t) for t in queries.running_timers(self.membership)])

    @extend_schema(
        request=s.ProjectsTimerStartSerializer, responses={201: s.ProjectsTimerSerializer}
    )
    def post(self, request, company_id):
        data = _valid(s.ProjectsTimerStartSerializer, request.data)
        project = (
            queries.get_visible(self.membership, data["project"]) if data.get("project") else None
        )
        task = None
        if data.get("task"):
            task = Task.objects.select_related("project").get(pk=data["task"], company=self.company)
            if task.project_id and not queries.can_view(task.project, self.membership):
                raise exceptions.NotFound()
        timer = services.start_timer(
            self.membership, task=task, project=project, note=data.get("note", "")
        )
        timer = queries.running_timers(self.membership).get(pk=timer.pk)
        return Response(s.timer_row(timer), status=status.HTTP_201_CREATED)


class TimerStopView(ProjectsView):
    @extend_schema(request=None, responses={200: s.ProjectsTimeEntrySerializer, 204: None})
    def post(self, request, company_id):
        entry = services.stop_timer(self.membership)
        if entry is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        entry = TimeEntry.objects.select_related("membership__user", "project", "task").get(
            pk=entry.pk
        )
        return Response(s.time_row(entry, self.membership))


# Settings -------------------------------------------------------------------------------


class SettingsView(ProjectsView):
    """Company-wide project defaults: the starting lists, the weekly nudge, health thresholds."""

    def payload(self) -> dict:
        settings = conf.get_settings(self.company)
        return {
            "default_lists": conf.default_list_names(self.company),
            "custom_lists": bool(settings.default_lists),
            "weekly_nudge": settings.weekly_nudge,
            "nudge_weekday": settings.nudge_weekday,
            "at_risk_days": settings.at_risk_days,
            "at_risk_percent": settings.at_risk_percent,
            "can_edit": self.membership.has_perm(Perm.COMPANY_SETTINGS)
            or self.membership.has_perm(Perm.PROJECTS_MANAGE),
        }

    @extend_schema(responses=s.ProjectsSettingsSerializer)
    def get(self, request, company_id):
        return Response(self.payload())

    @extend_schema(request=s.ProjectsSettingsSerializer, responses=s.ProjectsSettingsSerializer)
    def patch(self, request, company_id):
        data = _valid(s.ProjectsSettingsSerializer, request.data, partial=True)
        services.update_settings(self.company, by=self.membership, **data)
        return Response(self.payload())
