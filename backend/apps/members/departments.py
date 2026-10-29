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
# What heading a department amounts to, for the people below: who may choose heads holds it.
HEAD_RIGHTS = (Perm.TASKS_ASSIGN, Perm.TASKS_CONFIRM, Perm.TASKS_VIEW_ALL)


class Org:
    """A company's departments in memory: one query, then every tree question without more."""

    def __init__(self, company_id: int):
        self.departments: dict[int, Department] = {
            department.pk: department
            for department in Department.objects.filter(company_id=company_id).select_related(
                "head__user", "head__role"
            )
        }
        self.children: dict[int | None, list[int]] = defaultdict(list)
        for department in sorted(self.departments.values(), key=lambda d: (d.name.lower(), d.pk)):
            parent = department.parent_id if department.parent_id in self.departments else None
            self.children[parent].append(department.pk)
        # Parents before children, siblings by name; depth 1 at the top. Walked without
        # recursion, so a deep tree can't overflow the stack.
        self.order: list[int] = []
        self.depths: dict[int, int] = {}
        stack = [(pk, 1) for pk in reversed(self.children.get(None, ()))]
        while stack:
            pk, depth = stack.pop()
            if pk in self.depths:
                continue
            self.depths[pk] = depth
            self.order.append(pk)
            stack.extend((child, depth + 1) for child in reversed(self.children.get(pk, ())))
        # Member -> the departments they head, in tree order.
        self.heads: dict[int, list[int]] = defaultdict(list)
        for pk in self.order:
            if (head_id := self.departments[pk].head_id) is not None:
                self.heads[head_id].append(pk)

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
        return list(self.heads.get(member_id, ()))

    def managed(self, member_id: int) -> set[int]:
        """The departments a member manages: the ones they head and everything below."""
        return self.below(self.headed_by(member_id))

    def anchor(self, member_id: int, department_id: int | None) -> int | None:
        """Where someone sits in the tree: the highest of the departments they head and the one
        they're in (one they head wins a tie). Heads and teams are reckoned from it, so the
        chain of command can't loop: whoever sits higher is never managed from below."""
        options = [(self.depths[pk], 0, pk) for pk in self.heads.get(member_id, ())]
        if department_id in self.depths:
            options.append((self.depths[department_id], 1, department_id))
        return min(options)[2] if options else None

    def head_above(self, person: Membership) -> Membership | None:
        """The person's own head: going up from where they sit (`anchor`), the first approved
        head who isn't them. An owner's head can only be another owner."""
        owner = is_owner(person)
        pk, seen = self.anchor(person.pk, person.department_id), set()
        while pk is not None and pk not in seen:
            seen.add(pk)
            department = self.departments[pk]
            head = department.head
            if (
                head is not None
                and head.pk != person.pk
                and head.status == Membership.Status.APPROVED
                and (is_owner(head) or not owner)
            ):
                return head
            pk = department.parent_id
        return None

    def depth(self, pk: int) -> int:
        return self.depths.get(pk, 0)

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
        return list(self.order)


def is_owner(member: Membership) -> bool:
    return member.role_id is not None and member.role.is_owner


def is_top_manager(member: Membership) -> bool:
    """Who uses the owner bot (the owner, 29.10.2026: "only top and owner managers can use the
    owner bot"): owners, people whose role runs every branch and gives work (a Manager), and
    the heads of top-level departments. Other heads work from the employee bot."""
    if member.status != Membership.Status.APPROVED:
        return False
    if is_owner(member):
        return True
    if member.has_perm(Perm.BRANCHES_ALL) and member.has_perm(Perm.TASKS_ASSIGN):
        return True
    return Department.objects.filter(
        company_id=member.company_id, head_id=member.pk, parent__isnull=True
    ).exists()


# Whom a member manages --------------------------------------------------------------------------


def team_ids(member: Membership, org: Org | None = None) -> frozenset[int]:
    """The memberships `member` manages: the current people who sit (`Org.anchor`) in a
    department they head or below it; never themselves, and an owner only when they're an
    owner too. Cached on the member object; `org` saves loading the tree again (without it,
    someone who heads nothing costs one query)."""
    cached = getattr(member, "_team_ids", None)
    if cached is not None:
        return cached
    team: frozenset[int] = frozenset()
    if member.pk and member.status == Membership.Status.APPROVED:
        if (
            org is None
            and Department.objects.filter(company_id=member.company_id, head_id=member.pk).exists()
        ):
            org = Org(member.company_id)
        if org is not None and org.heads.get(member.pk):
            team = _team(org, member)
    member._team_ids = team
    return team


def _team(org: Org, member: Membership) -> frozenset[int]:
    managed = org.managed(member.pk)
    heads = {org.departments[pk].head_id for pk in managed} - {None}
    sees_owners = is_owner(member)
    candidates = (
        Membership.objects.filter(company_id=member.company_id, status__in=CURRENT)
        .filter(Q(department_id__in=managed) | Q(pk__in=heads))
        .values_list("pk", "department_id", "role__is_owner")
    )
    return frozenset(
        pk
        for pk, department_id, owner in candidates
        if pk != member.pk
        and org.anchor(pk, department_id) in managed
        and (sees_owners or not owner)
    )


def manages(member: Membership, person: Membership) -> bool:
    return person.pk != member.pk and person.pk in team_ids(member)


def leads(member: Membership) -> bool:
    """Whether the member manages anyone through departments."""
    return bool(team_ids(member))


def manager_of(person: Membership, org: Org | None = None) -> Membership | None:
    """The person's own head, or None."""
    org = org if org is not None else Org(person.company_id)
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
    _apply(department, {"name": name, "parent": parent, "head": head}, by=by)
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
    changes = _apply(department, fields, by=by)
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
    # Free its name first: a part named like it ("Savdo" in "Savdo") moves up into its place.
    Department.objects.filter(pk=department.pk).update(name=f"~{department.pk}")
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
        if is_owner(person) and not is_owner(by) and person.pk != by.pk:
            raise PermissionDenied(_("Only owners can change an owner."))
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


def _apply(department: Department, fields: dict, *, by: Membership) -> dict:
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
        if head is not None and head.pk != department.head_id and not _may_appoint(by):
            raise PermissionDenied(
                _("Only owners, and people who give and check tasks themselves, choose heads.")
            )
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


def _may_appoint(by: Membership) -> bool:
    """A head gives, sees and checks their people's work: only someone holding those rights
    themselves (an owner holds every right) hands them out (the role rules' rule 2)."""
    from apps.members.services import may_grant

    return may_grant(by, HEAD_RIGHTS)


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
