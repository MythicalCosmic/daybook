import re
from collections import defaultdict
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.announcements.models import Announcement
from apps.attendance import queries as attendance
from apps.attendance.models import AttendanceRecord, WorkShift
from apps.companies.models import Company, Feature
from apps.companies.tests.factories import CompanyFactory
from apps.core import demo_plan
from apps.core.management.commands import seed_demo
from apps.finance.models import Category, MoneyAccount, Transaction
from apps.inbox.models import Notification
from apps.knowledge.models import Page, PageVersion
from apps.members.models import AccessRole, Membership, Position
from apps.projects.models import TimeEntry
from apps.sales.models import CashMovement, CashShift, DailySales
from apps.tasks.models import Task, TaskTemplate
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db

REAL_OWNER = 6_589_960_007
PHARMACY, DISTRIBUTOR = seed_demo.SLUG, seed_demo.SMALL_SLUG
# Names of real companies and brands an older demo used: none may appear in the data.
REAL_NAMES = ("Kapitalbank", "Coca-Cola", "Uzonline", "Artel", "Agromir", "Korzinka")


def seed(**options) -> str:
    out = StringIO()
    call_command("seed_demo", stdout=out, **options)
    return out.getvalue()


def seed_core(**options) -> str:
    """The core demo without any app's demo.py (apps.core has none): what seed_demo itself does
    (reset, owners, rollback) in seconds instead of the full demo's minute."""
    return seed(only="core", **options)


@pytest.fixture
def debug(settings):
    settings.DEBUG = True


@pytest.fixture
def demo_calls(monkeypatch):
    """Records which apps' demo.py hooks and defaults.ensure ran, and for which company."""
    calls = []
    for label in ("sales", "finance"):

        def demo(company, people, now, label=label):
            calls.append(("demo", label, company.slug, sorted(people)))

        def small(company, people, now, label=label):
            calls.append(("small", label, company.slug, sorted(people)))

        def finish(company, people, now, label=label):
            calls.append(("finish", label, company.slug, sorted(people)))

        def ensure(company, label=label):
            calls.append(("ensure", label, company.slug))

        monkeypatch.setattr(f"apps.{label}.demo.seed", demo)
        monkeypatch.setattr(f"apps.{label}.demo.seed_small", small, raising=False)
        monkeypatch.setattr(f"apps.{label}.demo.finish", finish, raising=False)
        monkeypatch.setattr(f"apps.{label}.defaults.ensure", ensure)
    return calls


def demos(calls) -> list[str]:
    return [call[1] for call in calls if call[0] == "demo"]


def made_today(companies):
    """Routines of `companies` made today: a routine made after today's deadline only starts
    tomorrow, so a fresh demo would offer "give today's task now" on it."""
    midnight = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return TaskTemplate.objects.filter(
        company__in=companies, onboarding=False, created_at__gte=midnight
    ).values_list("title", flat=True)


def leave_days(company) -> set[tuple[int, object]]:
    days = set()
    for row in TimeOff.objects.filter(company=company, status=TimeOff.Status.APPROVED):
        day = row.first_day
        while day <= row.last_day:
            days.add((row.membership_id, day))
            day += timedelta(days=1)
    return days


def test_the_whole_demo_tells_one_story(debug):
    output = seed(owner_tg=REAL_OWNER, verbosity=2)

    assert "Demo Dorixona and Demo Distribyutor are ready." in output
    assert "  sales " in output  # -v 2 prints how long each app's demo took
    pharmacy = Company.objects.get(slug=PHARMACY)
    distributor = Company.objects.get(slug=DISTRIBUTOR)
    assert sorted(pharmacy.features) == sorted(Feature.values)
    assert sorted(distributor.features) == sorted(seed_demo.SMALL_FEATURES)
    chilonzor, yunusobod = pharmacy.branches.order_by("order")
    assert (chilonzor.code, yunusobod.code) == ("CHL", "YNS")
    assert yunusobod.opens_at is None  # open around the clock
    assert [b.code for b in distributor.branches.all()] == ["SRG"]

    # The people: Demo Dorixona's fifteen (and the real owner), the distributor's five.
    approved = pharmacy.memberships.filter(status=Membership.Status.APPROVED)
    assert approved.exclude(user__telegram_id=REAL_OWNER).count() == len(demo_plan.PEOPLE)
    assert distributor.memberships.filter(status=Membership.Status.APPROVED).exclude(
        user__telegram_id=REAL_OWNER
    ).count() == len(demo_plan.SMALL_PEOPLE)
    statuses = set(pharmacy.memberships.values_list("status", flat=True))
    assert {"approved", "suspended", "left", "blocked", "pending"} <= statuses
    assert all(m.home_branch_id and m.branches.filter(pk=m.home_branch_id) for m in approved)
    # Uzbek companies: positions and roles carry Uzbek names once every demo has run.
    for company in (pharmacy, distributor):
        for model, names in seed_demo.IN_UZBEK.items():
            assert not model.objects.filter(company=company, name__in=list(names)).exists()
    assert {"Dorixona mudiri", "Provizor", "Farmatsevt", "Omborchi", "Kuryer", "Ofis"} <= set(
        Position.objects.filter(company=pharmacy).values_list("name", flat=True)
    )
    assert {"Ombor mudiri", "Omborchi", "Savdo menejeri", "Haydovchi", "Ofis"} <= set(
        Position.objects.filter(company=distributor).values_list("name", flat=True)
    )
    assert {"Egasi", "Rahbar", "Farmatsevt", "Kassir", "Xodim", "Filial rahbari"} <= set(
        AccessRole.objects.filter(company=pharmacy).values_list("name", flat=True)
    )
    # Two pharmacists share a position and a shift pattern, so their nights can be swapped.
    nigora = approved.get(user__telegram_id=seed_demo.NIGORA)
    dilshod = approved.get(user__first_name="Dilshod")
    assert nigora.position == dilshod.position and nigora.position.name == "Farmatsevt"
    for asker, colleague in ((nigora, dilshod), (dilshod, nigora)):
        coming = WorkShift.objects.working().filter(membership=asker, date__gt=timezone.localdate())
        assert attendance.takeable(colleague, coming.select_related("membership"))
    nights = WorkShift.objects.working().filter(branch=yunusobod, starts_at__hour__gte=14)
    assert nights.exists()  # Yunusobod has night shifts

    # Nobody away works: no shift, check-in, routine, till or project time on a day of approved
    # leave, and nothing before someone joined.
    away = leave_days(pharmacy)
    assert away
    shifts = WorkShift.objects.working().filter(company=pharmacy)
    assert not [s for s in shifts if (s.membership_id, s.date) in away]
    records = AttendanceRecord.objects.filter(company=pharmacy).exclude(status="absent")
    assert not [r for r in records if (r.membership_id, r.date) in away]
    routines = Task.objects.filter(company=pharmacy, kind=Task.Kind.DAILY, for_date__isnull=False)
    assert not [t for t in routines if (t.assignee_id, t.for_date) in away]
    tills = CashShift.objects.filter(company=pharmacy)
    assert not [c for c in tills if (c.cashier_id, c.business_day) in away]
    entries = TimeEntry.objects.filter(company=pharmacy)
    assert not [e for e in entries if (e.membership_id, e.day) in away]
    joined = {m.pk: timezone.localtime(m.decided_at).date() for m in approved if m.decided_at}
    early = [t for t in routines if t.for_date < joined.get(t.assignee_id, t.for_date)]
    assert not early
    # No pile of old routine runs: everything before today was done, in time or late.
    stale = routines.filter(for_date__lt=timezone.localdate())
    open_states = (Task.Status.TODO, Task.Status.IN_PROGRESS, Task.Status.RETURNED)
    assert stale.exists() and not stale.filter(status__in=open_states).exists()
    assert not list(made_today([pharmacy, distributor]))
    # A till is run by someone rostered that day, who checked in before opening it and checked
    # out after closing it.
    rostered = set(shifts.values_list("membership_id", "date"))
    assert all((c.cashier_id, c.business_day) in rostered for c in tills)
    days = {(r.membership_id, r.date): r for r in records}
    for till in tills:
        came = days.get((till.cashier_id, till.business_day))
        assert came is None or came.check_in_at <= till.opened_at, till.number
        went = days.get((till.closed_by_id, till.business_day))
        if till.closed_at and went and went.check_out_at:
            assert went.check_out_at >= till.closed_at, till.number
    # Nobody starts, finishes or checks a task (a card, a routine, a job given) while away.
    for task in Task.objects.filter(company=pharmacy):
        for moment, who in (
            (task.started_at, task.assignee_id),
            (task.completed_at, task.assignee_id),
            (task.confirmed_at, task.confirmed_by_id),
        ):
            if moment is not None:
                assert (who, timezone.localtime(moment).date()) not in away, task.title
    # ...and finishes it while there: in one of their shifts or, without one, in the branch's
    # opening hours (Yunusobod is open around the clock).
    spans = defaultdict(list)
    for shift in shifts:
        spans[shift.membership_id].append(
            (shift.starts_at - timedelta(minutes=30), shift.ends_at + timedelta(minutes=30))
        )
    finished = Task.objects.filter(company=pharmacy, completed_at__isnull=False)
    for task in finished.select_related("branch"):
        if any(start <= task.completed_at <= end for start, end in spans[task.assignee_id]):
            continue
        if task.branch.opens_at is not None and task.branch.closes_at is not None:
            clock = timezone.localtime(task.completed_at).time()
            assert task.branch.opens_at <= clock <= task.branch.closes_at, (task.title, clock)
    now = timezone.now() + timedelta(minutes=1)
    assert not Task.objects.filter(company=pharmacy, created_at__gt=now).exists()
    assert not AttendanceRecord.objects.filter(company=pharmacy, check_in_at__gt=now).exists()

    # Money: the days the tills book aren't booked again by the ledger's daily sales.
    rows = Transaction.objects.filter(company=pharmacy, status="posted")
    ledger_days = set(
        rows.filter(source_type="finance.demo", kind="income").values_list("occurred_on", flat=True)
    )
    tilled = rows.filter(source_type="sales.cashshift")
    till_days = set(tilled.values_list("occurred_on", flat=True))
    assert ledger_days and till_days and not ledger_days & till_days
    # The ledger's days are the tills' imported weeks, with exactly its totals and its cash
    # taken to the safe; so the sales pages compare this month with the one before.
    daily = rows.filter(source_type="finance.demo", source_key__startswith="s:")
    booked = {
        (row["source_id"], row["occurred_on"]): row["total"]
        for row in daily.values("source_id", "occurred_on").annotate(total=Sum("amount"))
    }
    imported = CashShift.objects.filter(company=pharmacy, source=CashShift.Source.IMPORT)
    sold = {
        (row["branch_id"], row["business_day"]): row["total"]
        for row in imported.values("branch_id", "business_day").annotate(
            total=Sum("payments__sales")
        )
    }
    assert booked and sold == booked
    assert not imported.exclude(status=CashShift.Status.VERIFIED).exists()
    moved = CashMovement.objects.filter(shift__in=imported)
    assert moved.exists() and not moved.filter(transfer__isnull=True).exists()
    month = timezone.localdate().replace(day=1)
    before = (month - timedelta(days=1)).replace(day=1)
    assert DailySales.objects.filter(company=pharmacy, day=before).exists()
    for account in MoneyAccount.objects.filter(company__in=(pharmacy, distributor)):
        posted = Transaction.objects.filter(account=account, status="posted").aggregate(
            total=Sum("amount")
        )["total"]
        assert account.balance == (posted or 0), account.name
        assert account.balance >= 0 or account.allow_negative, account.name
    # One cash account per pharmacy (its till's), and no empty company-level cash desk.
    cash = MoneyAccount.objects.filter(company=pharmacy, kind=MoneyAccount.Kind.CASH)
    assert sorted(cash.values_list("branch__code", flat=True)) == ["CHL", "YNS"]

    # Only invented names, and messages in each reader's language.
    texts = " ".join(
        [
            *MoneyAccount.objects.values_list("name", flat=True),
            *Transaction.objects.values_list("description", flat=True),
            *Task.objects.values_list("title", flat=True),
        ]
    )
    assert not [name for name in REAL_NAMES if name in texts]
    # A number keeps its % or °C on its line (a no-break space between them): Telegram's
    # preview of the prices announcement broke "20 %" before the %. (Page titles are left out:
    # the knowledge service collapses their spaces.)
    words = [
        texts,
        *Announcement.objects.values_list("text", flat=True),
        *Page.objects.values_list("body", flat=True),
        *Category.objects.values_list("name", flat=True),
        *Task.objects.values_list("description", flat=True),
    ]
    assert not [text for text in words if re.search(r"\d [%°]", text)]
    # What the services store in words comes out in the company's language (Uzbek), as when
    # its people use the apps: a till's cash difference, a knowledge page's first version.
    shortages = Transaction.objects.filter(company=pharmacy, source_type="sales.cashshift")
    assert shortages.filter(description__endswith=": kassa farqi").exists()
    assert not shortages.filter(description__contains="cash difference").exists()
    assert PageVersion.objects.filter(page__company=pharmacy, note="Birinchi versiya").exists()
    assert not PageVersion.objects.filter(page__company=pharmacy, note="First version").exists()
    uzbek_readers = Notification.objects.filter(recipient__user__language="uz")
    assert uzbek_readers.exists()
    assert not uzbek_readers.filter(title__startswith="Cash difference").exists()
    assert not uzbek_readers.filter(title__contains="You're invited").exists()

    # Everything the demo made can be removed again.
    seed_core(reset=True)
    assert not Transaction.objects.filter(company__slug=PHARMACY).exists()


def test_the_demo_stays_out_of_production():
    with pytest.raises(CommandError):
        seed()


def test_an_existing_demo_needs_reset(debug):
    seed_core()
    with pytest.raises(CommandError, match="--reset"):
        seed_core()


def test_reset_removes_the_food_demo_this_one_replaced(debug):
    for slug in demo_plan.OLD_SLUGS:
        CompanyFactory(slug=slug)

    with pytest.raises(CommandError, match="--reset"):
        seed_core()
    seed_core(reset=True)

    assert not Company.objects.filter(slug__in=demo_plan.OLD_SLUGS).exists()
    assert set(Company.objects.values_list("slug", flat=True)) == {PHARMACY, DISTRIBUTOR}


def test_the_core_demo_alone_gives_the_bot_work(debug):
    seed_core()

    pharmacy = Company.objects.get(slug=PHARMACY)
    worker = pharmacy.memberships.get(user__telegram_id=seed_demo.WORKER)
    assert worker.position.name == "Farmatsevt" and worker.home_branch.code == "CHL"
    tasks = Task.objects.for_company(pharmacy).select_related("assignee")
    assert tasks.filter(assignee=worker, for_date=timezone.localdate()).exists()
    # Every task belongs to its assignee's home branch, as the create paths do it.
    assert all(task.branch_id == task.assignee.home_branch_id for task in tasks)
    # The demo's people read Uzbek, four of them Russian.
    languages = dict(
        User.objects.filter(telegram_id__in=[seed_demo.OWNER, seed_demo.MADINA]).values_list(
            "telegram_id", "language"
        )
    )
    assert languages == {seed_demo.OWNER: "uz", seed_demo.MADINA: "ru"}


def test_the_distributor_is_a_second_smaller_company_with_the_same_owner(debug):
    seed_core()  # the apps' demos fill it through seed_small

    distributor = Company.objects.get(slug=DISTRIBUTOR)
    assert distributor.memberships.filter(status=Membership.Status.APPROVED).count() == 5
    [branch] = distributor.branches.all()
    assert branch.manager.user.telegram_id == seed_demo.WAREHOUSE_HEAD
    assert branch.manager.role.name == "Rahbar" and branch.manager.position.name == "Ombor mudiri"
    owner = User.objects.get(telegram_id=seed_demo.OWNER)
    owned = Membership.objects.filter(user=owner, role__is_owner=True, status="approved")
    assert sorted(owned.values_list("company__slug", flat=True)) == sorted([PHARMACY, DISTRIBUTOR])
    assert Task.objects.for_company(distributor).filter(branch=branch).count() > 14
    # No tasks demo fills the distributor: its routines get today's runs from the core demo.
    story = demo_plan.Plan(distributor, {}, timezone.now())
    if story.works("worker", story.today):
        today = Task.objects.for_company(distributor).filter(for_date=story.today)
        assert today.filter(template__title="Ombor harorati va namligini yozish").count() == 1
    # The core demo's own routines (both companies') have run for a while.
    assert not list(made_today(Company.objects.filter(slug__in=(PHARMACY, DISTRIBUTOR))))


def test_each_company_works_the_days_its_branches_open(debug):
    seed_core()

    # The time-off calendar shades, and Settings lists, the company's working days: both
    # pharmacies open every day, the distributor's warehouse Monday to Saturday.
    for slug, days in ((PHARMACY, [0, 1, 2, 3, 4, 5, 6]), (DISTRIBUTOR, [0, 1, 2, 3, 4, 5])):
        company = Company.objects.get(slug=slug)
        assert sorted(company.workdays) == days, slug
        opens = {day for branch in company.branches.all() for day in branch.open_weekdays}
        assert sorted(opens) == days, slug


def test_owner_tg_makes_a_real_account_owner_of_both_companies(debug):
    seed_core(owner_tg=REAL_OWNER)

    user = User.objects.get(telegram_id=REAL_OWNER)
    memberships = Membership.objects.filter(user=user).select_related("company", "role")
    assert sorted(m.company.slug for m in memberships) == sorted([PHARMACY, DISTRIBUTOR])
    for membership in memberships:
        assert membership.status == Membership.Status.APPROVED
        assert membership.role.is_owner
        assert membership.is_onboarded
        assert membership.home_branch is not None
        assert membership.branches.count() == membership.company.branches.count()

    # A rebuild keeps the real account (only the demo people go) and makes it owner again.
    user.first_name = "Real"
    user.save()
    seed_core(reset=True, owner_tg=REAL_OWNER)
    assert User.objects.get(telegram_id=REAL_OWNER).first_name == "Real"
    assert Membership.objects.filter(user=user).count() == 2

    # A rebuild without it removes the memberships but still not the account.
    seed_core(reset=True)
    assert User.objects.filter(telegram_id=REAL_OWNER).exists()
    assert not Membership.objects.filter(user=user).exists()


def test_owner_tg_on_an_existing_demo_only_adds_the_owner(debug):
    seed_core()
    pharmacy = Company.objects.get(slug=PHARMACY)
    tasks = Task.objects.for_company(pharmacy).count()

    output = seed_core(owner_tg=REAL_OWNER)
    seed_core(owner_tg=REAL_OWNER)  # twice is fine

    assert "Owner of Demo Distribyutor, Demo Dorixona" in output
    assert Company.objects.get(slug=PHARMACY).pk == pharmacy.pk
    assert Task.objects.for_company(pharmacy).count() == tasks
    assert Membership.objects.filter(user__telegram_id=REAL_OWNER).count() == 2


def test_owner_tg_cant_be_one_of_the_demo_people(debug):
    with pytest.raises(CommandError, match="demo people"):
        seed(owner_tg=seed_demo.WORKER)


def test_owner_tg_may_be_the_demo_owner_who_owns_both_already(debug):
    """`make demo OWNER_TG=1001` works: Dilnoza is the demo's owner of both companies."""
    output = seed_core(owner_tg=seed_demo.OWNER)

    assert "Demo Dorixona and Demo Distribyutor are ready." in output
    owned = Membership.objects.filter(user__telegram_id=seed_demo.OWNER, role__is_owner=True)
    assert sorted(owned.values_list("company__slug", flat=True)) == sorted([PHARMACY, DISTRIBUTOR])
    pharmacy_owner = owned.get(company__slug=PHARMACY)
    assert seed_core(owner_tg=seed_demo.OWNER) == (
        "1001 is the demo owner: an Owner of both companies.\n"
    )
    assert owned.get(company__slug=PHARMACY).onboarded_at == pharmacy_owner.onboarded_at


def test_module_demos_and_defaults_run(debug, demo_calls):
    seed(owner_tg=REAL_OWNER, only="sales,finance")

    people = ["jasur", "madina", "manager", "nigora", "owner", "worker"]
    small = ["cashier", "manager", "owner", "worker"]
    assert ("demo", "sales", PHARMACY, people) in demo_calls
    assert ("demo", "finance", PHARMACY, people) in demo_calls
    assert ("small", "finance", DISTRIBUTOR, small) in demo_calls
    # `seed` fills the pharmacy, `seed_small` the distributor; defaults are made for both
    # companies, before the demos.
    assert {call[2] for call in demo_calls if call[0] == "demo"} == {PHARMACY}
    assert {call[2] for call in demo_calls if call[0] == "small"} == {DISTRIBUTOR}
    ensured = [call for call in demo_calls if call[0] == "ensure"]
    assert {(call[1], call[2]) for call in ensured} >= {
        ("sales", PHARMACY),
        ("sales", DISTRIBUTOR),
        ("finance", PHARMACY),
        ("finance", DISTRIBUTOR),
    }
    first_demo = next(i for i, call in enumerate(demo_calls) if call[0] in ("demo", "small"))
    assert all(demo_calls.index(call) < first_demo for call in ensured)
    # Every demo's finish runs after every demo's seed, once per company it filled.
    finished = [call for call in demo_calls if call[0] == "finish"]
    assert {(call[1], call[2]) for call in finished} == {
        ("sales", PHARMACY),
        ("finance", PHARMACY),
        ("sales", DISTRIBUTOR),
        ("finance", DISTRIBUTOR),
    }
    last_seed = max(i for i, call in enumerate(demo_calls) if call[0] in ("demo", "small"))
    assert all(demo_calls.index(call) > last_seed for call in finished)


def test_module_demos_never_see_the_real_owner(debug, monkeypatch):
    seen = []

    def demo(company, people, now):
        seen.append(Membership.objects.filter(user__telegram_id=REAL_OWNER).count())

    monkeypatch.setattr("apps.sales.demo.seed", demo)
    seed(owner_tg=REAL_OWNER, only="sales")

    assert seen == [0]
    assert Membership.objects.filter(user__telegram_id=REAL_OWNER).count() == 2


def test_only_runs_the_listed_apps_demos(debug, demo_calls):
    output = seed(only="sales")

    assert demos(demo_calls) == ["sales"]
    assert {call[1] for call in demo_calls if call[0] == "finish"} == {"sales"}
    assert "Module demo data: sales." in output
    # Defaults are not narrowed: a module's demo may rely on another module's rows.
    assert {call[1] for call in demo_calls if call[0] == "ensure"} == {"sales", "finance"}


def test_demo_apps_from_the_environment(debug, demo_calls, monkeypatch):
    monkeypatch.setenv("DEMO_APPS", "finance, sales")
    seed()
    assert sorted(demos(demo_calls)) == ["finance", "sales"]

    demo_calls.clear()
    seed(reset=True, only="finance")  # --only wins over the environment
    assert demos(demo_calls) == ["finance"]


def test_unknown_demo_apps_are_refused(debug, monkeypatch):
    with pytest.raises(CommandError, match="nope"):
        seed(only="sales,nope")
    monkeypatch.setenv("DEMO_APPS", "nope")
    with pytest.raises(CommandError, match="nope"):
        seed()
    assert not Company.objects.filter(slug=PHARMACY).exists()


def test_a_failing_rebuild_keeps_the_previous_demo(debug, monkeypatch):
    seed_core()
    pharmacy = Company.objects.get(slug=PHARMACY)

    def broken(company, people, now):
        raise RuntimeError("half-finished demo.py")

    monkeypatch.setattr("apps.sales.demo.seed", broken)
    with pytest.raises(RuntimeError):
        seed(reset=True, only="sales")

    assert Company.objects.get(slug=PHARMACY).pk == pharmacy.pk
    assert Company.objects.filter(slug=DISTRIBUTOR).exists()
    assert User.objects.filter(telegram_id=seed_demo.WORKER).exists()


def test_owner_tg_finds_the_owner_role_even_renamed(debug):
    seed_core()
    AccessRole.objects.filter(company__slug=PHARMACY, is_owner=True).update(name="Boss")

    seed_core(owner_tg=REAL_OWNER)

    membership = Membership.objects.get(user__telegram_id=REAL_OWNER, company__slug=PHARMACY)
    assert membership.role.name == "Boss"
    assert membership.role.is_owner


@pytest.mark.parametrize("telegram_id", [0, -1_001_555])
def test_owner_tg_must_be_a_user_id(debug, telegram_id):
    with pytest.raises(CommandError, match="Telegram user id"):
        seed(owner_tg=telegram_id)
    assert not Company.objects.filter(slug=PHARMACY).exists()


def test_the_head_of_chilonzor_sees_and_runs_chilonzor_only(debug):
    from apps.members.scope import branch_ids
    from apps.tasks.models import OnFinish, TasksSettings

    seed_core()

    pharmacy = Company.objects.get(slug=PHARMACY)
    head = pharmacy.memberships.get(user__telegram_id=seed_demo.MANAGER)
    chilonzor = pharmacy.branches.get(code="CHL")
    assert branch_ids(head) == [chilonzor.pk]  # audit X-12: no longer every branch
    assert head.role.name in ("Filial rahbari", "Branch manager") and not head.role.is_owner
    assert head.has_perm("tasks.templates") and head.has_perm("tasks.confirm")
    assert chilonzor.manager == head
    # Both demo companies accept finished work automatically, like every new company.
    rules = TasksSettings.objects.filter(company__slug__in=(PHARMACY, DISTRIBUTOR))
    assert sorted(rules.values_list("on_finish", flat=True)) == [OnFinish.AUTO] * 2
