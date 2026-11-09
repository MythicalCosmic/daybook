"""Tenant isolation and rights, walked over every API route: ids from a client never cross
companies, and a write needs the right to make it.

"Theirs" is the whole demo (Demo Dorixona and Demo Distribyutor, every module), seeded after
every database sequence was moved to THEIRS: the first rows of every table are theirs and carry
the same ids, whatever model a route looks up. "Ours" is a company made before that, holding
only its defaults; its owner (every permission) is the client, with a dashboard token for
`owner/` routes and a mini app token for the others. Then, for every route and every method it
answers:

1. our company id with their ids answers exactly like our company id with ids that exist
   nowhere: a foreign id is indistinguishable from a missing one;
2. their company id answers 404: an owner of ours learns nothing about theirs;
3. no answer about our company carries a name only they have (people, branches, the company).

List routes get every id filter the API reads (`?branch=`, `?member=`, …) set to their ids.

Then, inside their company: someone whose role holds only dashboard access writes nothing
through the owner API, and a new employee changes none of the demo's rows through the mini app
(`writes_without_rights`, `others_rows_untouched`), their own things apart.
"""

import json
import re
from dataclasses import dataclass
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection, transaction
from django.urls import URLResolver, get_resolver
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.companies.models import Branch, Company, Feature
from apps.core.management.commands import seed_demo
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import MembershipFactory
from apps.signin.tokens import OwnerAccessToken

pytestmark = pytest.mark.django_db

THEIRS = 900_000_000
MISSING = 1_900_000_000
# Their first rows: a route whose lookup wants a certain kind of row (an open task, a card)
# gets a few chances to meet one.
TRIES = 3
# Routes outside any company: sign-in, the caller's own profile and sessions, new companies and
# signed files. Each has its own tests (accounts, signin, companies, core.files).
OUTSIDE = re.compile(
    r"^api/v1/(auth/|me/|files/|devices/|owner/(auth/|me/|permissions/|ai/|companies/(new/)?$))"
)
# Every id filter a list route reads from the query string.
ID_FILTERS = (
    "account",
    "assignee",
    "assignee_id",
    "branch",
    "branch_id",
    "category",
    "department",
    "employee",
    "given_by",
    "group",
    "home_branch_id",
    "label",
    "link_id",
    "member",
    "member_id",
    "person",
    "position",
    "position_id",
    "project",
    "receiver_id",
    "record_id",
    "register_id",
    "role",
    "role_id",
    "routine",
    "shift_id",
    "space",
    "target_id",
)
# Path parts that aren't row ids.
WORDS = {"verb": "accept", "key": "approve"}
# Writes that check their body before looking the row up get a valid body, or a foreign id
# would never reach the lookup. Keys are route endings.
SOON = "2031-03-01T10:00:00Z"
BODIES = {
    "tasks/(?P<pk>[^/.]+)/blocker/$": {"reason_code": "other", "note": "walk"},
    "tasks/(?P<pk>[^/.]+)/blocker/resolve/$": {"action": "cancel"},
    "tasks/(?P<pk>[^/.]+)/extension/$": {"until": SOON, "note": "walk"},
    "tasks/(?P<pk>[^/.]+)/extension/decide/$": {"approve": True},
    "tasks/(?P<pk>[^/.]+)/return/$": {"reason": "walk"},
    "tasks/(?P<pk>[^/.]+)/comment/$": {"text": "walk"},
    "tasks/(?P<pk>[^/.]+)/move/$": {"to": "done"},
    r"people/(?P<pk>\d+)/offboard/$": {"reason": "resignation"},
    r"people/(?P<pk>\d+)/suspend/$": {"reason": "walk"},
    r"announcements/(?P<pk>\d+)/pin/$": {"pinned_until": SOON},
    r"knowledge/pages/(?P<pk>\d+)/move/$": {"index": 0},
    "calendar/events/<int:pk>/respond/": {"response": "going"},
    r"calendar/events/(?P<pk>\d+)/respond/$": {"response": "going"},
    r"sales/shifts/(?P<pk>\d+)/dispute/$": {"reason": "walk"},
    r"sales/shifts/(?P<pk>\d+)/force-close/$": {"reason": "walk"},
    r"sales/shifts/(?P<pk>\d+)/payments/$": {"payments": [], "reason": "walk"},
    r"sales/cash-movements/(?P<pk>\d+)/void/$": {"reason": "walk"},
    r"sales/entries/(?P<pk>\d+)/void/$": {"reason": "walk"},
    r"attendance/records/(?P<pk>\d+)/excuse/$": {"reason": "walk"},
    r"attendance/records/(?P<pk>\d+)/overtime/$": {"approve": True},
    r"attendance/swaps/(?P<pk>\d+)/reject/$": {"reason": "walk"},
    r"attendance/corrections/(?P<pk>\d+)/decide/$": {"approve": True},
}
# What anyone with the dashboard writes for themselves: their saved views, inbox and
# notification settings, their own timer, "I've read it" on a page they're asked to read.
OWN_THINGS = (
    "saved-views/",
    "inbox/",
    "notification-preferences/",
    "projects/timers/",
    "/ack/",
)
PARAM = re.compile(r"<(?:\w+:)?(?P<name>\w+)>|\(\?P<(?P<regex_name>\w+)>[^)]*\)")
# Timestamps differ between two calls a moment apart.
MOMENT = re.compile(r"\d{4}-\d\d-\d\dT[\d:.]+(Z|[+-]\d\d:\d\d)?")


@dataclass(frozen=True)
class Route:
    route: str
    view: str
    methods: tuple[str, ...]

    @property
    def params(self) -> list[str]:
        return [m.group("name") or m.group("regex_name") for m in PARAM.finditer(self.route)]

    @property
    def has_ids(self) -> bool:
        return any(name not in ("company_id", *WORDS) for name in self.params)

    @property
    def owner(self) -> bool:
        return self.route.startswith("api/v1/owner/")

    @property
    def body(self) -> dict:
        return next((body for end, body in BODIES.items() if self.route.endswith(end)), {})

    def url(self, company_id: int, row_id: int) -> str:
        def value(match):
            name = match.group("name") or match.group("regex_name")
            if name == "company_id":
                return str(company_id)
            return WORDS.get(name, str(row_id))

        return "/" + PARAM.sub(value, self.route).replace("^", "").replace("$", "")


def routes() -> list[Route]:
    found = []

    def walk(resolver, prefix):
        for pattern in resolver.url_patterns:
            route = prefix + str(pattern.pattern)
            if isinstance(pattern, URLResolver):
                walk(pattern, route)
                continue
            if not route.startswith("api/v1/") or OUTSIDE.match(route.replace("^", "")):
                continue
            callback = pattern.callback
            actions = getattr(callback, "actions", None)
            view = getattr(callback, "cls", None) or callback.view_class
            if actions:
                methods = tuple(actions)
            else:
                methods = tuple(
                    method
                    for method in view.http_method_names
                    if method not in ("head", "options", "trace") and hasattr(view, method)
                )
            found.append(Route(route, f"{view.__module__}.{view.__qualname__}", methods))

    walk(get_resolver(), "")
    return found


def restart_sequences(at: int | None) -> dict[str, tuple[int, bool]]:
    """Move every sequence to `at` (the next row gets it); returns where each one was."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT schemaname || '.' || sequencename, last_value FROM pg_sequences "
            "WHERE schemaname = 'public'"
        )
        before = {name: (last or 1, last is not None) for name, last in cursor.fetchall()}
        for name in before:
            cursor.execute("SELECT setval(%s, %s, false)", [name, at])
    return before


def put_back(sequences: dict[str, tuple[int, bool]]) -> None:
    with connection.cursor() as cursor:
        for name, (value, called) in sequences.items():
            cursor.execute("SELECT setval(%s, %s, %s)", [name, value, called])


def call(client: APIClient, method: str, route: Route, company_id: int, row_id: int):
    url = route.url(company_id, row_id)
    if method == "get":
        return client.get(url, dict.fromkeys(ID_FILTERS, row_id))
    return getattr(client, method)(url, route.body, format="json")


def text(response) -> str:
    if getattr(response, "streaming", False):
        return ""
    return MOMENT.sub("<moment>", response.content.decode(errors="replace"))


def their_names(companies) -> set[str]:
    names = {company.name for company in companies}
    names |= set(Branch.objects.filter(company__in=companies).values_list("name", flat=True))
    for first, last in Membership.objects.filter(company__in=companies).values_list(
        "first_name", "last_name"
    ):
        if first and last:
            names.add(f"{first} {last}")
    # Short words ("Ombor") could be anyone's; a full name or a branch name is theirs.
    return {name for name in names if len(name) >= 8}


@pytest.fixture
def clients(company, member):
    """Our owner's two clients. Every module is on for our company, or a module's routes would
    answer 403 before looking at any id."""
    company.features = list(Feature.values)
    company.save(update_fields=["features"])
    owner = member(company, "Owner", first_name="Ozod", last_name="Bizniki")
    dashboard, mini_app = APIClient(), APIClient()
    dashboard.credentials(HTTP_AUTHORIZATION=f"Bearer {OwnerAccessToken.for_user(owner.user)}")
    mini_app.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(owner.user)}")
    return dashboard, mini_app


@pytest.fixture
def theirs(settings, company, clients):
    """The whole demo, its rows numbered from THEIRS; sequences are put back afterwards (a
    walk that breaks the transaction is rolled back to the savepoint first, so they can be)."""
    settings.DEBUG = True
    sequences = restart_sequences(THEIRS)
    try:
        with transaction.atomic():
            call_command("seed_demo", stdout=StringIO())
            settings.DEBUG = False
            yield list(Company.objects.filter(slug__in=(seed_demo.SLUG, seed_demo.SMALL_SLUG)))
    finally:
        put_back(sequences)


def test_every_route_keeps_companies_apart(company, clients, theirs):
    dashboard, mini_app = clients
    names = their_names(theirs)
    their_company = min(theirs, key=lambda each: each.pk).pk
    problems = []
    walked = 0

    def look(route, method, what, response):
        body = text(response)
        leaked = sorted(name for name in names if name in body)
        if leaked:
            problems.append(f"{method.upper()} {route.route} ({what}) shows {leaked[:3]}")
        return body

    for route in routes():
        client = dashboard if route.owner else mini_app
        # Reads first: a write that wrongly reaches their rows must not hide a read leak.
        for method in sorted(route.methods, key=lambda m: m != "get"):
            walked += 1
            missing = call(client, method, route, company.pk, MISSING)
            missing_body = look(route, method, "missing ids", missing)
            # A write without ids in its path is the same call either way.
            tries = TRIES if route.has_ids else int(method == "get")
            for row_id in range(THEIRS, THEIRS + tries):
                foreign = call(client, method, route, company.pk, row_id)
                foreign_body = look(route, method, f"their id {row_id}", foreign)
                if foreign.status_code != missing.status_code:
                    problems.append(
                        f"{method.upper()} {route.route}: their id {row_id} answers "
                        f"{foreign.status_code}, a missing one {missing.status_code} "
                        f"({foreign_body[:160]})"
                    )
                    break
                if method == "get" and foreign_body != missing_body:
                    problems.append(
                        f"GET {route.route}: their id {row_id} answers differently "
                        f"({foreign_body[:160]} vs {missing_body[:160]})"
                    )
                    break
            other = call(client, method, route, their_company, THEIRS)
            if other.status_code != 404:
                problems.append(
                    f"{method.upper()} {route.route}: their company id answers "
                    f"{other.status_code} ({text(other)[:160]})"
                )

    assert walked > 400
    assert not problems, "\n".join(problems)
    # The same demo, then two more walks (one seed for all: it takes a minute).
    found = writes_without_rights(their_company) + others_rows_untouched(their_company)
    assert not found, "\n".join(found)


def newcomer(company: Company, role: AccessRole) -> Membership:
    """Approved and onboarded a moment ago in the company's first branch: no rows of their own."""
    branch = company.branches.order_by("order", "pk").first()
    person = MembershipFactory(
        company=company,
        role=role,
        status=Membership.Status.APPROVED,
        onboarded_at=timezone.now(),
        home_branch=branch,
    )
    person.branches.add(branch)
    return person


def writes_without_rights(company_id: int) -> list[str]:
    """Inside their own company, someone whose role gives nothing but the dashboard changes
    nothing: every owner write on the demo's first rows answers 400, 403 or 404 for them,
    except their own things (`OWN_THINGS`)."""
    company = Company.objects.get(pk=company_id)
    role = AccessRole.objects.create(
        company=company, name="Only the dashboard (walk)", permissions=[Perm.DASHBOARD_ACCESS]
    )
    client = APIClient()
    token = OwnerAccessToken.for_user(newcomer(company, role).user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return _no_write_goes_through(client, company_id, owner=True, why="dashboard access alone")


def others_rows_untouched(company_id: int) -> list[str]:
    """A new employee (the company's default role) changes none of the demo's rows through the
    mini app: they are all someone else's tasks, shifts, requests and pages."""
    company = Company.objects.get(pk=company_id)
    role = AccessRole.objects.filter(company=company, is_default=True).first()
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(newcomer(company, role).user)}"
    )
    return _no_write_goes_through(client, company_id, owner=False, why="a new employee")


def _no_write_goes_through(client, company_id: int, *, owner: bool, why: str) -> list[str]:
    found = []
    for route in routes():
        if route.owner != owner or any(own in route.route for own in OWN_THINGS):
            continue
        if not owner and not route.has_ids:
            continue  # their own new rows: a check-in, a request, a task for themselves
        for method in route.methods:
            if method in ("get", "head"):
                continue
            for row_id in range(THEIRS, THEIRS + (TRIES if route.has_ids else 1)):
                response = call(client, method, route, company_id, row_id)
                if response.status_code < 300:
                    found.append(
                        f"{method.upper()} {route.route} ({row_id}) answers "
                        f"{response.status_code} to {why}: {text(response)[:160]}"
                    )
                    break
    return found


def test_the_walk_sees_every_api_route():
    """Every company route is walked: a new urls.py is covered without touching this file."""
    walked = {route.route for route in routes()}

    assert len(walked) > 350
    assert any("tasks/(?P<pk>" in route for route in walked)
    assert any("owner/companies/<int:company_id>/^people/(?P<pk>" in route for route in walked)
    assert not [route for route in walked if "company_id" not in route]
    # Sanity of the URL builder on both route syntaxes.
    sample = next(r for r in routes() if r.route.endswith("my-team/<int:member_id>/"))
    assert sample.url(7, 9) == "/api/v1/companies/7/my-team/9/"
    viewset = next(r for r in routes() if r.route.endswith("tasks/(?P<pk>[^/.]+)/start/$"))
    assert viewset.url(7, 9) == "/api/v1/companies/7/tasks/9/start/"
    assert json.dumps(viewset.methods) == '["post"]'
