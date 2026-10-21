"""Demo companies for trying the apps and for screenshots (development only), docs/PLAN-OWNER.md
§14.3; `apps/core/demo_plan.py` tells their story. Every name in them is invented.

- **Demo Dorixona**: two pharmacies, Chilonzor (08:00 to 22:00 every day) and Yunusobod (open
  around the clock, with day and night shifts), fifteen people and every module switched on.
  Each app adds its own rows through `apps/<app>/demo.py: seed(company, people, now)`.
- **Demo Distribyutor**: a small distributor with one warehouse in Sergeli, selling to
  pharmacies and clinics, with fewer modules, so the company switcher and the portfolio have
  something to show. An app fills it through an optional `seed_small(company, people, now)`,
  whose `people` are owner, manager, worker and cashier.

After every app's seed, each demo's optional `finish(company, people, now)` runs for each
company it filled: for what would refuse other demos' rows (finance closes the books there) or
needs them (card settlements after the tills). The inbox's runs last, to settle the messages
the others sent. Positions and roles get their Uzbek names once every demo has run, because the
module demos look them up by the English names they are made with.

The build is one transaction that queues no background jobs (`demo_time.quiet`), and what each
demo leaves for after commit runs right after that demo. `--reset` also removes the demos this
one replaced (Demo Shop and Demo Café). `--owner-tg <id>` makes that Telegram account an Owner
of both companies, so a real person can sign in to the dashboard and both bots against the
demo. `--only sales,finance` (or `DEMO_APPS`) runs only those apps' `demo.py`; the core demo
always runs. `-v 2` prints how long each app's demo took.
"""

import importlib
import importlib.util
import os
import time as stopwatch
from datetime import time, timedelta
from decimal import Decimal

from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F, ProtectedError, Q
from django.utils import timezone

from apps.accounts.models import User
from apps.companies.models import Branch, Company, Feature, TenantModel
from apps.companies.services import create_company
from apps.core import demo_plan as plan
from apps.core.demo_time import quiet, run_hooks
from apps.core.management.commands.ensure_company_defaults import ensure_company_defaults
from apps.members.models import AccessRole, Membership, Position
from apps.members.permissions import Perm
from apps.reminders.models import ReminderLog
from apps.tasks.models import Activity, ChecklistItem, Proof, Task, TaskComment, TaskTemplate
from apps.timeoff.models import TimeOff

SLUG, SMALL_SLUG = plan.PHARMACY, plan.DISTRIBUTOR
NAME, SMALL_NAME = "Demo Dorixona", "Demo Distribyutor"
IN_UZBEK = {Position: plan.IN_UZBEK_POSITIONS, AccessRole: plan.IN_UZBEK_ROLES}
# The distributor runs other modules, so switching companies changes the navigation too.
SMALL_FEATURES = [
    Feature.FINANCE,
    Feature.SALES,
    Feature.STOCK,
    Feature.HR,
    Feature.PAYROLL,
    Feature.AI,
]
# Yunusobod's head sees and runs only her pharmacy.
BRANCH_MANAGER_PERMISSIONS = [
    Perm.MEMBERS_VIEW,
    Perm.MEMBERS_APPROVE,
    Perm.TASKS_VIEW_ALL,
    Perm.TASKS_ASSIGN,
    Perm.TASKS_CONFIRM,
    Perm.REPORTS_VIEW,
    Perm.TIME_OFF_APPROVE,
    Perm.ANNOUNCE,
    Perm.DASHBOARD_ACCESS,
    Perm.ATTENDANCE_VIEW,
    Perm.SALES_VIEW,
    Perm.FINANCE_CLAIM,
]
# The steps of the shift handover routine.
HANDOVER_STEPS = [
    "Kassa qoldig‘ini sanash",
    "Muzlatgich haroratini tekshirish",
    "Retseptli dorilar shkafini tekshirish",
    "Navbatchilik jurnaliga imzo",
]

# Creating a company makes its first branch; the demo renames it. Yunusobod is open around the
# clock: a branch without hours is never "not opened yet" or "closed".
BRANCHES = [
    {
        "name": "Chilonzor",
        "code": "CHL",
        "address": "Bunyodkor ko‘chasi 12, Chilonzor tumani, Toshkent",
        "phone": "+998712000101",
        "latitude": Decimal("41.285680"),
        "longitude": Decimal("69.203430"),
        "opens_at": time(8, 0),
        "closes_at": time(22, 0),
        "cash_limit": Decimal("10000000.00"),
        "order": 0,
    },
    {
        "name": "Yunusobod",
        "code": "YNS",
        "address": "Amir Temur shoh ko‘chasi 107, Yunusobod tumani, Toshkent",
        "phone": "+998712000202",
        "latitude": Decimal("41.364250"),
        "longitude": Decimal("69.287950"),
        "opens_at": None,
        "closes_at": None,
        "cash_limit": Decimal("15000000.00"),
        "order": 1,
    },
]
SMALL_BRANCH = {
    "name": "Sergeli ombori",
    "code": "SRG",
    "address": "Yangi Sergeli ko‘chasi 41, Sergeli tumani, Toshkent",
    "phone": "+998712000303",
    "latitude": Decimal("41.222460"),
    "longitude": Decimal("69.221970"),
    "opens_at": time(9, 0),
    "closes_at": time(18, 0),
    "open_weekdays": [0, 1, 2, 3, 4, 5],
    "cash_limit": Decimal("5000000.00"),
    "order": 0,
}

# Telegram ids of the demo people. Sign in as one of them with dev init data.
OWNER, MANAGER, WORKER, MADINA, JASUR, NIGORA = 1001, 1002, 4242, 1004, 1005, 1006
APPLICANT, WAITING, OUTSIDER = 5001, 5002, 5003
WAREHOUSE_HEAD, STOREKEEPER, SALES_MANAGER = 2001, 2002, 2003
EVERYONE = tuple(
    sorted(
        {
            person.telegram_id
            for person in (
                *plan.PEOPLE,
                *plan.SMALL_PEOPLE,
                plan.SUSPENDED,
                plan.LEFT,
                plan.BLOCKED,
                plan.RETURNING,
            )
        }
        | {row[1] for row in plan.REQUESTS}
        | {APPLICANT, WAITING, OUTSIDER}
    )
)
# Earlier demos kept extra people at Telegram ids 3001 to 3040; a rebuild removes any left over.
OLD_PEOPLE = (3001, 3040)
# Seed hooks per company, and the demos whose `finish` waits for every other one.
SEED, SMALL_SEED = "seed", "seed_small"
FINISH_LAST = ("inbox",)


class Command(BaseCommand):
    help = (
        "Create the demo pharmacy business Demo Dorixona and the distributor Demo Distribyutor "
        "with people, tasks and every module's data (development only)."
    )

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
        if owner_tg is not None and owner_tg <= 0:
            raise CommandError(f"{owner_tg} isn't a Telegram user id.")
        # The demo's own owner already owns both companies: nothing to add.
        demo_owner = owner_tg == OWNER
        if demo_owner:
            owner_tg = None
        if owner_tg is not None and owner_tg in EVERYONE:
            raise CommandError(f"{owner_tg} is one of the demo people; pick another account.")

        exists = Company.objects.filter(slug__in=(SLUG, SMALL_SLUG, *plan.OLD_SLUGS)).exists()
        if exists and not reset:
            if demo_owner:
                self.stdout.write(
                    self.style.SUCCESS(f"{OWNER} is the demo owner: an Owner of both companies.")
                )
                return
            if owner_tg is None:
                raise CommandError(
                    "The demo already exists. Use --reset to rebuild it "
                    "(or --owner-tg to add an owner to it)."
                )
            with transaction.atomic():
                names = self._add_owner(owner_tg)
            self.stdout.write(
                self.style.SUCCESS(f"{owner_tg} is now an Owner of {', '.join(names)}.")
            )
            return

        # One transaction: if a module's demo fails, the previous demo is still there.
        with transaction.atomic(), quiet():
            if exists:
                self._remove()
            seeded, timings = self._build(demo_apps, owner_tg)
        self.stdout.write(self.style.SUCCESS(f"{NAME} and {SMALL_NAME} are ready."))
        self.stdout.write(
            f"Telegram ids: {NAME}: owner {OWNER} (both companies), head of Chilonzor "
            f"{MANAGER}, farmatsevt {WORKER}, provizor {MADINA}, courier {JASUR}, Yunusobod night "
            f"farmatsevt {NIGORA}, applicant {APPLICANT}, waiting {WAITING}, outsider "
            f"{OUTSIDER}; {SMALL_NAME}: warehouse manager {WAREHOUSE_HEAD}, storekeeper "
            f"{STOREKEEPER}, sales manager {SALES_MANAGER}."
        )
        if owner_tg is not None:
            self.stdout.write(f"{owner_tg} is an Owner of both companies.")
        self.stdout.write(f"Module demo data: {', '.join(seeded) or 'none'}.")
        if options.get("verbosity", 1) >= 2:
            for label, seconds in sorted(timings.items(), key=lambda item: -item[1]):
                self.stdout.write(f"  {label:14} {seconds:5.1f} s")

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
        for company in Company.objects.filter(slug__in=(SLUG, SMALL_SLUG, *plan.OLD_SLUGS)):
            self._remove_company(company)
        # Only the demo people: an --owner-tg account is a real person and stays.
        first, last = OLD_PEOPLE
        User.objects.filter(
            Q(telegram_id__in=EVERYONE) | Q(telegram_id__range=(first, last))
        ).delete()

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

    def _build(self, demo_apps: set[str] | None, owner_tg: int | None):
        now = timezone.now()
        shop, people = self._build_pharmacy(now)
        small, small_people = self._build_distributor(now, owner=people["owner"].user)

        shop.features = list(Feature.values)
        small.features = [str(feature) for feature in SMALL_FEATURES]
        for company in (shop, small):
            company.save(update_fields=["features", "updated_at"])
            ensure_company_defaults(company)

        demos = []
        for config in django_apps.get_app_configs():
            if not config.name.startswith("apps."):
                continue
            if demo_apps is not None and config.label not in demo_apps:
                continue
            name = f"{config.name}.demo"
            if importlib.util.find_spec(name) is None:
                continue
            demos.append((config.label, importlib.import_module(name)))

        timings: dict[str, float] = {}

        def run(label, function, company, crew):
            started = stopwatch.perf_counter()
            with run_hooks():  # what this demo left for after commit happens now, in its turn
                function(company, crew, now)
            timings[label] = timings.get(label, 0.0) + stopwatch.perf_counter() - started

        filled = []
        for company, crew, hook in ((shop, people, SEED), (small, small_people, SMALL_SEED)):
            ran = [(label, demo) for label, demo in demos if hasattr(demo, hook)]
            for label, demo in ran:
                run(label, getattr(demo, hook), company, crew)
            filled.append((company, crew, ran))
        # Then each demo's optional `finish`: what would refuse other demos' rows (closing the
        # books) or needs them waits until every demo has written its own, whatever order the
        # apps run in.
        for company, crew, ran in filled:
            for label, demo in sorted(ran, key=lambda item: item[0] in FINISH_LAST):
                if finish := getattr(demo, "finish", None):
                    run(label, finish, company, crew)
        for company in (shop, small):
            for model, names in IN_UZBEK.items():
                for english, uzbek in names.items():
                    model.objects.filter(company=company, name=english).update(name=uzbek)

        # Last, so the module demos never treat a real person as one of the staff.
        if owner_tg is not None:
            self._add_owner(owner_tg)
        seeded = [label for label, demo in demos if hasattr(demo, SEED)]
        return seeded, timings

    def _add_owner(self, telegram_id: int) -> list[str]:
        """Make `telegram_id` an approved Owner of every demo company that exists."""
        now = timezone.now()
        user = User.objects.filter(telegram_id=telegram_id).first()
        if user is None:
            # Their name and language arrive when they first open one of the bots.
            user = User(username=f"tg{telegram_id}", telegram_id=telegram_id)
            user.set_unusable_password()
            user.save()
        names = []
        for company in Company.objects.filter(slug__in=(SLUG, SMALL_SLUG)).order_by("name"):
            branches = list(company.branches.order_by("order", "pk"))
            # By what it is, not its name: an owner may have renamed the role.
            role = AccessRole.objects.filter(company=company, is_owner=True).order_by("pk").first()
            if role is None:
                raise CommandError(f"{company.name} has no owner role.")
            membership, _ = Membership.objects.update_or_create(
                company=company,
                user=user,
                defaults={
                    "status": Membership.Status.APPROVED,
                    "role": role,
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

    def _user(self, telegram_id, first, last, *, phone="", username="", language="uz") -> User:
        user = User(
            username=f"tg{telegram_id}",
            telegram_id=telegram_id,
            first_name=first,
            last_name=last,
            phone=phone,
            telegram_username=username,
            language=language,
        )
        user.set_unusable_password()
        user.save()
        return user

    def _staff(self, company, cast, branches, now, *, users=None) -> dict[str, Membership]:
        """The approved people of `cast`, joined (approved by the owner) and registered on the
        day the story says, working in their branches."""
        story = plan.Plan(company, {}, now)
        names = plan.POSITIONS if company.slug == SLUG else plan.SMALL_POSITIONS
        positions = {
            name: Position.objects.create(company=company, name=name, order=index)
            for index, name in enumerate(names)
        }
        roles = {role.name: role for role in AccessRole.objects.filter(company=company)}
        if any(person.role == plan.BRANCH_MANAGER for person in cast):
            roles[plan.BRANCH_MANAGER] = AccessRole.objects.create(
                company=company,
                name=plan.BRANCH_MANAGER,
                permissions=[str(perm) for perm in BRANCH_MANAGER_PERMISSIONS],
            )
        users = users or {}
        made = {}
        for person in cast:
            user = users.get(person.telegram_id) or self._user(
                person.telegram_id,
                person.first,
                person.last,
                phone=person.phone,
                username=person.username,
                language=person.language,
            )
            joined = story.at(story.joined(person.key), time(10, 0))
            owner = made.get("owner")
            member = Membership.objects.create(
                company=company,
                user=user,
                first_name=person.first,
                last_name=person.last,
                role=roles[person.role],
                position=positions.get(person.position) if person.position else None,
                status=Membership.Status.APPROVED,
                decided_at=joined,
                decided_by=owner.user if owner else None,
                onboarded_at=joined + timedelta(hours=1),
                home_branch=branches[person.branches[0]],
            )
            member.branches.set([branches[code] for code in person.branches])
            made[person.key] = member
        return made

    def _build_pharmacy(self, now) -> tuple[Company, dict[str, Membership]]:
        company = create_company(name=NAME, slug=SLUG, timezone="Asia/Tashkent")
        chilonzor, yunusobod = self._branches(company, BRANCHES)
        staff = self._staff(company, plan.PEOPLE, {"C": chilonzor, "Y": yunusobod}, now)
        chilonzor.manager = staff["manager"]
        chilonzor.save(update_fields=["manager", "updated_at"])
        yunusobod.manager = staff["farrux"]
        yunusobod.save(update_fields=["manager", "updated_at"])

        # Someone who just pressed /start, someone who filled in the form and waits, and a
        # Telegram user who belongs to no company.
        Membership.objects.create(
            company=company,
            user=self._user(APPLICANT, "Javohir", "Rasulov"),
            first_name="Javohir",
            last_name="Rasulov",
            status=Membership.Status.PENDING,
        )
        Membership.objects.create(
            company=company,
            user=self._user(WAITING, "Sevara", "Tursunova", phone="+998935550202"),
            first_name="Sevara",
            last_name="Tursunova",
            position=Position.objects.get(company=company, name=plan.PHARMACIST),
            status=Membership.Status.PENDING,
            onboarded_at=now - timedelta(minutes=3),
        )
        self._user(OUTSIDER, "Temur", "Begmatov")

        people = {key: staff[key] for key in plan.CORE}
        self._pharmacy_work(company, plan.Plan(company, people, now), now)
        return company, people

    def _pharmacy_work(self, company, story: plan.Plan, now) -> None:
        """What the bot and the mini app show without any app's demo: Alisher's routines and
        today's work (he opens Chilonzor today), two weeks of three colleagues' routines, and
        Madina's and Alisher's time off."""
        owner, me = story.member("owner"), story.member("worker")
        today = story.today

        def at(hour, minute=0, day=today):
            return story.at(day, time(hour, minute))

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

        handover = TaskTemplate.objects.create(
            company=company,
            title=plan.HANDOVER,
            due_time="08:15",
            created_by=owner,
            needs_confirmation=True,
        )
        orders = TaskTemplate.objects.create(
            company=company, title=plan.TELEGRAM_ORDERS, due_time="12:00", created_by=owner
        )
        for template in (handover, orders):
            template.assignees.add(me)

        # Today's shift, 08:00 to 20:00: what's done by now is done.
        opened = task(
            plan.HANDOVER,
            kind=Task.Kind.DAILY,
            template=handover,
            for_date=today,
            due=at(8, 15),
            by=owner,
            needs_confirmation=True,
            description="Kechagi smenadan dorixonani qabul qiling va har bir bandni belgilang.",
            **(
                {
                    "status": Task.Status.DONE,
                    "completed_at": at(8, 9),
                    "confirmed_at": at(8, 40),
                    "confirmed_by": owner,
                }
                if now >= at(8, 45)
                else {}
            ),
        )
        for order, text in enumerate(HANDOVER_STEPS):
            ChecklistItem.objects.create(
                task=opened, text=text, is_done=opened.status == Task.Status.DONE, order=order
            )
        task(
            plan.TELEGRAM_ORDERS,
            kind=Task.Kind.DAILY,
            template=orders,
            for_date=today,
            due=at(12),
            by=owner,
            description=(
                "Kechagi va bugungi buyurtmalarga javob bering. Retseptli dori so‘rashsa, "
                "retsept bilan kelishini ayting: retseptli dorilar yetkazib berilmaydi."
            ),
            **({"status": Task.Status.DONE, "completed_at": at(11, 42)} if now >= at(12) else {}),
        )
        tomorrow = story.next_working_day("worker", today) or today + timedelta(days=1)
        showcase = task(
            "Vitrinani yangilash: shamollash va gripp mavsumi",
            kind=Task.Kind.ASSIGNED,
            due=at(18, day=tomorrow),
            status=Task.Status.IN_PROGRESS if now >= at(9, 30) else Task.Status.TODO,
            by=owner,
            proof=Proof.PHOTO,
            needs_confirmation=True,
            started_at=at(9, 30) if now >= at(9, 30) else None,
            description=(
                "Retseptsiz bo‘limga vitaminlar, yo‘tal siroplari va burun spreylarini "
                "qo‘ying. Retseptli dorilar vitrinaga qo‘yilmaydi."
            ),
        )
        for order, (text, ticked) in enumerate(
            (
                ("Eski vitrinani yig‘ish", True),
                ("Askorbin kislotasi va sink preparatlari", True),
                ("Yo‘tal siroplari va pastillalar", False),
                ("Narx yorliqlari", False),
            )
        ):
            ChecklistItem.objects.create(
                task=showcase, text=text, is_done=ticked and now >= at(10), order=order
            )
        TaskComment.objects.create(
            task=showcase, author=owner, text="Yangi narx yorliqlari omborda, yuqori javonda."
        )
        task("Kassa lentasidan buyurtma berish", kind=Task.Kind.PERSONAL, due=at(15))
        task(
            "Yangi kassa dasturida smena yopishni o‘rganish",
            kind=Task.Kind.PERSONAL,
            due=at(16, day=story.next_working_day("worker", tomorrow) or tomorrow),
        )
        plants = TaskTemplate.objects.create(
            company=company,
            title="Dorixonadagi gullarni sug‘orish",
            due_time="09:00",
            weekdays=[today.weekday()],
            personal=True,
            created_by=me,
        )
        plants.assignees.add(me)
        task(
            plants.title,
            kind=Task.Kind.PERSONAL,
            template=plants,
            for_date=today,
            due=at(9),
            **({"status": Task.Status.DONE, "completed_at": at(8, 52)} if now >= at(9) else {}),
        )

        # A streak: his last five working days with the handover done in time.
        day = today
        for _ in range(5):
            day = story.last_working_day("worker", day)
            if day is None:
                break
            due = at(8, 15, day=day)
            task(
                plan.HANDOVER,
                kind=Task.Kind.DAILY,
                template=handover,
                for_date=day,
                due=due,
                by=owner,
                status=Task.Status.DONE,
                needs_confirmation=True,
                completed_at=due - timedelta(minutes=9),
                confirmed_at=due + timedelta(minutes=25),
                confirmed_by=owner,
            )

        # Two weeks of three colleagues' routines, so the team results have something to show.
        history(story, owner, "madina", plan.CASH_REPORT, due=time(21, 45), late={3})
        history(story, owner, "jasur", plan.DELIVERIES, due=time(13), late={1, 2, 5}, missed={4})
        history(story, owner, "nigora", plan.FRIDGE_EVENING, due=time(20, 30))

        for row in plan.TIME_OFF:
            if row.who not in ("madina", "worker") or row.status not in ("approved", "pending"):
                continue
            decided = row.status == "approved"
            TimeOff.objects.create(
                company=company,
                membership=story.member(row.who),
                first_day=story.day(row.first),
                last_day=story.day(row.last),
                reason=row.reason,
                status=row.status,
                decided_by=story.member(row.decided_by).user if decided else None,
                decided_at=now - timedelta(days=max(row.asked - 1, 0)) if decided else None,
            )

        def feed(kind, about, actor, at_, text="", read=False):
            entry = Activity.objects.create(
                company=company,
                recipient=me,
                actor=actor,
                kind=kind,
                task=about,
                text=text,
                read_at=now if read else None,
            )
            Activity.objects.filter(pk=entry.pk).update(created_at=at_)

        # The owner gave the showcase this morning, or last evening when it's still early.
        given = at(9, 20) if now >= at(9, 30) else at(18, 30, day=today - timedelta(days=1))
        noted = given + timedelta(minutes=15)
        feed(Activity.Kind.ASSIGNED, showcase, owner, given)
        feed(Activity.Kind.COMMENTED, showcase, owner, noted, showcase.comments.get().text)
        if opened.status == Task.Status.DONE:
            feed(Activity.Kind.CONFIRMED, opened, owner, opened.confirmed_at, read=True)
        TaskComment.objects.filter(task=showcase).update(created_at=noted)
        Task.objects.filter(pk=showcase.pk).update(created_at=given)
        # Everything else Alisher has today was made at midnight, like daily generation.
        Task.objects.filter(company=company, assignee=me, for_date=today).update(
            created_at=min(now, at(0, 5))
        )

    def _build_distributor(self, now, *, owner: User) -> tuple[Company, dict[str, Membership]]:
        company = create_company(name=SMALL_NAME, slug=SMALL_SLUG, timezone="Asia/Tashkent")
        [sergeli] = self._branches(company, [SMALL_BRANCH])
        staff = self._staff(company, plan.SMALL_PEOPLE, {"S": sergeli}, now, users={OWNER: owner})
        sergeli.manager = staff["manager"]
        sergeli.save(update_fields=["manager", "updated_at"])
        people = {key: staff[key] for key in plan.SMALL_CORE}
        story = plan.Plan(company, people, now)
        boss, days = staff["owner"], plan.SMALL_DAYS

        history(
            story,
            boss,
            "worker",
            "Ombor harorati va namligini yozish",
            due=time(9, 15),
            days=days,
            late={2},
        )
        history(story, boss, "manager", "Kunlik jo‘natmalarni tekshirish", due=time(17), days=days)
        history(
            story,
            boss,
            "driver",
            "Buyurtmalarni dorixonalarga yetkazish",
            due=time(14),
            days=days,
            missed={3},
        )
        picking = TaskTemplate.objects.create(
            company=company,
            title="Buyurtmalarni yig‘ish va yuklash",
            due_time="11:00",
            created_by=boss,
            needs_confirmation=True,
            checklist=["Buyurtma varaqasi", "Seriya va muddatini tekshirish", "Yuk xati"],
        )
        picker = story.member("worker")
        picking.assignees.add(picker)
        if story.works("worker", story.today):
            due = story.at(story.today, time(11, 0))
            Task.objects.create(
                company=company,
                kind=Task.Kind.DAILY,
                template=picking,
                for_date=story.today,
                title=picking.title,
                assignee=picker,
                branch=sergeli,
                created_by=boss,
                due_at=due,
                status=Task.Status.REVIEW if now > due else Task.Status.TODO,
                proof=Proof.PHOTO,
                needs_confirmation=True,
                completed_at=due - timedelta(minutes=6) if now > due else None,
            )
        manager_day = (
            story.today
            if story.works("manager", story.today)
            else story.next_working_day("manager", story.today)
        )
        Task.objects.create(
            company=company,
            kind=Task.Kind.ASSIGNED,
            title="Kirim: Amoksitsillin 500 mg kapsula partiyasining seriyasini tekshirish",
            assignee=staff["manager"],
            branch=sergeli,
            created_by=boss,
            due_at=story.at(manager_day, time(17, 0)),
            description="Yaroqlilik muddati 12 oydan kam bo‘lsa, qabul qilmang.",
        )
        return company, people


def history(story, by, key, title, *, due=time(10, 0), days=14, late=(), missed=()):
    """Two weeks (`days`) of one person's routine, on the days they work. `late` and `missed`
    count their working days back (1 is the last one), so the story stays the same whatever the
    rota."""
    who = story.member(key)
    if who is None:
        return None
    company = story.company
    template = TaskTemplate.objects.create(
        company=company, title=title, due_time=due, created_by=by
    )
    template.assignees.add(who)
    tasks, worked = [], 0
    for days_ago in range(1, days + 1):
        day = story.day(-days_ago)
        if not story.works(key, day):
            continue
        worked += 1
        due_at = story.at(day, due)
        done_at = None if worked in missed else due_at - timedelta(minutes=15)
        if worked in late:
            done_at = due_at + timedelta(minutes=40)
        tasks.append(
            Task(
                company=company,
                kind=Task.Kind.DAILY,
                template=template,
                for_date=day,
                title=title,
                assignee=who,
                branch=who.home_branch,
                created_by=by,
                due_at=due_at,
                status=Task.Status.TODO if done_at is None else Task.Status.DONE,
                completed_at=done_at,
                reminders_sent=2 if worked in late or worked in missed else 0,
            )
        )
    Task.objects.bulk_create(tasks)
    # Made the evening before, like daily generation does.
    Task.objects.filter(pk__in=[work.pk for work in tasks]).update(
        created_at=F("due_at") - timedelta(hours=8)
    )
    logs = [
        ReminderLog(task=work, kind=ReminderLog.Kind.REMINDER, step=step, recipient=who)
        for work in tasks
        if work.reminders_sent
        for step in (1, 2)
    ]
    ReminderLog.objects.bulk_create(logs)
    for log in logs:
        ReminderLog.objects.filter(pk=log.pk).update(
            sent_at=log.task.due_at + timedelta(minutes=20 * log.step)
        )
    return template
