"""Departments: the company's structure as a tree, each department with a head (the owner,
26.10.2026: "department head assigning tasks, and also their own head? like manager high top
manager like thing").

A head manages everyone in their department and in every department below it, the heads of those
departments included; nobody manages themselves. A person's own head is the nearest head above
them. Managing lets a head give their people work, see and check it, nudge them and answer their
"can't do it" and "need more time" (apps.tasks), and late work reaches the person's head
(apps.reminders). Roles are unchanged; a company without departments works as before.

    Org(company_id)                 the tree, loaded once and asked in memory
    team_ids / manages / leads      whom a member manages (cached on the member object)
    manager_of                      a person's head
    assignable                      whom a member may give work to (bot and app pickers)
    create / update / delete / place    the structure (members.manage with every branch)
"""

from collections import defaultdict

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.companies.models import Company
from apps.core.exceptions import DomainError
from apps.members import scope
from apps.members.audit_actions import MemberAction
from apps.members.models import Department, Membership
from apps.members.permissions import Perm

# Members who count as people of a department (a suspended one keeps their place).
CURRENT = (Membership.Status.APPROVED, Membership.Status.SUSPENDED)
# "Leave this as it is" for update_department's fields.
UNSET = object()
# People placed into a department in one go at most.
PLACE_LIMIT = 200


class Org:
    """A company's departments in memory: one query, then every tree question without more."""

    def __init__(self, company_id: int):
        self.departments: dict[int, Department] = {
            department.pk: department
            for department in Department.objects.filter(company_id=company_id).select_related(
                "head__user"
            )
        }
        self.children: dict[int | None, list[int]] = defaultdict(list)
        for department in sorted(self.departments.values(), key=lambda d: (d.name.lower(), d.pk)):
            self.children[department.parent_id].append(department.pk)

    def __bool__(self) -> bool:
        return bool(self.departments)

    def below(self, ids) -> set[int]:
        """`ids` and every department under them."""
        found: set[int] = set()
        todo = [pk for pk in ids if pk in self.departments]
        while todo:
            pk = todo.pop()
            if pk not in found:
                found.add(pk)
                todo.extend(self.children.get(pk, ()))
        return found

    def headed_by(self, member_id: int) -> list[int]:
        return [pk for pk in self.in_tree_order() if self.departments[pk].head_id == member_id]

    def managed(self, member_id: int) -> set[int]:
        """The departments a member manages: the ones they head and everything below."""
        return self.below(self.headed_by(member_id))

    def head_above(self, person: Membership) -> Membership | None:
        """The person's own head: going up from their department (or, when they're in none, the
        highest one they head), the first approved head who isn't them."""
        start = person.department_id if person.department_id in self.departments else None
        if start is None:
            headed = self.headed_by(person.pk)
            start = min(headed, key=self.depth) if headed else None
        pk, seen = start, set()
        while pk is not None and pk not in seen:
            seen.add(pk)
            department = self.departments[pk]
            head = department.head
            approved = head is not None and head.status == Membership.Status.APPROVED
            if approved and head.pk != person.pk:
                return head
            pk = department.parent_id
        return None

    def depth(self, pk: int) -> int:
        depth, seen = 0, set()
        while pk is not None and pk not in seen:
            seen.add(pk)
            pk = self.departments[pk].parent_id
            depth += 1
        return depth

    def path(self, pk: int) -> list[str]:
        """Names from the top down to the department."""
        names, seen = [], set()
        while pk is not None and pk not in seen:
            seen.add(pk)
            names.append(self.departments[pk].name)
            pk = self.departments[pk].parent_id
        return names[::-1]

    def in_tree_order(self) -> list[int]:
        """Parents before their children, siblings by name."""
        ordered: list[int] = []

        def walk(parent):
            for pk in self.children.get(parent, ()):
                ordered.append(pk)
                walk(pk)

        walk(None)
        return ordered


# Whom a member manages --------------------------------------------------------------------------


def team_ids(member: Membership) -> frozenset[int]:
    """The memberships `member` manages: current people of the departments they head and of
    every department below, with those departments' heads; never themselves. Cached on the
    member object (one query for someone who heads nothing)."""
    cached = getattr(member, "_team_ids", None)
    if cached is not None:
        return cached
    team: frozenset[int] = frozenset()
    if member.pk and member.status == Membership.Status.APPROVED:
        heads_something = Department.objects.filter(
            company_id=member.company_id, head_id=member.pk
        ).exists()
        if heads_something:
            org = Org(member.company_id)
            managed = org.managed(member.pk)
            people = set(
                Membership.objects.filter(
                    company_id=member.company_id, department_id__in=managed, status__in=CURRENT
                ).values_list("pk", flat=True)
            )
            heads = {
                org.departments[pk].head_id
                for pk in managed
                if org.departments[pk].head is not None
                and org.departments[pk].head.status in CURRENT
            }
            team = frozenset((people | heads) - {member.pk})
    member._team_ids = team
    return team


def manages(member: Membership, person: Membership) -> bool:
    return person.pk != member.pk and person.pk in team_ids(member)


def leads(member: Membership) -> bool:
    """Whether the member manages anyone through departments."""
    return bool(team_ids(member))


def manager_of(person: Membership) -> Membership | None:
    """The person's own head, or None."""
    org = Org(person.company_id)
    return org.head_above(person) if org else None


def assignable(member: Membership) -> QuerySet[Membership]:
    """Registered people `member` may give work to: everyone in their branch scope with
    tasks.assign, and the people they manage (themselves left out)."""
    people = Membership.objects.for_company(member.company_id).filter(
        status=Membership.Status.APPROVED, onboarded_at__isnull=False
    )
    team = team_ids(member)
    if not member.has_perm(Perm.TASKS_ASSIGN):
        people = people.filter(pk__in=team)
    elif team:
        scoped = scope.restrict(people, scope.branch_ids(member), field="branches")
        people = people.filter(Q(pk__in=scoped.values("pk")) | Q(pk__in=team))
    else:
        people = scope.restrict(people, scope.branch_ids(member), field="branches")
    return people.exclude(pk=member.pk)


def counts(company_id: int) -> dict[int, int]:
    """Current people directly in each department."""
    return dict(
        Membership.objects.filter(
            company_id=company_id, status__in=CURRENT, department__isnull=False
        )
        .values_list("department_id")
        .annotate(people=Count("pk"))
        .values_list("department_id", "people")
    )


# Changing the structure -------------------------------------------------------------------------


def may_edit_structure(member: Membership) -> bool:
    """Owners, and people who edit members and see every branch: the tree is company-wide."""
    return member.has_perm(Perm.MEMBERS_MANAGE) and scope.branch_ids(member) is None


@transaction.atomic
def create_department(
    company: Company,
    *,
    by: Membership,
    name: str,
    parent: Department | None = None,
    head: Membership | None = None,
) -> Department:
    _ensure_editor(company, by)
    _lock(company)
    department = Department(company=company)
    _apply(department, {"name": name, "parent": parent, "head": head})
    department.save()
    audit.record(
        MemberAction.DEPARTMENT_CREATED, company_id=company.pk, actor=by.user, target=department
    )
    _bump(company.pk)
    return department


@transaction.atomic
def update_department(department: Department, *, by: Membership, **fields) -> Department:
    """Change any of `name`, `parent`, `head` (None clears the parent or the head)."""
    unknown = set(fields) - {"name", "parent", "head"}
    if unknown:
        raise TypeError(f"update_department: unknown fields {sorted(unknown)}")
    _ensure_editor(department.company, by)
    _lock(department.company)
    department = Department.objects.select_related("company", "head").get(pk=department.pk)
    changes = _apply(department, fields)
    if not changes:
        return department
    department.save()
    audit.record(
        MemberAction.DEPARTMENT_CHANGED,
        company_id=department.company_id,
        actor=by.user,
        target=department,
        changes=changes,
    )
    _bump(department.company_id, people=True)
    return department


@transaction.atomic
def delete_department(department: Department, *, by: Membership) -> None:
    """Its people and its sub-departments move up to its parent (to the top level, and to no
    department, when it has none)."""
    _ensure_editor(department.company, by)
    _lock(department.company)
    department = Department.objects.select_related("company", "parent").get(pk=department.pk)
    children = list(Department.objects.filter(parent=department))
    taken = set(
        Department.objects.filter(company_id=department.company_id, parent=department.parent)
        .exclude(pk=department.pk)
        .values_list("name", flat=True)
    )
    for child in children:
        if child.name.lower() in {name.lower() for name in taken}:
            raise DomainError(
                _("«%(name)s» already exists there. Rename one of them first.")
                % {"name": child.name}
            )
    Department.objects.filter(parent=department).update(parent=department.parent)
    Membership.objects.filter(department=department).update(department=department.parent)
    audit.record(
        MemberAction.DEPARTMENT_DELETED,
        company_id=department.company_id,
        actor=by.user,
        target=department,
    )
    company_id = department.company_id
    department.delete()
    _bump(company_id, people=True)


@transaction.atomic
def place(department: Department, *, by: Membership, people: list[Membership]) -> int:
    """Put people into `department` (they leave their old one): members.manage, people in the
    member's branch scope. Returns how many moved."""
    from apps.members import queries

    if department.company_id != by.company_id or not by.has_perm(Perm.MEMBERS_MANAGE):
        raise PermissionDenied(_("You don't have permission to do this."))
    moved = 0
    for person in people:
        if person.company_id != department.company_id or person.status not in CURRENT:
            raise DomainError(_("Only current members of your company can be placed."))
        if not queries.in_scope(by, person):
            raise PermissionDenied(
                _("%(name)s works in a branch you don't manage.") % {"name": person}
            )
        if person.department_id == department.pk:
            continue
        old = person.department.name if person.department_id else None
        Membership.objects.filter(pk=person.pk).update(department=department)
        audit.record(
            MemberAction.CHANGED,
            company_id=department.company_id,
            actor=by.user,
            target=person,
            changes={"department": [old, department.name]},
        )
        moved += 1
    if moved:
        _bump(department.company_id, people=True)
    return moved


def _apply(department: Department, fields: dict) -> dict:
    """Check `fields` and set them on `department`; returns {field: [before, after]}."""
    company_id = department.company_id
    org = Org(company_id)
    changes = {}
    if "name" in fields:
        name = " ".join(str(fields["name"] or "").split())
        if not name:
            raise DomainError(_("Give the department a name."))
        if len(name) > 100:
            raise DomainError(_("A department's name can be at most 100 characters."))
        if name != department.name:
            changes["name"] = [department.name or None, name]
        department.name = name
    if "parent" in fields:
        parent = fields["parent"]
        if parent is not None:
            if parent.company_id != company_id:
                raise DomainError(_("Pick a department of this company."))
            if department.pk and parent.pk in org.below([department.pk]):
                raise DomainError(_("A department can't go under itself or its own part."))
        if (parent.pk if parent else None) != department.parent_id:
            before = org.departments.get(department.parent_id)
            changes["parent"] = [before.name if before else None, parent.name if parent else None]
        department.parent = parent
    if "head" in fields:
        head = fields["head"]
        if head is not None and (
            head.company_id != company_id or head.status != Membership.Status.APPROVED
        ):
            raise DomainError(_("The head must be a current member of the company."))
        if (head.pk if head else None) != department.head_id:
            changes["head"] = [
                str(department.head) if department.head_id else None,
                str(head) if head else None,
            ]
        department.head = head
    siblings = Department.objects.filter(
        company_id=company_id, parent_id=department.parent_id, name__iexact=department.name
    ).exclude(pk=department.pk)
    if siblings.exists():
        raise DomainError(
            _("There's already a department named «%(name)s» there.") % {"name": department.name}
        )
    return changes


def _ensure_editor(company: Company, by: Membership) -> None:
    if by.company_id != company.pk or not may_edit_structure(by):
        raise PermissionDenied(_("Only owners and people who manage every branch can do this."))


def _lock(company: Company) -> None:
    """One structure change at a time per company (moves are checked against the whole tree)."""
    Company.objects.select_for_update().filter(pk=company.pk).first()


def _bump(company_id: int, *, people: bool = False) -> None:
    from apps.members.services import bump_on_commit

    keys = ["members.departments", "members.people"] if people else ["members.departments"]
    bump_on_commit(company_id, *keys)
