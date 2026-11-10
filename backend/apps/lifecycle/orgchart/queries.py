"""The org chart in one read (docs/PLAN-OWNER.md §13.4 "Org chart").

`chart(company, viewer)` gives everything the page draws, for both of its views:

- the owners, on top;
- the departments (the tree of `members.departments.Org`, as `hr.queries.org` reads it): parent,
  depth, head, and the headcount the viewer sees directly in each and in all below it;
- the branches with their manager (`Branch.manager`) and headcount by home branch;
- every current person the viewer sees: position, department, home branch (and the branch the
  branch view puts them under), their manager (their nearest head, `departments.manager_of`),
  small statuses (suspended until, on leave until, leaving on, a job change waiting) and
  `may_move`: whether the viewer may propose a job change for them (`job_changes.may_propose`),
  with the reason when not;
- open vacancies (hiring) as places: their branch, and the department where people of the same
  position work (in that branch first), which is where the department view puts them.

Branch scope (§2.6): a manager sees the people of their branches, those branches, and the
departments those people are in or head (with every department above them, so the tree
holds); owners see everything. A fixed number of queries, whatever the size of the company.
"""

from collections import Counter, defaultdict

from django.db.models import Count, Q

from apps.hr import queries as hr_queries
from apps.lifecycle import job_changes
from apps.lifecycle.models import JobChange, Termination
from apps.members import departments, scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import photo_url

# Why someone can't be moved by the viewer.
RIGHTS, SELF, OWNER = "rights", "self", "owner"
CURRENT = hr_queries.CURRENT


def why_not(viewer: Membership, person: Membership) -> str | None:
    """None when `viewer` may propose a job change for `person` (already in their scope);
    else why not: no right to (hr.manage), it is themselves, or an owner and they aren't one."""
    if job_changes.may_propose(viewer, person, in_scope=True):
        return None
    if person.pk == viewer.pk:
        return SELF
    if viewer.has_perm(Perm.HR_MANAGE) and departments.is_owner(person):
        return OWNER
    return RIGHTS


def _ref(member: Membership) -> dict:
    return {
        "id": member.pk,
        "name": str(member),
        "photo_url": photo_url(member),
        "position": member.position.name if member.position_id else None,
    }


def chart(company, viewer: Membership) -> dict:
    today = hr_queries.today(company)
    branch_ids = scope.branch_ids(viewer)
    tree = departments.Org(company.pk)
    people = list(
        hr_queries.people(company, branch_ids=branch_ids)
        .select_related("user", "role", "position", "department", "home_branch")
        .prefetch_related("branches")
        .order_by("first_name", "last_name", "pk")
    )
    ids = [person.pk for person in people]

    branches = company.branches.filter(is_active=True).select_related(
        "manager__user", "manager__position"
    )
    if branch_ids is not None:
        branches = branches.filter(pk__in=branch_ids)
    branches = list(branches.order_by("order", "name", "pk"))
    shown_branches = [branch.pk for branch in branches]

    rows = [_person(person, viewer, tree, shown_branches) for person in people]
    _statuses(company, rows, ids, today)

    positions = {person.position_id: person.position for person in people if person.position_id}
    vacancies = _vacancies(company, branch_ids, rows, positions)

    # The departments the viewer's part of the tree needs.
    if branch_ids is None:
        shown = set(tree.order)
    else:
        needed = {row["department_id"] for row in rows if row["department_id"]}
        needed |= {pk for row in rows for pk in tree.headed_by(row["id"])}
        needed |= {row["department_id"] for row in vacancies if row["department_id"]}
        shown = set()
        for pk in needed:
            while pk is not None and pk in tree.departments and pk not in shown:
                shown.add(pk)
                pk = tree.departments[pk].parent_id

    direct = Counter(row["department_id"] for row in rows if row["department_id"])
    total = dict(direct)
    for pk in reversed(tree.order):
        parent = tree.departments[pk].parent_id
        if parent in tree.departments:
            total[parent] = total.get(parent, 0) + total.get(pk, 0)

    heads = {
        member.pk: member
        for member in Membership.objects.filter(
            company=company,
            status__in=CURRENT,
            pk__in=[tree.departments[pk].head_id for pk in shown if tree.departments[pk].head_id],
        ).select_related("user", "position")
    }
    department_rows = []
    for pk in tree.order:
        if pk not in shown:
            continue
        department = tree.departments[pk]
        head = heads.get(department.head_id)
        department_rows.append(
            {
                "id": pk,
                "name": department.name,
                "parent_id": department.parent_id if department.parent_id in shown else None,
                "depth": tree.depths[pk],
                "head": _ref(head) if head is not None else None,
                "headcount": direct.get(pk, 0),
                "total": total.get(pk, 0),
            }
        )

    by_branch = Counter(row["branch_id"] for row in rows if row["branch_id"])
    branch_rows = [
        {
            "id": branch.pk,
            "name": branch.name,
            "code": branch.code,
            "manager": _ref(branch.manager)
            if branch.manager_id and branch.manager.status in CURRENT
            else None,
            "headcount": by_branch.get(branch.pk, 0),
        }
        for branch in branches
    ]

    owners = (
        Membership.objects.for_company(company)
        .filter(status=Membership.Status.APPROVED, role__is_owner=True)
        .select_related("user", "position")
        .order_by("first_name", "last_name", "pk")
    )
    return {
        "today": today,
        "company": {"id": company.pk, "name": company.name},
        "owners": [_ref(owner) for owner in owners],
        "departments": department_rows,
        "branches": branch_rows,
        "positions": [
            {"id": position.pk, "name": position.name, "order": position.order}
            for position in sorted(positions.values(), key=lambda p: (p.order, p.name, p.pk))
        ],
        "people": rows,
        "vacancies": vacancies,
        "can": {
            "move": viewer.has_perm(Perm.HR_MANAGE),
            "decide": viewer.has_perm(Perm.HR_MANAGE) and viewer.has_perm(Perm.MEMBERS_MANAGE),
            "hiring": viewer.has_perm(Perm.HR_HIRING),
            "structure": departments.may_edit_structure(viewer),
        },
    }


def _person(person: Membership, viewer: Membership, tree, shown_branches: list[int]) -> dict:
    manager = departments.manager_of(person, tree) if tree else None
    reason = why_not(viewer, person)
    # The branch view puts someone under their home branch, or (it is outside the viewer's
    # branches) under the first of their branches the viewer sees.
    branch_id = person.home_branch_id
    if branch_id not in shown_branches:
        theirs = {branch.pk for branch in person.branches.all()}
        branch_id = next((pk for pk in shown_branches if pk in theirs), None)
    return {
        "id": person.pk,
        "name": str(person),
        "photo_url": photo_url(person),
        "position_id": person.position_id,
        "department_id": person.department_id if person.department_id in tree.departments else None,
        "home_branch_id": person.home_branch_id,
        "branch_id": branch_id,
        "manager_id": manager.pk if manager is not None else None,
        "is_owner": departments.is_owner(person),
        "status": person.status,
        "suspended_until": person.suspended_until
        if person.status == Membership.Status.SUSPENDED
        else None,
        "on_leave_until": None,
        "leaving": None,
        "change": None,
        "may_move": reason is None,
        "why_not": reason,
    }


def _statuses(company, rows: list[dict], ids: list[int], today) -> None:
    """On leave today, leaving (asked or agreed), a job change waiting: three queries."""
    from apps.timeoff import queries as timeoff

    by_id = {row["id"]: row for row in rows}
    for member_id, away in timeoff.off_on(company, today, ids).items():
        by_id[member_id]["on_leave_until"] = away["until"]
    for leaving in Termination.objects.filter(
        company=company,
        membership_id__in=ids,
        status__in=(Termination.Status.REQUESTED, Termination.Status.AGREED),
    ).order_by("pk"):
        by_id[leaving.membership_id]["leaving"] = {
            "id": leaving.pk,
            "status": leaving.status,
            "day": leaving.last_day or leaving.wished_last_day,
        }
    for change in JobChange.objects.filter(
        company=company, membership_id__in=ids, status__in=job_changes.OPEN
    ).order_by("effective_on", "pk"):
        row = by_id[change.membership_id]
        if row["change"] is None:
            row["change"] = {
                "id": change.pk,
                "status": change.status,
                "effective_on": change.effective_on,
                "parts": list(change.parts or []),
            }


def _vacancies(company, branch_ids, rows: list[dict], positions: dict) -> list[dict]:
    """Open vacancies in the viewer's branches, each placed in the department where people of
    its position work at its branch (else anywhere, else where its branch's people are)."""
    from apps.hr.hiring import queries as hiring
    from apps.hr.models import Applicant, Vacancy

    found = (
        hiring.vacancies(company, branch_ids=branch_ids)
        .filter(status=Vacancy.Status.OPEN)
        .annotate(
            waiting=Count("applicants", filter=Q(applicants__stage__in=hiring.OPEN_STAGES)),
            fresh=Count("applicants", filter=Q(applicants__stage=Applicant.Stage.NEW)),
        )
        .order_by("title", "pk")
    )
    by_position_branch: dict = defaultdict(Counter)
    by_position: dict = defaultdict(Counter)
    by_branch: dict = defaultdict(Counter)
    for row in rows:
        department = row["department_id"]
        if department is None:
            continue
        if row["position_id"]:
            by_position_branch[(row["position_id"], row["home_branch_id"])][department] += 1
            by_position[row["position_id"]][department] += 1
        by_branch[row["home_branch_id"]][department] += 1

    out = []
    for vacancy in found:
        candidates = (
            by_position_branch.get((vacancy.position_id, vacancy.branch_id)),
            by_position.get(vacancy.position_id),
            by_branch.get(vacancy.branch_id),
        )
        department = next((counter.most_common(1)[0][0] for counter in candidates if counter), None)
        if vacancy.position_id:
            positions.setdefault(vacancy.position_id, vacancy.position)
        out.append(
            {
                "id": vacancy.pk,
                "title": vacancy.title,
                "position_id": vacancy.position_id,
                "branch_id": vacancy.branch_id,
                "department_id": department,
                "applicants": vacancy.waiting,
                "new": vacancy.fresh,
            }
        )
    return out
