"""Demo companies for trying the apps and for screenshots (development only).

- **Demo Shop**: two branches, six people, tasks, time off and every module switched on. Each
  app adds its own rows through `apps/<app>/demo.py: seed(company, people, now)`.
- **Demo Café**: a smaller second company with the same owner and a few modules, so the
  company switcher and the portfolio have something to show.

`--owner-tg <id>` makes that Telegram account an Owner of both, so a real person can sign in to
the dashboard and both bots against the demo. `--only sales,finance` (or `DEMO_APPS`) runs only
those apps' `demo.py`; the core demo always runs.
"""

import importlib
import importlib.util
import os
from datetime import time, timedelta
from decimal import Decimal

from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.accounts.models import User
from apps.companies.models import Branch, Company, Feature, TenantModel
from apps.companies.services import create_company
from apps.core.management.commands.ensure_company_defaults import ensure_company_defaults
from apps.members.models import AccessRole, Membership, Position
from apps.reminders.models import ReminderLog
from apps.tasks.models import Activity, ChecklistItem, Proof, Task, TaskComment, TaskTemplate
from apps.timeoff.models import Holiday, TimeOff

SLUG = "demo-shop"
CAFE_SLUG = "demo-cafe"
POSITIONS = ["Sales floor", "Cashier", "Stock & warehouse", "Shift lead", "Delivery", "Office"]
CAFE_POSITIONS = ["Barista", "Kitchen", "Hall", "Office"]

# The shop's branches. Creating a company makes its first branch; the demo renames it.
BRANCHES = [
    {
        "name": "Chilonzor",
        "code": "CHL",
        "address": "Bunyodkor 12, Chilonzor, Tashkent",
        "phone": "+998712000101",
        "latitude": Decimal("41.285680"),
        "longitude": Decimal("69.203430"),
        "opens_at": time(9, 0),
        "closes_at": time(21, 0),
        "cash_limit": Decimal("20000000.00"),
        "order": 0,
    },
    {
        "name": "Yunusobod",
        "code": "YNS",
        "address": "Amir Temur 107, Yunusobod, Tashkent",
        "phone": "+998712000202",
        "latitude": Decimal("41.364250"),
        "longitude": Decimal("69.287950"),
        "opens_at": time(10, 0),
        "closes_at": time(22, 0),
        "cash_limit": Decimal("15000000.00"),
        "order": 1,
    },
]
CAFE_BRANCH = {
    "name": "Mirobod",
    "code": "MRB",
    "address": "Shahrisabz 5, Mirobod, Tashkent",
    "phone": "+998712000303",
    "latitude": Decimal("41.296720"),
    "longitude": Decimal("69.279140"),
    "opens_at": time(8, 0),
    "closes_at": time(23, 0),
    "order": 0,
}
# The café runs fewer modules, so switching companies changes the navigation too.
CAFE_FEATURES = [Feature.FINANCE, Feature.SALES, Feature.ATTENDANCE, Feature.PAYROLL]

# Telegram ids of the demo people. Sign in as one of them with dev init data.
OWNER, MANAGER, WORKER, COLLEAGUE = 1001, 1002, 4242, 1004
STOCKER, COURIER = 1005, 1006
APPLICANT, WAITING, OUTSIDER = 5001, 5002, 5003
CAFE_MANAGER, BARISTA, COOK = 2001, 2002, 2003
EVERYONE = (
    OWNER,
    MANAGER,
    WORKER,
    COLLEAGUE,
    STOCKER,
    COURIER,
    APPLICANT,
    WAITING,
    OUTSIDER,
    CAFE_MANAGER,
    BARISTA,
    COOK,
)


class Command(BaseCommand):
    help = "Create the Demo Shop and Demo Café companies with people and tasks (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Replace an existing demo.")
        parser.add_argument("--force", action="store_true", help="Run even when DEBUG is off.")
        parser.add_argument(
            "--only",
            default=None,
            metavar="APPS",
            help=(
                "Run only these apps' demo.py, e.g. sales,finance (default: DEMO_APPS, else "
                "every app). The core demo always runs."
            ),
        )
        parser.add_argument(
            "--owner-tg",
            type=int,
            default=None,
            metavar="TELEGRAM_ID",
            help=(
                "Make this Telegram account an Owner of both demo companies. With an existing "
                "demo and no --reset, only adds the owner."
            ),
        )

    def handle(self, *args, reset=False, force=False, only=None, owner_tg=None, **options):
        if not settings.DEBUG and not force:
            raise CommandError("Refusing to seed demo data with DEBUG off (use --force).")
        demo_apps = self._demo_apps(os.environ.get("DEMO_APPS", "") if only is None else only)
        if owner_tg is not None and owner_tg in EVERYONE:
            raise CommandError(f"{owner_tg} is one of the demo people; pick another account.")

        if Company.objects.filter(slug__in=(SLUG, CAFE_SLUG)).exists():
            if not reset:
                if owner_tg is None:
                    raise CommandError(
                        "The demo already exists. Use --reset to rebuild it "
                        "(or --owner-tg to add an owner to it)."
                    )
                with transaction.atomic():
                    names = self._add_owner(owner_tg, timezone.now())
                self.stdout.write(
                    self.style.SUCCESS(f"{owner_tg} is now an Owner of {', '.join(names)}.")
                )
                return
            self._remove()

        with transaction.atomic():
            seeded = self._build(demo_apps, owner_tg)
        self.stdout.write(self.style.SUCCESS("Demo Shop and Demo Café are ready."))
        self.stdout.write(
            f"Telegram ids: worker {WORKER}, manager {MANAGER}, owner {OWNER} (both companies), "
            f"applicant {APPLICANT}, waiting {WAITING}, outsider {OUTSIDER}; "
            f"café manager {CAFE_MANAGER}, barista {BARISTA}, cook {COOK}."
        )
        if owner_tg is not None:
            self.stdout.write(f"{owner_tg} is an Owner of both companies.")
        self.stdout.write(f"Module demo data: {', '.join(seeded) or 'none'}.")

    def _demo_apps(self, value: str) -> set[str] | None:
        """The app labels whose demo.py runs; None means every app."""
        wanted = {label.strip() for label in value.split(",") if label.strip()}
        if not wanted:
            return None
        known = {c.label for c in django_apps.get_app_configs() if c.name.startswith("apps.")}
        if unknown := wanted - known:
            raise CommandError(f"Unknown apps in --only/DEMO_APPS: {', '.join(sorted(unknown))}.")
        return wanted

    # Removing ---------------------------------------------------------------------------------

    def _remove(self):
        with transaction.atomic():
            for company in Company.objects.filter(slug__in=(SLUG, CAFE_SLUG)):
                self._remove_company(company)
            # Only the demo people: an --owner-tg account is a real person and stays.
            User.objects.filter(telegram_id__in=EVERYONE).delete()

    def _remove_company(self, company: Company):
        # Every per-company model, in whatever order their protected links allow.
        remaining = [m for m in django_apps.get_models() if issubclass(m, TenantModel)]
        while remaining:
            blocked = []
            for model in remaining:
                try:
                    with transaction.atomic():
                        model.objects.filter(company=company).delete()
                except ProtectedError:
                    blocked.append(model)
            if len(blocked) == len(remaining):
                raise CommandError(f"Can't remove the demo: {blocked} keep pointing at it.")
            remaining = blocked
        company.delete()

    # Building ---------------------------------------------------------------------------------

    def _build(self, demo_apps: set[str] | None, owner_tg: int | None) -> list[str]:
        now = timezone.now()
        shop, people = self._build_shop(now)
        cafe = self._build_cafe(now, owner=people["owner"].user)

        shop.features = list(Feature.values)
        cafe.features = [str(feature) for feature in CAFE_FEATURES]
        for company in (shop, cafe):
            company.save(update_fields=["features", "updated_at"])
            ensure_company_defaults(company)

        seeded = []
        for config in django_apps.get_app_configs():
            if not config.name.startswith("apps."):
                continue
            if demo_apps is not None and config.label not in demo_apps:
                continue
            name = f"{config.name}.demo"
            if importlib.util.find_spec(name) is None:
                continue
            importlib.import_module(name).seed(shop, people, now)
            seeded.append(config.label)

        # Last, so the module demos never treat a real person as one of the staff.
        if owner_tg is not None:
            self._add_owner(owner_tg, now)
        return seeded

    def _add_owner(self, telegram_id: int, now) -> list[str]:
        """Make `telegram_id` an approved Owner of every demo company that exists."""
        user = User.objects.filter(telegram_id=telegram_id).first()
        if user is None:
            # Their name and language arrive when they first open one of the bots.
            user = User(username=f"tg{telegram_id}", telegram_id=telegram_id)
            user.set_unusable_password()
            user.save()
        names = []
        for company in Company.objects.filter(slug__in=(SLUG, CAFE_SLUG)).order_by("name"):
            branches = list(company.branches.order_by("order", "pk"))
            membership, _ = Membership.objects.update_or_create(
                company=company,
                user=user,
                defaults={
                    "status": Membership.Status.APPROVED,
                    "role": AccessRole.objects.get(company=company, is_owner=True, name="Owner"),
                    "first_name": user.first_name or "Owner",
                    "last_name": user.last_name,
                    "onboarded_at": now,
                    "decided_at": now,
                    "home_branch": branches[0] if branches else None,
                },
            )
            membership.branches.set(branches)
            names.append(company.name)
        return names

    def _branches(self, company: Company, rows: list[dict]) -> list[Branch]:
        """One branch per row. The first reuses the branch made with the company, if any."""
        made_with_company = company.branches.order_by("pk").first()
        branches = []
        for index, row in enumerate(rows):
            branch = made_with_company if index == 0 and made_with_company else Branch()
            branch.company = company
            for field, value in row.items():
                setattr(branch, field, value)
            branch.save()
            branches.append(branch)
        return branches

    def _user(self, telegram_id, first, last, phone="") -> User:
        user = User(
            username=f"tg{telegram_id}",
            telegram_id=telegram_id,
            first_name=first,
            last_name=last,
            phone=phone,
            language="en",
        )
        user.set_unusable_password()
        user.save()
        return user

    def _build_shop(self, now) -> tuple[Company, dict[str, Membership]]:
        company = create_company(name="Demo Shop", slug=SLUG, timezone="Asia/Tashkent")
        chilonzor, yunusobod = self._branches(company, BRANCHES)
        positions = {
            name: Position.objects.create(company=company, name=name, order=index)
            for index, name in enumerate(POSITIONS)
        }
        roles = {role.name: role for role in AccessRole.objects.filter(company=company)}

        def person(telegram_id, first, last, *, role=None, position=None, phone="", **membership):
            user = self._user(telegram_id, first, last, phone)
            if membership.get("status") is None and role is None:
                return user
            branches = membership.pop("branches", ())
            created = Membership.objects.create(
                company=company,
                user=user,
                first_name=first,
                last_name=last,
                role=roles.get(role) if role else None,
                position=positions.get(position) if position else None,
                home_branch=branches[0] if branches else None,
                **membership,
            )
            created.branches.set(branches)
            return created

        registered = {
            "status": Membership.Status.APPROVED,
            "onboarded_at": now - timedelta(days=60),
        }
        everywhere = (chilonzor, yunusobod)
        owner = person(
            OWNER,
            "Dilnoza",
            "Karimova",
            role="Owner",
            position="Office",
            phone="+998901110001",
            branches=everywhere,
            **registered,
        )
        manager = person(
            MANAGER,
            "Bekzod",
            "Mirzayev",
            role="Manager",
            position="Shift lead",
            phone="+998901110002",
            branches=everywhere,
            **registered,
        )
        me = person(
            WORKER,
            "Alisher",
            "Valiyev",
            role="Employee",
            position="Sales floor",
            phone="+998901234567",
            branches=(chilonzor,),
            **registered,
        )
        madina = person(
            COLLEAGUE,
            "Madina",
            "Saidova",
            role="Cashier",
            position="Cashier",
            phone="+998901110004",
            branches=(chilonzor,),
            **registered,
        )
        jasur = person(
            STOCKER,
            "Jasur",
            "Tursunov",
            role="Employee",
            position="Stock & warehouse",
            phone="+998901110005",
            branches=(yunusobod,),
            **registered,
        )
        nigora = person(
            COURIER,
            "Nigora",
            "Azimova",
            role="Employee",
            position="Delivery",
            phone="+998901110006",
            branches=(yunusobod,),
            **registered,
        )
        person(APPLICANT, "Javohir", "Rasulov", status=Membership.Status.PENDING)
        person(
            WAITING,
            "Sevara",
            "Tursunova",
            position="Cashier",
            phone="+998935550202",
            status=Membership.Status.PENDING,
            onboarded_at=now - timedelta(minutes=3),
        )
        person(OUTSIDER, "Outside", "Person")
        chilonzor.manager = manager
        chilonzor.save(update_fields=["manager", "updated_at"])

        def task(title, *, kind, due, status=Task.Status.TODO, by=None, **fields):
            return Task.objects.create(
                company=company,
                kind=kind,
                title=title,
                assignee=me,
                branch=me.home_branch,
                created_by=by or me,
                due_at=due,
                status=status,
                **fields,
            )

        def checklist(item_task, *items):
            for order, (text, done) in enumerate(items):
                ChecklistItem.objects.create(task=item_task, text=text, is_done=done, order=order)

        every_day = TaskTemplate.objects.create(
            company=company,
            title="Opening checklist",
            due_time="08:30",
            created_by=owner,
            needs_confirmation=True,
        )
        weekdays = TaskTemplate.objects.create(
            company=company,
            title="Reply to customer messages",
            due_time="12:00",
            weekdays=[0, 1, 2, 3, 4],
            created_by=owner,
        )
        for template in (every_day, weekdays):
            template.assignees.add(me)

        opening = task(
            "Opening checklist",
            kind=Task.Kind.DAILY,
            template=every_day,
            due=now - timedelta(hours=2),
            status=Task.Status.DONE,
            by=owner,
            needs_confirmation=True,
            completed_at=now - timedelta(hours=1, minutes=50),
            confirmed_at=now - timedelta(hours=1, minutes=40),
            confirmed_by=owner,
            description="Lights, till float, music, front door unlocked. Tick each item as you go.",
        )
        checklist(
            opening,
            ("Lights and music", True),
            ("Count the till float", True),
            ("Unlock the front door", True),
        )

        stock = task(
            "Stock count: front shelves",
            kind=Task.Kind.DAILY,
            template=every_day,
            due=now - timedelta(minutes=25),
            by=owner,
            proof=Proof.PHOTO,
            needs_confirmation=True,
            reminders_sent=1,
            next_reminder_at=now + timedelta(minutes=15),
            escalate_to=manager,
            description=(
                "Count the front shelves against the stock sheet and note anything below the "
                "minimum. Take one photo of the finished shelf."
            ),
        )
        checklist(
            stock,
            ("Drinks fridge", True),
            ("Snack shelf", False),
            ("Counter display", False),
            ("Note items below minimum", False),
        )
        TaskComment.objects.create(
            task=stock,
            author=manager,
            text="Counter display was restocked last night, so that part should be quick.",
        )

        task(
            "Reply to customer messages",
            kind=Task.Kind.DAILY,
            template=weekdays,
            due=now + timedelta(hours=2),
            by=owner,
            description=(
                "Answer everything in the shop inbox from the last 24 hours. Pass refunds and "
                "complaints to Bekzod."
            ),
        )
        task(
            "Clean and reset the workspace",
            kind=Task.Kind.DAILY,
            template=every_day,
            due=now + timedelta(hours=5),
            by=owner,
            proof=Proof.PHOTO,
        )

        window = task(
            "Prepare the window display",
            kind=Task.Kind.ASSIGNED,
            due=now + timedelta(days=2),
            status=Task.Status.IN_PROGRESS,
            by=owner,
            proof=Proof.PHOTO,
            needs_confirmation=True,
            started_at=now - timedelta(hours=1),
            description=(
                "Set up the autumn window with the new arrivals. Keep the left side for the sale "
                "rail and leave room for the price cards."
            ),
        )
        checklist(
            window,
            ("Clear the old display", True),
            ("Steam the clothes", True),
            ("Dress the two mannequins", False),
            ("Place the price cards", False),
            ("Photo from the street", False),
        )
        TaskComment.objects.create(
            task=window, author=owner, text="Mannequins are in the stock room, top shelf."
        )
        TaskComment.objects.create(
            task=window, author=manager, text="I can help after 14:00 if needed."
        )
        TaskComment.objects.create(
            task=window,
            author=owner,
            text="@Alisher can you take the street photo once the lights are on?",
        )

        supplier = task(
            "Call the supplier about the late delivery",
            kind=Task.Kind.ASSIGNED,
            due=now + timedelta(hours=4),
            by=manager,
            proof=Proof.TEXT,
            description=(
                "Order #4471 was due on Friday. Ask for a new delivery date and write it in the "
                "note."
            ),
        )
        tags = task(
            "Update price tags for the winter range",
            kind=Task.Kind.ASSIGNED,
            due=now + timedelta(hours=1),
            by=owner,
            status=Task.Status.REVIEW,
            proof=Proof.PHOTO,
            needs_confirmation=True,
            completed_at=now - timedelta(minutes=10),
        )
        checklist(tags, ("Rail 3", True), ("Rail 4", True))
        photos = task(
            "Photograph the new arrivals",
            kind=Task.Kind.ASSIGNED,
            due=now + timedelta(hours=3),
            by=owner,
            status=Task.Status.RETURNED,
            proof=Proof.PHOTO,
            needs_confirmation=True,
            description=(
                "Flat-lay photos of the twelve new pieces for the shop channel, one per piece."
            ),
        )
        TaskComment.objects.create(
            task=photos,
            author=owner,
            text="Retake these in daylight, please. The colours look off.",
        )

        task("Order receipt rolls", kind=Task.Kind.PERSONAL, due=now + timedelta(hours=3))
        task(
            "Learn the refunds flow on the new till",
            kind=Task.Kind.PERSONAL,
            due=now + timedelta(days=3),
        )
        plants = TaskTemplate.objects.create(
            company=company,
            title="Water the plants",
            due_time="09:00",
            weekdays=[timezone.localtime(now).weekday()],
            personal=True,
            created_by=me,
        )
        plants.assignees.add(me)
        task(
            "Water the plants",
            kind=Task.Kind.PERSONAL,
            template=plants,
            due=now - timedelta(minutes=50),
            status=Task.Status.DONE,
            completed_at=now - timedelta(minutes=45),
        )

        # A streak: five earlier days with everything done in time, and one free day before them.
        for days_ago in range(1, 6):
            due = now - timedelta(days=days_ago)
            task(
                "Opening checklist",
                kind=Task.Kind.DAILY,
                template=every_day,
                due=due,
                by=owner,
                status=Task.Status.DONE,
                completed_at=due - timedelta(minutes=20),
            )

        # Two weeks of the others' daily work, so the team results have something to show.
        history(company, owner, madina, "Count the till", now, late={3, 9})
        history(
            company,
            owner,
            jasur,
            "Receive the morning delivery",
            now,
            late={1, 2, 5, 8, 12},
            missed={4, 10},
        )
        history(company, owner, nigora, "Deliver online orders", now)

        # Time off: Madina is off today and tomorrow, Alisher is waiting for an answer.
        today = timezone.localdate()
        TimeOff.objects.create(
            company=company,
            membership=madina,
            first_day=today,
            last_day=today + timedelta(days=1),
            status=TimeOff.Status.APPROVED,
            decided_by=manager.user,
            decided_at=now - timedelta(days=2),
        )
        TimeOff.objects.create(
            company=company,
            membership=me,
            first_day=today + timedelta(days=7),
            last_day=today + timedelta(days=8),
            reason="My sister's wedding",
        )
        constitution_day = today.replace(month=12, day=8)
        if constitution_day < today:
            constitution_day = constitution_day.replace(year=today.year + 1)
        Holiday.objects.create(company=company, date=constitution_day, name="Constitution Day")

        def feed(kind, about, actor, text="", minutes_ago=0, read=False):
            entry = Activity.objects.create(
                company=company,
                recipient=me,
                actor=actor,
                kind=kind,
                task=about,
                text=text,
                read_at=now if read else None,
            )
            Activity.objects.filter(pk=entry.pk).update(
                created_at=now - timedelta(minutes=minutes_ago)
            )

        feed(Activity.Kind.ASSIGNED, supplier, manager, minutes_ago=6)
        feed(
            Activity.Kind.RETURNED,
            photos,
            owner,
            "Retake these in daylight, please. The colours look off.",
            minutes_ago=14,
        )
        feed(Activity.Kind.CONFIRMED, opening, owner, minutes_ago=100, read=True)
        feed(Activity.Kind.ASSIGNED, window, owner, minutes_ago=180, read=True)
        feed(
            Activity.Kind.COMMENTED,
            stock,
            manager,
            "Counter display was restocked last night, so that part should be quick.",
            minutes_ago=200,
            read=True,
        )

        people = {
            "owner": owner,
            "manager": manager,
            "worker": me,
            "madina": madina,
            "jasur": jasur,
            "nigora": nigora,
        }
        return company, people

    def _build_cafe(self, now, *, owner: User) -> Company:
        company = create_company(name="Demo Café", slug=CAFE_SLUG, timezone="Asia/Tashkent")
        [mirobod] = self._branches(company, [CAFE_BRANCH])
        positions = {
            name: Position.objects.create(company=company, name=name, order=index)
            for index, name in enumerate(CAFE_POSITIONS)
        }
        roles = {role.name: role for role in AccessRole.objects.filter(company=company)}

        def member(user, role, position):
            created = Membership.objects.create(
                company=company,
                user=user,
                first_name=user.first_name,
                last_name=user.last_name,
                role=roles[role],
                position=positions[position],
                status=Membership.Status.APPROVED,
                onboarded_at=now - timedelta(days=30),
                home_branch=mirobod,
            )
            created.branches.set([mirobod])
            return created

        boss = member(owner, "Owner", "Office")
        manager = member(
            self._user(CAFE_MANAGER, "Sardor", "Qodirov", "+998901120001"), "Manager", "Hall"
        )
        barista = member(
            self._user(BARISTA, "Kamola", "Yusupova", "+998901120002"), "Cashier", "Barista"
        )
        cook = member(self._user(COOK, "Otabek", "Rahimov", "+998901120003"), "Employee", "Kitchen")
        mirobod.manager = manager
        mirobod.save(update_fields=["manager", "updated_at"])

        history(company, boss, barista, "Clean the coffee machine", now, late={2, 6})
        history(company, boss, cook, "Check the fridge temperatures", now, missed={3})
        opening = TaskTemplate.objects.create(
            company=company,
            title="Open the café",
            due_time="07:45",
            created_by=boss,
            needs_confirmation=True,
        )
        opening.assignees.add(barista)
        Task.objects.create(
            company=company,
            kind=Task.Kind.DAILY,
            template=opening,
            for_date=timezone.localtime(now).date(),
            title="Open the café",
            assignee=barista,
            branch=mirobod,
            created_by=boss,
            due_at=now - timedelta(hours=1),
            status=Task.Status.REVIEW,
            proof=Proof.PHOTO,
            needs_confirmation=True,
            completed_at=now - timedelta(hours=1, minutes=10),
        )
        Task.objects.create(
            company=company,
            kind=Task.Kind.ASSIGNED,
            title="Order oat milk for the weekend",
            assignee=manager,
            branch=mirobod,
            created_by=boss,
            due_at=now + timedelta(hours=6),
        )
        return company


def history(company, by, who, title, now, *, late=(), missed=(), delay=timedelta(minutes=40)):
    """Two weeks of one person's daily work, so the team results have something to show."""
    template = TaskTemplate.objects.create(
        company=company, title=title, due_time="10:00", created_by=by
    )
    template.assignees.add(who)
    for days_ago in range(1, 15):
        due = now - timedelta(days=days_ago)
        done_at = None if days_ago in missed else due - timedelta(minutes=15)
        if days_ago in late:
            done_at = due + delay
        work = Task.objects.create(
            company=company,
            kind=Task.Kind.DAILY,
            template=template,
            for_date=timezone.localtime(due).date(),
            title=title,
            assignee=who,
            branch=who.home_branch,
            created_by=by,
            due_at=due,
            status=Task.Status.TODO if done_at is None else Task.Status.DONE,
            completed_at=done_at,
        )
        if days_ago in late or days_ago in missed:
            for step in (1, 2):
                log = ReminderLog.objects.create(
                    task=work, kind=ReminderLog.Kind.REMINDER, step=step, recipient=who
                )
                ReminderLog.objects.filter(pk=log.pk).update(
                    sent_at=due + timedelta(minutes=20 * step)
                )
