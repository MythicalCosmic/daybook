"""A demo company that looks like the mini app design: for trying the app and for screenshots."""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.companies.models import Company
from apps.companies.services import create_company
from apps.groups.models import TelegramGroup
from apps.members.models import AccessRole, Membership, Position
from apps.reminders.models import ReminderLog, ReminderPolicy
from apps.tasks.models import Activity, ChecklistItem, Proof, Task, TaskComment, TaskTemplate

SLUG = "demo-shop"
POSITIONS = ["Sales floor", "Cashier", "Stock & warehouse", "Shift lead", "Delivery", "Office"]

# Telegram ids of the demo people. Sign in as one of them with dev init data.
OWNER, MANAGER, WORKER, COLLEAGUE = 1001, 1002, 4242, 1004
STOCKER, COURIER = 1005, 1006
APPLICANT, WAITING, OUTSIDER = 5001, 5002, 5003
EVERYONE = (OWNER, MANAGER, WORKER, COLLEAGUE, STOCKER, COURIER, APPLICANT, WAITING, OUTSIDER)
# Deleted in this order, so nothing still points at what goes next.
TENANT_MODELS = (
    AuditLog,
    TelegramGroup,
    Activity,
    Task,
    TaskTemplate,
    ReminderPolicy,
    Membership,
    Position,
    AccessRole,
)


class Command(BaseCommand):
    help = "Create the Demo Shop company with people and tasks (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Replace an existing demo.")
        parser.add_argument("--force", action="store_true", help="Run even when DEBUG is off.")

    def handle(self, *args, reset=False, force=False, **options):
        if not settings.DEBUG and not force:
            raise CommandError("Refusing to seed demo data with DEBUG off (use --force).")
        if Company.objects.filter(slug=SLUG).exists():
            if not reset:
                raise CommandError("The demo already exists. Use --reset to rebuild it.")
            self._remove()
        with transaction.atomic():
            self._build()
        self.stdout.write(self.style.SUCCESS("Demo Shop is ready."))
        self.stdout.write(
            f"Telegram ids: worker {WORKER}, manager {MANAGER}, owner {OWNER}, "
            f"applicant {APPLICANT}, waiting {WAITING}, outsider {OUTSIDER}."
        )

    def _remove(self):
        company = Company.objects.get(slug=SLUG)
        with transaction.atomic():
            for model in TENANT_MODELS:
                model.objects.filter(company=company).delete()
            company.delete()
            User.objects.filter(telegram_id__in=EVERYONE).delete()

    def _build(self):
        now = timezone.now()
        company = create_company(name="Demo Shop", slug=SLUG, timezone="Asia/Tashkent")
        positions = {
            name: Position.objects.create(company=company, name=name, order=index)
            for index, name in enumerate(POSITIONS)
        }
        roles = {role.name: role for role in AccessRole.objects.filter(company=company)}

        def person(telegram_id, first, last, *, role=None, position=None, phone="", **membership):
            user = User.objects.create(
                username=f"tg{telegram_id}",
                telegram_id=telegram_id,
                first_name=first,
                last_name=last,
                phone=phone,
                language="en",
            )
            user.set_unusable_password()
            user.save()
            if membership.get("status") is None and role is None:
                return user
            return Membership.objects.create(
                company=company,
                user=user,
                first_name=first,
                last_name=last,
                role=roles.get(role) if role else None,
                position=positions.get(position) if position else None,
                **membership,
            )

        registered = {
            "status": Membership.Status.APPROVED,
            "onboarded_at": now - timedelta(days=60),
        }
        owner = person(
            OWNER,
            "Dilnoza",
            "Karimova",
            role="Owner",
            position="Office",
            phone="+998901110001",
            **registered,
        )
        manager = person(
            MANAGER,
            "Bekzod",
            "Mirzayev",
            role="Manager",
            position="Shift lead",
            phone="+998901110002",
            **registered,
        )
        me = person(
            WORKER,
            "Alisher",
            "Valiyev",
            role="Employee",
            position="Sales floor",
            phone="+998901234567",
            **registered,
        )
        madina = person(
            COLLEAGUE,
            "Madina",
            "Saidova",
            role="Employee",
            position="Cashier",
            phone="+998901110004",
            **registered,
        )
        jasur = person(
            STOCKER,
            "Jasur",
            "Tursunov",
            role="Employee",
            position="Stock & warehouse",
            phone="+998901110005",
            **registered,
        )
        nigora = person(
            COURIER,
            "Nigora",
            "Azimova",
            role="Employee",
            position="Delivery",
            phone="+998901110006",
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

        def task(title, *, kind, due, status=Task.Status.TODO, by=None, **fields):
            return Task.objects.create(
                company=company,
                kind=kind,
                title=title,
                assignee=me,
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
        def history(who, title, *, late=(), missed=(), delay=timedelta(minutes=40)):
            template = TaskTemplate.objects.create(
                company=company, title=title, due_time="10:00", created_by=owner
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
                    created_by=owner,
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

        history(madina, "Count the till", late={3, 9})
        history(jasur, "Receive the morning delivery", late={1, 2, 5, 8, 12}, missed={4, 10})
        history(nigora, "Deliver online orders")

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
