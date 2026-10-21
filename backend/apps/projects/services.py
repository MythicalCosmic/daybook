"""Business logic of projects: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), checks what `by` may do
(`apps.projects.queries`), audits its changes with `apps.audit.services.record` and queues
jobs with `transaction.on_commit`.

Cards are `tasks.Task` rows. They are made and completed through `apps.tasks.services`
(`create_task`, `complete_task`, `confirm_task`, `update_task`); this app only sets where a
card sits on its board (`project`, `project_list`, `milestone`, `list_position`) and keeps its
own rows (`Card`, `TaskLabel`).
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from functools import partial
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.console import pulse
from apps.core import uploads
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.scope import branch_ids
from apps.projects import conf, queries
from apps.projects.audit_actions import ProjectsAction
from apps.projects.models import (
    COLOR_KEYS,
    KEY_PATTERN,
    Card,
    Health,
    Label,
    Milestone,
    Project,
    ProjectFile,
    ProjectLink,
    ProjectList,
    ProjectMember,
    ProjectSettings,
    ProjectUpdate,
    RunningTimer,
    TaskLabel,
    TimeEntry,
)
from apps.tasks import rules as task_rules
from apps.tasks import services as task_services
from apps.tasks.models import Proof, Task

Role = ProjectMember.Role
PULSE_PROJECTS = "projects.projects"
PULSE_TIME = "projects.time"

PROJECT_FIELDS = frozenset(
    {
        "name",
        "key",
        "description",
        "color",
        "icon",
        "status",
        "priority",
        "lead",
        "branch",
        "client",
        "start_on",
        "due_on",
        "budget",
        "budget_currency",
        "visibility",
    }
)
CARD_TASK_FIELDS = frozenset({"title", "description", "due_at", "priority"})
CARD_FIELDS = CARD_TASK_FIELDS | {"milestone", "label_ids", "start_on"}
MAX_UPDATE_LENGTH = 4000


class ProjectError(DomainError):
    """A project rule was broken. `code` lets the client react (`needs_proof` opens the card)."""

    def __init__(self, message: str, *, code: str = "invalid"):
        super().__init__(message)
        self.code = code


# Helpers --------------------------------------------------------------------------------


def _audit(action: str, project_or_target, by: Membership | None, **details) -> None:
    target = project_or_target
    audit.record(
        action,
        company_id=target.company_id
        if hasattr(target, "company_id")
        else target.project.company_id,
        actor=by.user if by is not None else None,
        target=target,
        **details,
    )


def _bump(company_id: int, *keys: str) -> None:
    transaction.on_commit(lambda: pulse.bump(company_id, *keys))


def _need(allowed: bool, message: str | None = None) -> None:
    if not allowed:
        raise PermissionDenied(message or _("You can't do this on this project."))


def _same_company(company_id: int, *objects) -> None:
    for obj in objects:
        if obj is not None and getattr(obj, "company_id", company_id) != company_id:
            raise ProjectError(_("That belongs to another company."))


def _clean_text(value: str, *, field: str, limit: int, required: bool = False) -> str:
    text = (value or "").strip()
    if required and not text:
        raise ProjectError(_("Fill in the %(field)s.") % {"field": field})
    return text[:limit]


def _clean_color(value: str) -> str:
    value = (value or "").strip()
    if value and value not in COLOR_KEYS:
        raise ProjectError(_("Pick one of the palette colours."))
    return value


def _money(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ProjectError(_("That isn't an amount.")) from exc
    if not amount.is_finite() or amount < 0:
        raise ProjectError(_("The budget can't be negative."))
    if amount >= Decimal("1e16"):
        raise ProjectError(_("That amount is too large."))
    return amount.quantize(Decimal("0.01"))


def _lock_project(project: Project) -> Project:
    return Project.objects.select_for_update().get(pk=project.pk)


def _lock_person(membership: Membership) -> None:
    """Serialize one person's time writes (their timer and their 24-hour day)."""
    Membership.objects.select_for_update().filter(pk=membership.pk).first()


# Keys -----------------------------------------------------------------------------------

CYRILLIC = str.maketrans(
    {
        "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "Y", "Ж": "J",
        "З": "Z", "И": "I", "Й": "Y", "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O",
        "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U", "Ф": "F", "Х": "X", "Ц": "S",
        "Ч": "C", "Ш": "S", "Щ": "S", "Ъ": "", "Ы": "I", "Ь": "", "Э": "E", "Ю": "Y",
        "Я": "Y", "Ў": "O", "Қ": "Q", "Ғ": "G", "Ҳ": "H",
    }
)  # fmt: skip


def _letters(word: str) -> str:
    word = word.upper().translate(CYRILLIC)
    word = unicodedata.normalize("NFKD", word)
    return re.sub(r"[^A-Z]", "", word)


def suggest_key(company, name: str) -> str:
    """A free key from the name: the initials ("Chilonzor branch opening" → "CBO"), else the
    first letters of the first word ("Website" → "WEBS"), else with a letter added."""
    words = [w for w in (_letters(part) for part in re.split(r"[\s\-_/.,]+", name)) if w]
    taken = set(Project.objects.filter(company=company).values_list("key", flat=True))
    candidates: list[str] = []
    if len(words) >= 2:
        candidates.append("".join(w[0] for w in words)[:6])
    if words:
        first = words[0]
        candidates += [first[:n] for n in (4, 3, 5, 6, 2)]
        if len(words) >= 2:
            candidates.append((first[:2] + words[1][:2])[:6])
    candidates = [c for c in candidates if re.fullmatch(KEY_PATTERN, c)] or ["PR"]
    for candidate in candidates:
        if candidate not in taken:
            return candidate
    base = candidates[0][:5]
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if (base + letter) not in taken:
            return base + letter
    for a in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        for b in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if f"PR{a}{b}" not in taken:
                return f"PR{a}{b}"
    raise ProjectError(_("Pick a key for the project."))


def _clean_key(company, key: str, *, project: Project | None = None) -> str:
    key = (key or "").strip().upper()
    if not re.fullmatch(KEY_PATTERN, key):
        raise ProjectError(_("A key is 2 to 6 capital letters, e.g. RENO."), code="key")
    clash = Project.objects.filter(company=company, key=key)
    if project is not None:
        clash = clash.exclude(pk=project.pk)
    if clash.exists():
        raise ProjectError(
            _("Another project already uses the key %(key)s.") % {"key": key}, code="key"
        )
    return key


# Projects -------------------------------------------------------------------------------


@transaction.atomic
def create_project(
    company,
    *,
    by: Membership,
    name: str,
    key: str = "",
    description: str = "",
    color: str = "",
    icon: str = "",
    status: str = Project.Status.PLANNING,
    priority: str = Project.Priority.NORMAL,
    lead: Membership | None = None,
    branch=None,
    client=None,
    start_on: date | None = None,
    due_on: date | None = None,
    budget=None,
    budget_currency: str | None = None,
    visibility: str = Project.Visibility.MEMBERS,
    member_ids: list[int] | tuple = (),
) -> Project:
    """A new project with the default lists; the lead (and a creator who couldn't see it
    otherwise) become members."""
    _need(
        by.company_id == company.pk and by.has_perm(Perm.PROJECTS_MANAGE),
        _("You can't create projects."),
    )
    _same_company(company.pk, lead, branch, client)
    name = _clean_text(name, field=_("name"), limit=120, required=True)
    key = _clean_key(company, key) if key else suggest_key(company, name)
    if start_on and due_on and due_on < start_on:
        raise ProjectError(_("The due date can't be before the start."))
    if status not in Project.Status.values or priority not in Project.Priority.values:
        raise ProjectError(_("Unknown status or priority."))
    if visibility not in Project.Visibility.values:
        raise ProjectError(_("Unknown visibility."))
    lead = lead or by
    _check_member(company, lead)
    project = Project(
        company=company,
        name=name,
        key=key,
        description=_clean_text(description, field="description", limit=20000),
        color=_clean_color(color)
        or COLOR_KEYS[Project.objects.filter(company=company).count() % 8],
        icon=_clean_text(icon, field="icon", limit=40),
        status=status,
        priority=priority,
        lead=lead,
        branch=branch,
        client=client,
        start_on=start_on,
        due_on=due_on,
        budget=_money(budget),
        budget_currency=budget_currency or company.base_currency,
        visibility=visibility,
        created_by=by,
        position=(
            Project.objects.filter(company=company).aggregate(top=Max("position"))["top"] or 0
        )
        + 1024,
    )
    if status == Project.Status.COMPLETED:
        project.completed_at = timezone.now()
    try:
        with transaction.atomic():
            project.save()
    except IntegrityError as exc:
        raise ProjectError(
            _("Another project already uses the key %(key)s.") % {"key": key}, code="key"
        ) from exc
    names = conf.default_list_names(company)
    ProjectList.objects.bulk_create(
        ProjectList(
            project=project,
            name=list_name,
            position=(index + 1) * 1024,
            is_done=index == len(names) - 1,
        )
        for index, list_name in enumerate(names)
    )
    ProjectMember.objects.create(project=project, membership=lead, role=Role.LEAD, added_by=by)
    if lead.pk != by.pk and not by.has_perm(Perm.PROJECTS_VIEW_ALL):
        ProjectMember.objects.create(project=project, membership=by, role=Role.MEMBER, added_by=by)
    _audit(ProjectsAction.PROJECT_CREATED, project, by, key=key, name=name)
    if lead.pk != by.pk:
        _notify_added(project, lead, by)
    others = Membership.objects.filter(company=company, pk__in=member_ids).exclude(
        pk__in=project.members.values("membership_id")
    )
    for person in others:
        add_member(project, person, by=by)
    _bump(company.pk, PULSE_PROJECTS)
    return project


@transaction.atomic
def update_project(project: Project, *, by: Membership, **changes) -> Project:
    if unknown := changes.keys() - PROJECT_FIELDS:
        raise ValueError(f"Not editable: {sorted(unknown)}")
    project = _lock_project(project)
    _need(queries.can_manage(project, by))
    before = audit.snapshot(project)
    company = project.company
    if "name" in changes:
        project.name = _clean_text(changes["name"], field=_("name"), limit=120, required=True)
    if "key" in changes and changes["key"] != project.key:
        project.key = _clean_key(company, changes["key"], project=project)
    if "description" in changes:
        project.description = _clean_text(changes["description"], field="description", limit=20000)
    if "color" in changes:
        project.color = _clean_color(changes["color"])
    if "icon" in changes:
        project.icon = _clean_text(changes["icon"], field="icon", limit=40)
    if "status" in changes:
        status = changes["status"]
        if status not in Project.Status.values:
            raise ProjectError(_("Unknown status."))
        if status == Project.Status.COMPLETED and project.status != status:
            project.completed_at = timezone.now()
        elif status != Project.Status.COMPLETED:
            project.completed_at = None
        project.status = status
    if "priority" in changes:
        if changes["priority"] not in Project.Priority.values:
            raise ProjectError(_("Unknown priority."))
        project.priority = changes["priority"]
    if "visibility" in changes:
        if changes["visibility"] not in Project.Visibility.values:
            raise ProjectError(_("Unknown visibility."))
        project.visibility = changes["visibility"]
    for field in ("branch", "client"):
        if field in changes:
            _same_company(company.pk, changes[field])
            setattr(project, field, changes[field])
    for field in ("start_on", "due_on"):
        if field in changes:
            setattr(project, field, changes[field])
    if project.start_on and project.due_on and project.due_on < project.start_on:
        raise ProjectError(_("The due date can't be before the start."))
    if "budget" in changes:
        project.budget = _money(changes["budget"])
    if "budget_currency" in changes:
        if changes["budget_currency"] not in ("UZS", "USD"):
            raise ProjectError(_("Unknown currency."))
        project.budget_currency = changes["budget_currency"]
    new_lead = changes.get("lead")
    if "lead" in changes and new_lead is None and project.lead_id is not None:
        ProjectMember.objects.filter(project=project, membership_id=project.lead_id).update(
            role=Role.MEMBER, updated_at=timezone.now()
        )
        project.lead = None
    if "lead" in changes and new_lead is not None and new_lead.pk != project.lead_id:
        _same_company(company.pk, new_lead)
        _check_member(company, new_lead)
        old = project.lead_id
        project.lead = new_lead
        project.save()
        ProjectMember.objects.filter(project=project, membership_id=old, role=Role.LEAD).update(
            role=Role.MEMBER, updated_at=timezone.now()
        )
        row, created = ProjectMember.objects.get_or_create(
            project=project, membership=new_lead, defaults={"role": Role.LEAD, "added_by": by}
        )
        if not created and row.role != Role.LEAD:
            row.role = Role.LEAD
            row.save(update_fields=["role", "updated_at"])
        if new_lead.pk != by.pk and created:
            _notify_added(project, new_lead, by)
    project.save()
    if changed := audit.diff(before, audit.snapshot(project)):
        _audit(ProjectsAction.PROJECT_CHANGED, project, by, changes=changed)
    _bump(company.pk, PULSE_PROJECTS)
    return project


@transaction.atomic
def archive_project(project: Project, *, by: Membership) -> Project:
    project = _lock_project(project)
    _need(queries.can_manage(project, by))
    if project.archived_at is None:
        project.archived_at = timezone.now()
        project.save(update_fields=["archived_at", "updated_at"])
        RunningTimer.objects.filter(project=project).delete()
        _audit(ProjectsAction.PROJECT_ARCHIVED, project, by)
        _bump(project.company_id, PULSE_PROJECTS)
    return project


@transaction.atomic
def restore_project(project: Project, *, by: Membership) -> Project:
    project = _lock_project(project)
    _need(queries.can_manage(project, by))
    if project.archived_at is not None:
        project.archived_at = None
        project.save(update_fields=["archived_at", "updated_at"])
        _audit(ProjectsAction.PROJECT_RESTORED, project, by)
        _bump(project.company_id, PULSE_PROJECTS)
    return project


# Members --------------------------------------------------------------------------------


def _check_member(company, membership: Membership) -> None:
    if membership.company_id != company.pk or membership.status != Membership.Status.APPROVED:
        raise ProjectError(_("Only approved members of the company can join a project."))


@transaction.atomic
def add_member(
    project: Project,
    membership: Membership,
    *,
    by: Membership | None,
    role: str = Role.MEMBER,
    notify: bool = True,
) -> ProjectMember:
    """Add someone to the project (or return their row). `by=None`: the system, e.g. when a
    card is assigned to someone outside the project."""
    if by is not None:
        _need(queries.can_manage(project, by))
    _check_member(project.company, membership)
    if role not in Role.values or role == Role.LEAD:
        raise ProjectError(_("Make someone the lead from the project settings."))
    row, created = ProjectMember.objects.get_or_create(
        project=project, membership=membership, defaults={"role": role, "added_by": by}
    )
    if created:
        _audit(ProjectsAction.MEMBER_ADDED, project, by, member=str(membership), role=role)
        if notify and (by is None or membership.pk != by.pk):
            _notify_added(project, membership, by)
        _bump(project.company_id, PULSE_PROJECTS)
    return row


@transaction.atomic
def set_member_role(row: ProjectMember, *, by: Membership, role: str) -> ProjectMember:
    project = row.project
    _need(queries.can_manage(project, by))
    if role not in Role.values:
        raise ProjectError(_("Unknown role."))
    if role == Role.LEAD or row.membership_id == project.lead_id:
        raise ProjectError(_("Change the lead from the project settings."))
    if row.role != role:
        before = row.role
        row.role = role
        row.save(update_fields=["role", "updated_at"])
        _audit(
            ProjectsAction.MEMBER_ROLE_CHANGED,
            project,
            by,
            member=str(row.membership),
            changes={"role": [before, role]},
        )
        _bump(project.company_id, PULSE_PROJECTS)
    return row


@transaction.atomic
def remove_member(project: Project, membership: Membership, *, by: Membership) -> None:
    _need(queries.can_manage(project, by))
    if membership.pk == project.lead_id:
        raise ProjectError(_("Pick another lead before removing this one."))
    deleted, _rows = ProjectMember.objects.filter(project=project, membership=membership).delete()
    if deleted:
        _audit(ProjectsAction.MEMBER_REMOVED, project, by, member=str(membership))
        _bump(project.company_id, PULSE_PROJECTS)


def _notify_added(project: Project, membership: Membership, by: Membership | None) -> None:
    from apps.inbox import services as inbox

    def title(person: Membership) -> str:
        return _("You were added to project %(key)s · %(name)s") % {
            "key": project.key,
            "name": project.name,
        }

    def body(person: Membership) -> str:
        if by is None:
            return _("You have a card on its board.")
        return _("%(name)s added you. Open the board to see your cards.") % {"name": str(by)}

    inbox.notify(
        [membership],
        "projects.added",
        title=title,
        body=body,
        url=f"/c/{project.company_id}/projects/{project.pk}",
        app_screen=f"projects.board:{project.pk}",
        target=project,
        actor=by,
        dedupe_key=f"projects.added:{project.pk}",
    )


# Lists ----------------------------------------------------------------------------------


@transaction.atomic
def create_list(
    project: Project,
    *,
    by: Membership,
    name: str,
    wip_limit: int | None = None,
    is_done: bool = False,
) -> ProjectList:
    _need(queries.can_manage(project, by))
    name = _clean_text(name, field=_("name"), limit=60, required=True)
    if is_done and project.lists.filter(is_done=True).exists():
        raise ProjectError(_("This board already has a done list."))
    done = queries.done_list(project)
    if done is not None and not is_done:
        # New lists go before Done.
        before = project.lists.filter(is_done=False).aggregate(top=Max("position"))["top"] or 0
        position = (before + done.position) / 2 if done.position > before else before + 1024
    else:
        position = (project.lists.aggregate(top=Max("position"))["top"] or 0) + 1024
    row = ProjectList.objects.create(
        project=project, name=name, wip_limit=_wip(wip_limit), is_done=is_done, position=position
    )
    _audit(ProjectsAction.LIST_CREATED, project, by, list=name)
    _bump(project.company_id, PULSE_PROJECTS)
    return row


def _wip(value) -> int | None:
    if value in (None, "", 0):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ProjectError(_("A limit is a whole number.")) from exc
    if not 1 <= number <= 999:
        raise ProjectError(_("A limit is between 1 and 999 cards."))
    return number


@transaction.atomic
def update_list(project_list: ProjectList, *, by: Membership, **changes) -> ProjectList:
    project = project_list.project
    _need(queries.can_manage(project, by))
    if unknown := changes.keys() - {"name", "wip_limit"}:
        raise ValueError(f"Not editable: {sorted(unknown)}")
    before = {"name": project_list.name, "wip_limit": project_list.wip_limit}
    if "name" in changes:
        project_list.name = _clean_text(changes["name"], field=_("name"), limit=60, required=True)
    if "wip_limit" in changes:
        project_list.wip_limit = _wip(changes["wip_limit"])
    project_list.save()
    after = {"name": project_list.name, "wip_limit": project_list.wip_limit}
    if changed := audit.diff(before, after):
        _audit(ProjectsAction.LIST_CHANGED, project, by, list=project_list.name, changes=changed)
    _bump(project.company_id, PULSE_PROJECTS)
    return project_list


@transaction.atomic
def delete_list(project_list: ProjectList, *, by: Membership) -> None:
    """Delete a list; its cards move to the first remaining list. The done list stays."""
    project = _lock_project(project_list.project)
    _need(queries.can_manage(project, by))
    if project_list.is_done:
        raise ProjectError(_("The done list stays; rename it instead."))
    target = (
        project.lists.filter(is_done=False)
        .exclude(pk=project_list.pk)
        .order_by("position", "pk")
        .first()
    )
    if target is None:
        raise ProjectError(_("A board needs at least one list besides Done."))
    start = queries.end_position(target)
    for offset, task_id in enumerate(
        Task.objects.filter(project_list=project_list)
        .order_by("list_position", "pk")
        .values_list("pk", flat=True)
    ):
        Task.objects.filter(pk=task_id).update(
            project_list=target, list_position=start + offset * 1024
        )
    name = project_list.name
    project_list.delete()
    _audit(ProjectsAction.LIST_DELETED, project, by, list=name, moved_to=target.name)
    _bump(project.company_id, PULSE_PROJECTS)


@transaction.atomic
def reorder_lists(project: Project, ids: list[int], *, by: Membership) -> list[ProjectList]:
    _need(queries.can_manage(project, by))
    lists = {row.pk: row for row in project.lists.select_for_update()}
    if sorted(int(i) for i in ids) != sorted(lists):
        raise ProjectError(_("Send every list of the board once."))
    for index, pk in enumerate(ids):
        row = lists[int(pk)]
        row.position = (index + 1) * 1024
        row.save(update_fields=["position", "updated_at"])
    _audit(ProjectsAction.LISTS_REORDERED, project, by, order=[lists[int(pk)].name for pk in ids])
    _bump(project.company_id, PULSE_PROJECTS)
    return sorted(lists.values(), key=lambda row: row.position)


# Cards ----------------------------------------------------------------------------------


def _next_number(project: Project) -> int:
    return (Card.objects.filter(project=project).aggregate(top=Max("number"))["top"] or 0) + 1


def place_card(
    task: Task,
    project: Project,
    *,
    project_list: ProjectList | None = None,
    position: float | None = None,
) -> None:
    """Give a task its board place and number (any path that puts a task on a project)."""
    if project_list is None:
        project_list = (
            queries.done_list(project)
            if task.status == Task.Status.DONE
            else queries.first_list(project)
        )
    if project_list is not None and position is None:
        position = queries.end_position(project_list)
    Task.objects.filter(pk=task.pk).update(
        project=project,
        project_list=project_list,
        list_position=position or 0,
        updated_at=timezone.now(),
    )
    if not Card.objects.filter(task=task).exists():
        Project.objects.select_for_update().filter(pk=project.pk).first()
        Card.objects.create(task=task, project=project, number=_next_number(project))
    task.project = project
    task.project_list = project_list
    task.list_position = position or 0


@transaction.atomic
def create_card(
    project: Project,
    *,
    by: Membership,
    title: str,
    project_list: ProjectList | None = None,
    assignee: Membership | None = None,
    due_at: datetime | None = None,
    priority: str = Task.Priority.NORMAL,
    description: str = "",
    milestone: Milestone | None = None,
    label_ids: list[int] | tuple = (),
    checklist: list[str] | tuple = (),
    proof: str = Proof.NONE,
    needs_confirmation: bool = False,
    start_on: date | None = None,
) -> Task:
    """A new card: a task made through `tasks.services.create_task` on this project's board.
    The task app decides who may hand out the work (tasks.assign, or this project's lead to its
    people) and checks the list and milestone; `receivers.task_saved` numbers the card, puts it
    at the end of its list (the first one by default) and adds the assignee as a member."""
    project = _lock_project(project)
    _need(queries.can_edit_cards(project, by), _("You can't add cards to this project."))
    if project.archived_at is not None:
        raise ProjectError(_("This project is archived."))
    task = task_services.create_task(
        by=by,
        title=title,
        description=description,
        assignee=assignee,
        due_at=due_at,
        priority=priority,
        proof=proof,
        needs_confirmation=needs_confirmation,
        checklist=list(checklist),
        project=project,
        project_list=project_list,
        milestone=milestone,
    )
    if start_on:
        Card.objects.filter(task=task).update(start_on=start_on)
    if label_ids:
        _set_labels(task, project, label_ids)
    _audit(ProjectsAction.CARD_CREATED, task, by, project=project.key, title=task.title)
    _bump(project.company_id, PULSE_PROJECTS)
    return Task.objects.select_related("card", "assignee__user", "project_list").get(pk=task.pk)


@transaction.atomic
def update_card(task: Task, *, by: Membership, **changes) -> Task:
    if unknown := changes.keys() - CARD_FIELDS:
        raise ValueError(f"Not editable: {sorted(unknown)}")
    project = task.project
    if project is None:
        raise ProjectError(_("This task isn't on a board."))
    is_assignee = task.assignee_id == by.pk
    _need(queries.can_edit_cards(project, by) or is_assignee)
    task_changes = {k: v for k, v in changes.items() if k in CARD_TASK_FIELDS}
    if task_changes:
        if not task_rules.can_manage(task, by):
            raise PermissionDenied(
                _("Only whoever gave this card can change its title and deadline.")
            )
        task = task_services.update_task(task, by=by, **task_changes)
    details = {}
    if "milestone" in changes:
        milestone = changes["milestone"]
        if milestone is not None and milestone.project_id != project.pk:
            raise ProjectError(_("That milestone is on another board."))
        Task.objects.filter(pk=task.pk).update(milestone=milestone, updated_at=timezone.now())
        details["milestone"] = milestone.name if milestone else None
    if "label_ids" in changes:
        _set_labels(task, project, changes["label_ids"])
        details["labels"] = sorted(changes["label_ids"])
    if "start_on" in changes:
        card, _created = Card.objects.get_or_create(
            task=task, defaults={"project": project, "number": _next_number(project)}
        )
        card.start_on = changes["start_on"]
        card.save(update_fields=["start_on"])
        details["start_on"] = str(changes["start_on"]) if changes["start_on"] else None
    if details:
        _audit(ProjectsAction.CARD_CHANGED, task, by, project=project.key, **details)
    _bump(project.company_id, PULSE_PROJECTS)
    return Task.objects.select_related("card", "assignee__user", "project_list", "milestone").get(
        pk=task.pk
    )


def _set_labels(task: Task, project: Project, label_ids) -> None:
    ids = {int(i) for i in label_ids}
    labels = set(Label.objects.filter(project=project, pk__in=ids).values_list("pk", flat=True))
    if labels != ids:
        raise ProjectError(_("Those labels aren't on this board."))
    TaskLabel.objects.filter(task=task).exclude(label_id__in=ids).delete()
    have = set(TaskLabel.objects.filter(task=task).values_list("label_id", flat=True))
    TaskLabel.objects.bulk_create(TaskLabel(task=task, label_id=pk) for pk in ids - have)


@transaction.atomic
def move_card(
    task: Task, project_list: ProjectList, position: float | None, *, by: Membership
) -> Task:
    """Put a card in a list at a position (a float between its neighbours; None: at the end).

    Into the done list, an open card runs the normal completion (`tasks.services.complete_task`)
    when it needs no proof and the mover is its assignee; one waiting for a check is confirmed
    when the mover may confirm it. Otherwise this raises `ProjectError(code="needs_proof")` and
    the client opens the card. A card that then waits for a check goes to the last list before
    Done. A done card stays in Done."""
    task = (
        Task.objects.select_for_update(of=("self",))
        .select_related("project", "assignee", "created_by", "company")
        .get(pk=task.pk)
    )
    project = task.project
    if project is None or project_list.project_id != project.pk:
        raise ProjectError(_("That list is on another board."))
    _need(queries.can_move_card(task, by), _("You can only move your own cards."))
    if project.archived_at is not None:
        raise ProjectError(_("This project is archived."))
    if position is None:  # "Move to" a list: after its last card
        position = (
            task.list_position
            if task.project_list_id == project_list.pk
            else queries.end_position(project_list)
        )
    try:
        position = float(position)
    except (TypeError, ValueError) as exc:
        raise ProjectError(_("Bad position.")) from exc
    if not math.isfinite(position):
        raise ProjectError(_("Bad position."))
    from_list = task.project_list
    if task.status == Task.Status.CANCELLED:
        raise ProjectError(_("This card was cancelled."))
    if task.status == Task.Status.DONE and not project_list.is_done:
        raise ProjectError(_("A finished card stays in Done."), code="done")
    target = project_list
    if project_list.is_done and task.status != Task.Status.DONE:
        if task.status == Task.Status.REVIEW:
            if not task_rules.can_review(task, by):
                raise ProjectError(
                    _("This card is waiting for a check by whoever assigned it."),
                    code="needs_review",
                )
            task_services.confirm_task(task, by=by)
        elif task.proof != Proof.NONE:
            raise ProjectError(
                _("This card needs a photo or a report to be finished. Open it to complete it."),
                code="needs_proof",
            )
        elif not task_rules.is_assignee(task, by):
            raise ProjectError(
                _("Only %(name)s can finish this card.") % {"name": str(task.assignee)},
                code="needs_proof",
            )
        else:
            task = task_services.complete_task(task, by=by)
            if task.status == Task.Status.REVIEW:
                target = queries.review_list(project) or from_list
                position = queries.end_position(target) if target is not None else position
    Task.objects.filter(pk=task.pk).update(
        project_list=target, list_position=position, updated_at=timezone.now()
    )
    _rebalance_if_needed(target, position)
    if from_list is None or target is None or from_list.pk != target.pk:
        _audit(
            ProjectsAction.CARD_MOVED,
            task,
            by,
            project=project.key,
            changes={
                "list": [from_list.name if from_list else None, target.name if target else None]
            },
        )
    _bump(project.company_id, PULSE_PROJECTS)
    return Task.objects.select_related("card", "assignee__user", "project_list").get(pk=task.pk)


def _rebalance_if_needed(project_list: ProjectList | None, position: float) -> None:
    """Spread a list's positions out again when two cards got too close to tell apart."""
    if project_list is None:
        return
    near = Task.objects.filter(
        project_list=project_list,
        list_position__gt=position - 1e-6,
        list_position__lt=position + 1e-6,
    ).count()
    if near <= 1:
        return
    for index, pk in enumerate(
        Task.objects.filter(project_list=project_list)
        .order_by("list_position", "pk")
        .values_list("pk", flat=True)
    ):
        Task.objects.filter(pk=pk).update(list_position=(index + 1) * 1024)


# Milestones and labels ------------------------------------------------------------------


@transaction.atomic
def create_milestone(
    project: Project,
    *,
    by: Membership,
    name: str,
    due_on: date | None = None,
    description: str = "",
) -> Milestone:
    _need(queries.can_manage(project, by))
    top = project.milestones.aggregate(top=Max("position"))["top"] or 0
    milestone = Milestone.objects.create(
        project=project,
        name=_clean_text(name, field=_("name"), limit=120, required=True),
        description=_clean_text(description, field="description", limit=4000),
        due_on=due_on,
        position=top + 1024,
    )
    _audit(
        ProjectsAction.MILESTONE_CREATED,
        project,
        by,
        milestone=milestone.name,
        due_on=str(due_on) if due_on else None,
    )
    _bump(project.company_id, PULSE_PROJECTS)
    return milestone


@transaction.atomic
def update_milestone(milestone: Milestone, *, by: Membership, **changes) -> Milestone:
    project = milestone.project
    _need(queries.can_manage(project, by))
    if unknown := changes.keys() - {"name", "description", "due_on", "status", "position"}:
        raise ValueError(f"Not editable: {sorted(unknown)}")
    before = audit.snapshot(milestone)
    if "name" in changes:
        milestone.name = _clean_text(changes["name"], field=_("name"), limit=120, required=True)
    if "description" in changes:
        milestone.description = _clean_text(changes["description"], field="description", limit=4000)
    if "due_on" in changes:
        if changes["due_on"] != milestone.due_on:
            milestone.missed_notified_at = None
        milestone.due_on = changes["due_on"]
    if "position" in changes:
        milestone.position = float(changes["position"])
    if "status" in changes:
        status = changes["status"]
        if status not in Milestone.Status.values:
            raise ProjectError(_("Unknown status."))
        if status == Milestone.Status.DONE and milestone.status != status:
            milestone.completed_at = timezone.now()
        elif status == Milestone.Status.OPEN:
            milestone.completed_at = None
        milestone.status = status
    milestone.save()
    if changed := audit.diff(before, audit.snapshot(milestone)):
        _audit(
            ProjectsAction.MILESTONE_CHANGED, project, by, milestone=milestone.name, changes=changed
        )
    _bump(project.company_id, PULSE_PROJECTS)
    return milestone


@transaction.atomic
def delete_milestone(milestone: Milestone, *, by: Membership) -> None:
    project = milestone.project
    _need(queries.can_manage(project, by))
    name = milestone.name
    milestone.delete()  # its cards stay, without a milestone
    _audit(ProjectsAction.MILESTONE_DELETED, project, by, milestone=name)
    _bump(project.company_id, PULSE_PROJECTS)


@transaction.atomic
def create_label(project: Project, *, by: Membership, name: str, color: str = "") -> Label:
    _need(queries.can_edit_cards(project, by))
    name = _clean_text(name, field=_("name"), limit=30, required=True)
    if project.labels.filter(name__iexact=name).exists():
        raise ProjectError(_("This board already has that label."))
    top = project.labels.aggregate(top=Max("position"))["top"] or 0
    label = Label.objects.create(
        project=project,
        name=name,
        color=_clean_color(color) or COLOR_KEYS[project.labels.count() % 8],
        position=top + 1024,
    )
    _audit(ProjectsAction.LABEL_CREATED, project, by, label=name)
    _bump(project.company_id, PULSE_PROJECTS)
    return label


@transaction.atomic
def update_label(label: Label, *, by: Membership, **changes) -> Label:
    project = label.project
    _need(queries.can_edit_cards(project, by))
    if unknown := changes.keys() - {"name", "color"}:
        raise ValueError(f"Not editable: {sorted(unknown)}")
    if "name" in changes:
        name = _clean_text(changes["name"], field=_("name"), limit=30, required=True)
        if project.labels.filter(name__iexact=name).exclude(pk=label.pk).exists():
            raise ProjectError(_("This board already has that label."))
        label.name = name
    if "color" in changes:
        label.color = _clean_color(changes["color"])
    label.save()
    _audit(ProjectsAction.LABEL_CHANGED, project, by, label=label.name)
    _bump(project.company_id, PULSE_PROJECTS)
    return label


@transaction.atomic
def delete_label(label: Label, *, by: Membership) -> None:
    project = label.project
    _need(queries.can_manage(project, by))
    name = label.name
    label.delete()
    _audit(ProjectsAction.LABEL_DELETED, project, by, label=name)
    _bump(project.company_id, PULSE_PROJECTS)


# Time -----------------------------------------------------------------------------------


def _work_target(
    by: Membership, *, task: Task | None, project: Project | None
) -> tuple[Task | None, Project | None]:
    """Check `by` may book time on the task or project, and return both (the task's project
    wins)."""
    if task is not None:
        if task.company_id != by.company_id:
            raise ProjectError(_("That task belongs to another company."))
        if task.project_id is not None:
            if project is not None and project.pk != task.project_id:
                raise ProjectError(_("That task is on another project."))
            project = task.project
        if task.assignee_id != by.pk and not (project and queries.can_edit_cards(project, by)):
            raise PermissionDenied(_("You can only track time on your own tasks."))
    if project is not None:
        if project.company_id != by.company_id:
            raise ProjectError(_("That project belongs to another company."))
        if project.archived_at is not None:
            raise ProjectError(_("This project is archived."))
        if not (
            queries.can_edit_cards(project, by) or (task is not None and task.assignee_id == by.pk)
        ):
            raise PermissionDenied(_("Only the project's members track time on it."))
    return task, project


@transaction.atomic
def start_timer(
    by: Membership, *, task: Task | None = None, project: Project | None = None, note: str = ""
) -> RunningTimer:
    """Start (or switch) the person's timer; a running one is stopped and logged first."""
    task, project = _work_target(by, task=task, project=project)
    _lock_person(by)
    current = RunningTimer.objects.select_for_update().filter(membership=by).first()
    if current is not None:
        _stop(current, by=by)
    timer = RunningTimer.objects.create(
        company_id=by.company_id,
        membership=by,
        task=task,
        project=project,
        started_at=timezone.now(),
        note=_clean_text(note, field="note", limit=300),
    )
    _bump(by.company_id, PULSE_TIME)
    return timer


@transaction.atomic
def stop_timer(by: Membership, *, now: datetime | None = None) -> TimeEntry | None:
    """Stop the person's timer and log what it measured (at least a minute, at most a day).
    None when no timer was running."""
    _lock_person(by)
    current = RunningTimer.objects.select_for_update().filter(membership=by).first()
    if current is None:
        return None
    return _stop(current, by=by, now=now)


def _stop(timer: RunningTimer, *, by: Membership, now: datetime | None = None) -> TimeEntry | None:
    now = now or timezone.now()
    tz = ZoneInfo(by.company.timezone)
    minutes = max(1, min(1440, round((now - timer.started_at).total_seconds() / 60)))
    day = timezone.localtime(timer.started_at, tz).date()
    task, project = timer.task, timer.project
    timer.delete()
    if project is not None and project.archived_at is not None:
        return None
    used = (
        TimeEntry.objects.filter(membership=by, day=day).aggregate(total=Sum("minutes"))["total"]
        or 0
    )
    minutes = min(minutes, 1440 - used)
    if minutes <= 0:
        return None
    entry = TimeEntry.objects.create(
        company_id=by.company_id,
        membership=by,
        project=project,
        task=task,
        day=day,
        minutes=minutes,
        note=timer.note,
        source=TimeEntry.Source.TIMER,
        created_by=by,
    )
    _audit(ProjectsAction.TIME_LOGGED, entry, by, minutes=minutes, day=str(day), source="timer")
    _bump(by.company_id, PULSE_TIME, PULSE_PROJECTS)
    return entry


def _check_minutes(minutes) -> int:
    try:
        minutes = int(minutes)
    except (TypeError, ValueError) as exc:
        raise ProjectError(_("Time is a whole number of minutes.")) from exc
    if not 1 <= minutes <= 1440:
        raise ProjectError(_("Log between 1 minute and 24 hours."))
    return minutes


def _check_day(company, day: date) -> date:
    today = queries.local_today(company)
    if day > today:
        raise ProjectError(_("You can't log time for a day that hasn't come yet."))
    if day < today - timedelta(days=366):
        raise ProjectError(_("That day is too long ago."))
    return day


def _check_daily_total(
    membership: Membership, day: date, minutes: int, *, exclude: int | None = None
) -> None:
    used = TimeEntry.objects.filter(membership=membership, day=day)
    if exclude is not None:
        used = used.exclude(pk=exclude)
    if (used.aggregate(total=Sum("minutes"))["total"] or 0) + minutes > 1440:
        raise ProjectError(_("That's more than 24 hours on one day."))


@transaction.atomic
def log_time(
    by: Membership,
    *,
    day: date,
    minutes: int,
    project: Project | None = None,
    task: Task | None = None,
    note: str = "",
    billable: bool = False,
    membership: Membership | None = None,
) -> TimeEntry:
    """Log time by hand: for oneself, or for a member of a project one manages."""
    person = membership or by
    if person.pk != by.pk:
        if person.company_id != by.company_id:
            raise ProjectError(_("That person isn't in this company."))
        target_project = project or (task.project if task else None)
        _need(
            target_project is not None and queries.can_manage(target_project, by),
            _("You can only log time for others on projects you manage."),
        )
        _check_member(by.company, person)
        if queries.role_of(target_project, person) is None:
            raise ProjectError(_("%(name)s isn't on this project.") % {"name": str(person)})
    task, project = _work_target(by, task=task, project=project)
    minutes = _check_minutes(minutes)
    day = _check_day(by.company, day)
    _lock_person(person)
    _check_daily_total(person, day, minutes)
    entry = TimeEntry.objects.create(
        company_id=by.company_id,
        membership=person,
        project=project,
        task=task,
        day=day,
        minutes=minutes,
        note=_clean_text(note, field="note", limit=300),
        billable=bool(billable),
        source=TimeEntry.Source.MANUAL,
        created_by=by,
    )
    _audit(ProjectsAction.TIME_LOGGED, entry, by, minutes=minutes, day=str(day), person=str(person))
    _bump(by.company_id, PULSE_TIME, PULSE_PROJECTS)
    return entry


def _may_edit_entry(entry: TimeEntry, by: Membership) -> bool:
    if entry.membership_id == by.pk:
        return True
    return entry.project is not None and queries.can_manage(entry.project, by)


@transaction.atomic
def update_time_entry(entry: TimeEntry, *, by: Membership, **changes) -> TimeEntry:
    if unknown := changes.keys() - {"minutes", "day", "note", "billable"}:
        raise ValueError(f"Not editable: {sorted(unknown)}")
    _need(_may_edit_entry(entry, by), _("You can only change your own time."))
    _lock_person(entry.membership)
    before = audit.snapshot(entry)
    if "minutes" in changes:
        entry.minutes = _check_minutes(changes["minutes"])
    if "day" in changes:
        entry.day = _check_day(entry.company, changes["day"])
    if "note" in changes:
        entry.note = _clean_text(changes["note"], field="note", limit=300)
    if "billable" in changes:
        entry.billable = bool(changes["billable"])
    _check_daily_total(entry.membership, entry.day, entry.minutes, exclude=entry.pk)
    entry.save()
    if changed := audit.diff(before, audit.snapshot(entry)):
        _audit(ProjectsAction.TIME_CHANGED, entry, by, changes=changed)
    _bump(entry.company_id, PULSE_TIME, PULSE_PROJECTS)
    return entry


@transaction.atomic
def delete_time_entry(entry: TimeEntry, *, by: Membership) -> None:
    _need(_may_edit_entry(entry, by), _("You can only delete your own time."))
    _audit(ProjectsAction.TIME_DELETED, entry, by, minutes=entry.minutes, day=str(entry.day))
    company_id = entry.company_id
    entry.delete()
    _bump(company_id, PULSE_TIME, PULSE_PROJECTS)


# Updates, files, links ------------------------------------------------------------------


@transaction.atomic
def post_update(project: Project, *, by: Membership, health: str, text: str = "") -> ProjectUpdate:
    _need(
        queries.can_post_update(project, by), _("Only the project's lead and members post updates.")
    )
    if health not in Health.values:
        raise ProjectError(_("Say how the project is going: on track, at risk or off track."))
    update = ProjectUpdate.objects.create(
        project=project,
        author=by,
        health=health,
        text=_clean_text(text, field="text", limit=MAX_UPDATE_LENGTH),
    )
    _audit(ProjectsAction.UPDATE_POSTED, project, by, health=health)
    _bump(project.company_id, PULSE_PROJECTS)
    return update


@transaction.atomic
def add_file(project: Project, *, by: Membership, upload, name: str = "") -> ProjectFile:
    _need(queries.can_edit_cards(project, by))
    clean = uploads.accept_document(upload, allowed=("pdf", "xlsx", "csv", "image"))
    extension = clean.name.rsplit(".", 1)[-1].lower()
    kind = "image" if extension in ("jpg", "jpeg", "png", "webp") else extension
    display = (
        _clean_text(name or getattr(upload, "name", "") or clean.name, field="name", limit=200)
        or clean.name
    )
    row = ProjectFile(project=project, name=display, kind=kind, size=clean.size, uploaded_by=by)
    row.file.save(clean.name, clean, save=False)
    row.save()
    _audit(ProjectsAction.FILE_ADDED, project, by, file=display)
    _bump(project.company_id, PULSE_PROJECTS)
    return row


@transaction.atomic
def delete_file(row: ProjectFile, *, by: Membership) -> None:
    project = row.project
    _need(queries.can_manage(project, by) or row.uploaded_by_id == by.pk)
    name = row.name
    stored = row.file.name
    storage = row.file.storage
    row.delete()
    transaction.on_commit(partial(storage.delete, stored))
    _audit(ProjectsAction.FILE_DELETED, project, by, file=name)
    _bump(project.company_id, PULSE_PROJECTS)


@transaction.atomic
def add_link(project: Project, *, by: Membership, title: str, url: str) -> ProjectLink:
    _need(queries.can_edit_cards(project, by))
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.IGNORECASE) or len(url) > 500:
        raise ProjectError(_("Links start with http:// or https://."))
    link = ProjectLink.objects.create(
        project=project,
        title=_clean_text(title, field=_("title"), limit=120) or url[:120],
        url=url,
        added_by=by,
    )
    _audit(ProjectsAction.LINK_ADDED, project, by, link=link.title)
    _bump(project.company_id, PULSE_PROJECTS)
    return link


@transaction.atomic
def delete_link(link: ProjectLink, *, by: Membership) -> None:
    project = link.project
    _need(queries.can_manage(project, by) or link.added_by_id == by.pk)
    title = link.title
    link.delete()
    _audit(ProjectsAction.LINK_DELETED, project, by, link=title)
    _bump(project.company_id, PULSE_PROJECTS)


# Money ----------------------------------------------------------------------------------


def expense_accounts(member: Membership):
    """Accounts `member` may record an expense on: every active one in their branch scope with
    `finance.manage`, else the ones they operate or hold."""
    from apps.finance.models import MoneyAccount

    accounts = MoneyAccount.objects.for_company(member.company_id).filter(is_active=True)
    if not member.has_perm(Perm.FINANCE_RECORD):
        return accounts.none()
    if member.has_perm(Perm.FINANCE_MANAGE):
        scope = branch_ids(member)
        if scope is None:
            return accounts
        return accounts.filter(branch_id__in=scope)
    return accounts.filter(Q(operators=member) | Q(holder=member)).distinct()


@transaction.atomic
def add_expense(
    project: Project,
    *,
    by: Membership,
    amount,
    account,
    category,
    occurred_on: date,
    description: str = "",
    counterparty=None,
):
    """Record an expense on the project through the finance ledger
    (`finance.services.record_transaction(project=…)`)."""
    from apps.finance import services as finance

    _need(by.has_perm(Perm.FINANCE_RECORD), _("You can't record expenses."))
    _need(queries.can_view(project, by))
    if project.archived_at is not None:
        raise ProjectError(_("This project is archived."))
    if not expense_accounts(by).filter(pk=account.pk).exists():
        raise PermissionDenied(_("You can't record on this account."))
    if category is None or category.kind != "expense":
        raise ProjectError(_("Pick an expense category."))
    return finance.record_transaction(
        project.company,
        by=by,
        kind="expense",
        amount=amount,
        account=account,
        category=category,
        counterparty=counterparty,
        occurred_on=occurred_on,
        description=_clean_text(description, field="description", limit=300) or project.name[:300],
        project=project,
    )


# Settings -------------------------------------------------------------------------------


@transaction.atomic
def update_settings(company, *, by: Membership, **changes) -> ProjectSettings:
    _need(
        by.company_id == company.pk
        and (by.has_perm(Perm.COMPANY_SETTINGS) or by.has_perm(Perm.PROJECTS_MANAGE))
    )
    if unknown := changes.keys() - {
        "default_lists",
        "weekly_nudge",
        "nudge_weekday",
        "at_risk_days",
        "at_risk_percent",
    }:
        raise ValueError(f"Not editable: {sorted(unknown)}")
    settings = conf.get_settings(company)
    before = audit.snapshot(settings)
    if "default_lists" in changes:
        names = [str(n).strip()[:60] for n in changes["default_lists"] or [] if str(n).strip()]
        if names and len(names) < 2:
            raise ProjectError(_("A board starts with at least two lists, the last one is Done."))
        if len(names) > 12:
            raise ProjectError(_("A board starts with at most 12 lists."))
        settings.default_lists = names
    if "weekly_nudge" in changes:
        settings.weekly_nudge = bool(changes["weekly_nudge"])
    if "nudge_weekday" in changes:
        if int(changes["nudge_weekday"]) not in range(7):
            raise ProjectError(_("Pick a day of the week."))
        settings.nudge_weekday = int(changes["nudge_weekday"])
    if "at_risk_days" in changes:
        if not 1 <= int(changes["at_risk_days"]) <= 90:
            raise ProjectError(_("Between 1 and 90 days."))
        settings.at_risk_days = int(changes["at_risk_days"])
    if "at_risk_percent" in changes:
        if not 1 <= int(changes["at_risk_percent"]) <= 100:
            raise ProjectError(_("Between 1 and 100 percent."))
        settings.at_risk_percent = int(changes["at_risk_percent"])
    settings.save()
    if changed := audit.diff(before, audit.snapshot(settings)):
        audit.record(
            ProjectsAction.SETTINGS_CHANGED,
            company_id=company.pk,
            actor=by.user,
            target=settings,
            changes=changed,
        )
    _bump(company.pk, PULSE_PROJECTS)
    return settings


# Due dates ------------------------------------------------------------------------------


def due_at_for(company, day: date, *, keep: datetime | None = None) -> datetime:
    """A deadline on `day` at the time of `keep` (else 18:00), in the company's timezone."""
    tz = ZoneInfo(company.timezone)
    at = timezone.localtime(keep, tz).time() if keep else time(18, 0)
    return datetime.combine(day, at, tzinfo=tz)


@transaction.atomic
def reschedule_card(task: Task, *, by: Membership, start_on: date, end_on: date) -> Task:
    """Timeline drag: the card's planned start and its deadline (same time of day)."""
    if end_on < start_on:
        raise ProjectError(_("The end can't be before the start."))
    changes: dict = {"start_on": start_on}
    if (
        task.due_at is None
        or timezone.localtime(task.due_at, ZoneInfo(task.company.timezone)).date() != end_on
    ):
        changes["due_at"] = due_at_for(task.company, end_on, keep=task.due_at)
    return update_card(task, by=by, **changes)
