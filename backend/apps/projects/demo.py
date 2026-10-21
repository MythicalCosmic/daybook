"""Demo data of projects (docs/PLAN-OWNER.md §13.3): four projects with boards, labels,
milestones, 30 cards each (12 on the finished one), a week and a half of time, updates, links,
a running timer, and expenses on the ledger for the branch opening and the website.

- "Chilonzor branch opening" (OPEN): active, at risk (due in 6 days, about half done), budget
  120 000 000 so‘m with about 86 million spent.
- "Website relaunch" (WEB): active, on track.
- "Q4 stock audit" (AUDIT): planning.
- "Back-to-school promo" (PROMO): completed last month.
"""

from __future__ import annotations

import io
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.projects import queries
from apps.projects.models import (
    Card,
    Label,
    Milestone,
    Project,
    ProjectFile,
    ProjectLink,
    ProjectList,
    ProjectMember,
    ProjectUpdate,
    RunningTimer,
    TaskLabel,
    TimeEntry,
)
from apps.tasks.models import ChecklistItem, Proof, Task, TaskComment

TODO, DOING, REVIEW, DONE = "todo", "doing", "review", "done"
BACKLOG = "backlog"

# (title, person, list, labels, due offset in days, extra)
OPENING_CARDS = [
    ("Sign the lease with the landlord", "owner", DONE, ["Legal"], -38, {}),
    ("Register the branch with the tax office", "owner", DONE, ["Legal"], -33, {}),
    ("Measure the space and draw the floor plan", "manager", DONE, [], -35, {}),
    ("Pick the fit-out contractor", "manager", DONE, ["Construction"], -31, {}),
    ("Order shelving from Mebel Lux", "jasur", DONE, ["Equipment"], -27, {}),
    ("Dismantle the old partitions", "worker", DONE, ["Construction"], -26, {}),
    ("Electrical rough-in", "worker", DONE, ["Construction"], -21, {}),
    ("Order POS terminals (Uzcard, Humo)", "madina", DONE, ["Equipment"], -19, {}),
    ("Post cashier vacancies on OLX and hh.uz", "nigora", DONE, ["Hiring"], -24, {}),
    ("Interview cashier candidates", "manager", DONE, ["Hiring"], -14, {}),
    ("Order the storefront sign from Reklama Pro", "nigora", DONE, ["Marketing"], -16, {}),
    ("Paint walls and ceiling", "worker", DONE, ["Construction"], -12, {}),
    ("Install air conditioners", "jasur", DONE, ["Equipment"], -9, {}),
    ("Fire safety inspection", "manager", DONE, ["Legal", "Urgent"], -6, {}),
    ("Set up the Uzonline fibre internet", "jasur", DONE, ["Equipment"], -5, {}),
    ("Design the opening flyers", "nigora", DONE, ["Marketing"], -3, {}),
    (
        "Lay floor tiles in the sales area",
        "worker",
        REVIEW,
        ["Construction"],
        1,
        {"proof": Proof.PHOTO, "needs_confirmation": True},
    ),
    ("Install security cameras", "jasur", REVIEW, ["Equipment"], 2, {"needs_confirmation": True}),
    (
        "Install shelving and fridges",
        "jasur",
        DOING,
        ["Equipment"],
        2,
        {
            "checklist": [
                ("Shelving, aisles 1–6", True),
                ("Two drink fridges", True),
                ("Freezer", False),
            ]
        },
    ),
    ("Connect the POS to the 1C database", "madina", DOING, ["Equipment"], 3, {}),
    (
        "Train new cashiers on the till",
        "madina",
        DOING,
        ["Hiring"],
        4,
        {"checklist": [("Gulnoza", True), ("Sardor", True), ("Shahzoda", False)]},
    ),
    ("Mount the storefront sign", "madina", DOING, ["Marketing", "Urgent"], -1, {}),
    ("Final electrical check", "worker", DOING, ["Construction"], 2, {}),
    ("First stock delivery from the warehouse", "jasur", TODO, [], 4, {}),
    ("Launch the Instagram countdown", "nigora", TODO, ["Marketing"], 3, {}),
    ("Print price tags", "madina", TODO, [], 5, {}),
    ("Clean up after the builders", "worker", TODO, ["Construction"], 4, {}),
    ("Balloons and music for the grand opening", "nigora", BACKLOG, ["Marketing"], 6, {}),
    ("Invite neighbours with 10% coupons", "nigora", BACKLOG, ["Marketing"], 6, {}),
    ("Plan opening day shifts", "manager", BACKLOG, ["Hiring"], 5, {}),
]

WEBSITE_CARDS = [
    ("Collect requirements from the managers", "owner", DONE, ["Content"], -30, {}),
    ("Pick a CMS: Tilda or custom", "owner", DONE, ["Tech"], -28, {}),
    ("Moodboard and brand colours", "nigora", DONE, ["Design"], -26, {}),
    ("Homepage design", "nigora", DONE, ["Design"], -22, {}),
    ("Product page design", "nigora", DONE, ["Design"], -19, {}),
    ("Renew the demoshop.uz domain", "owner", DONE, ["Tech"], -18, {}),
    ("Hosting in a Tashkent data centre", "owner", DONE, ["Tech"], -16, {}),
    ("Photograph the top 50 products", "madina", DONE, ["Content"], -13, {}),
    ("Write About us in Uzbek and Russian", "nigora", DONE, ["Content", "SEO"], -11, {}),
    ("Set up Google Analytics", "owner", DONE, ["Tech", "SEO"], -9, {}),
    ("Design the mobile menu", "nigora", DONE, ["Design"], -7, {}),
    ("Approve the final design", "owner", DONE, ["Design"], -5, {}),
    ("Prepare product categories", "madina", DONE, ["Content"], -4, {}),
    (
        "Upload the first 200 products",
        "madina",
        REVIEW,
        ["Content"],
        3,
        {"needs_confirmation": True},
    ),
    (
        "Translate the catalog to Russian",
        "nigora",
        REVIEW,
        ["Content"],
        4,
        {"needs_confirmation": True},
    ),
    ("Connect Click payments", "owner", DOING, ["Tech"], 9, {}),
    ("Connect Payme payments", "owner", DOING, ["Tech"], 10, {}),
    ("Delivery zones and prices", "manager", DOING, [], 8, {}),
    ("SEO titles for every category", "nigora", DOING, ["SEO"], 12, {}),
    ("Photograph the remaining 150 products", "madina", DOING, ["Content"], 14, {}),
    ("Order notifications to the Telegram group", "owner", TODO, ["Tech"], 18, {}),
    ("Cookie and privacy page", "nigora", TODO, ["Content"], 20, {}),
    ("Speed test on a 3G connection", "owner", TODO, ["Tech"], 22, {}),
    ("Test checkout on iPhone and Android", "madina", TODO, ["Tech"], 24, {}),
    ("Train staff to handle web orders", "manager", TODO, [], 28, {}),
    ("Redirects from the old site", "owner", TODO, ["SEO", "Tech"], 30, {}),
    ("Loyalty points on the site", "owner", BACKLOG, [], 34, {}),
    ("Blog: a weekly recipe", "nigora", BACKLOG, ["Content", "SEO"], 34, {}),
    ("Customer reviews widget", "nigora", BACKLOG, ["Design"], 34, {}),
    ("Wishlist", "owner", BACKLOG, ["Design"], 34, {}),
]

AUDIT_AREAS = [
    "aisle 1 (drinks)",
    "aisle 2 (snacks)",
    "aisle 3 (dairy)",
    "aisle 4 (groceries)",
    "aisle 5 (household)",
    "aisle 6 (personal care)",
    "the cold room",
    "the freezers",
    "the back store",
    "cigarettes and the till area",
    "Yunusobod: front shelves",
    "Yunusobod: back store",
    "Yunusobod: freezers",
    "returns and damaged goods",
]

PROMO_CARDS = [
    ("Pick 40 school items for the promo", "owner", ["Marketing"]),
    ("Negotiate supplier discounts", "manager", ["Marketing"]),
    ("Design the promo posters", "nigora", ["Design"]),
    ("Print posters and price toppers", "nigora", ["Design"]),
    ("Set promo prices in 1C", "madina", []),
    ("Build the school-bag display", "jasur", []),
    ("Instagram reels with the kids' corner", "nigora", ["Marketing"]),
    ("Brief cashiers on the bundle offer", "madina", []),
    ("Extra stock of notebooks", "jasur", []),
    ("Count promo results by branch", "manager", []),
    ("Return unsold stock to suppliers", "jasur", []),
    ("Write the promo report", "owner", ["Marketing"]),
]


def seed(company, people, now) -> None:
    rng = random.Random(911)
    tz = ZoneInfo(company.timezone)
    today = timezone.localtime(now, tz).date()
    branches = {branch.name: branch for branch in company.branches.all()}
    first_branch = company.branches.order_by("order", "pk").first()
    chilonzor = branches.get("Chilonzor", first_branch)
    yunusobod = branches.get("Yunusobod", first_branch)
    owner, manager = people["owner"], people["manager"]

    opening = _project(
        company,
        people,
        name="Chilonzor branch opening",
        key="OPEN",
        color="chart-1",
        icon="store",
        description=(
            "Our second shop on Bunyodkor street, Chilonzor. Fit-out, equipment, hiring three "
            "cashiers and a **grand opening** with a 10% coupon for the neighbourhood.\n\n"
            "- Contractor: Ustalar Group\n- Shelving: Mebel Lux\n- Signage: Reklama Pro"
        ),
        status=Project.Status.ACTIVE,
        priority=Project.Priority.HIGH,
        lead=manager,
        branch=chilonzor,
        start_on=today - timedelta(days=40),
        due_on=today + timedelta(days=6),
        budget=Decimal("120000000"),
        visibility=Project.Visibility.MEMBERS,
        members=["owner", "worker", "madina", "jasur", "nigora"],
        labels=[
            ("Construction", "chart-2"),
            ("Equipment", "chart-3"),
            ("Hiring", "chart-6"),
            ("Marketing", "chart-4"),
            ("Legal", "chart-5"),
            ("Urgent", "chart-1"),
        ],
        milestones=[
            ("Lease signed", -38, True),
            ("Fit-out complete", 2, False),
            ("Staff hired and trained", 4, False),
            ("Grand opening", 6, False),
        ],
        now=now,
    )
    _cards(opening, people, OPENING_CARDS, today=today, tz=tz, now=now, rng=rng, start=-42)
    website = _project(
        company,
        people,
        name="Website relaunch",
        key="WEB",
        color="chart-3",
        icon="globe",
        description=(
            "A new demoshop.uz with the full catalog, Click and Payme payments, delivery across "
            "Tashkent and order alerts in our Telegram group."
        ),
        status=Project.Status.ACTIVE,
        priority=Project.Priority.NORMAL,
        lead=owner,
        branch=None,
        start_on=today - timedelta(days=32),
        due_on=today + timedelta(days=35),
        budget=Decimal("35000000"),
        visibility=Project.Visibility.COMPANY,
        members=["manager", "madina", "nigora"],
        labels=[
            ("Design", "chart-5"),
            ("Content", "chart-2"),
            ("Tech", "chart-3"),
            ("SEO", "chart-6"),
        ],
        milestones=[
            ("Design approved", -5, True),
            ("Catalog and photos", 12, False),
            ("Payments live (Click, Payme)", 25, False),
            ("Launch", 35, False),
        ],
        now=now,
    )
    _cards(website, people, WEBSITE_CARDS, today=today, tz=tz, now=now, rng=rng, start=-32)
    audit = _project(
        company,
        people,
        name="Q4 stock audit",
        key="AUDIT",
        color="chart-6",
        icon="clipboard-list",
        description=(
            "Full count of both shops before the year closes, reconciled with 1C and the ledger."
        ),
        status=Project.Status.PLANNING,
        priority=Project.Priority.NORMAL,
        lead=people["jasur"],
        branch=yunusobod,
        start_on=today + timedelta(days=10),
        due_on=today + timedelta(days=45),
        budget=Decimal("8000000"),
        visibility=Project.Visibility.MEMBERS,
        members=["worker", "manager", "madina"],
        labels=[("Counting", "chart-2"), ("Warehouse", "chart-3"), ("Reconciliation", "chart-4")],
        milestones=[
            ("Count plan agreed", 9, False),
            ("Yunusobod counted", 24, False),
            ("Chilonzor counted", 34, False),
            ("Reconciled with the ledger", 45, False),
        ],
        now=now,
    )
    _cards(audit, people, _audit_cards(), today=today, tz=tz, now=now, rng=rng, start=-6)
    promo = _project(
        company,
        people,
        name="Back-to-school promo",
        key="PROMO",
        color="chart-4",
        icon="backpack",
        description=(
            "August–September promo on school goods in both shops. "
            "Closed with +18% on the category."
        ),
        status=Project.Status.COMPLETED,
        priority=Project.Priority.NORMAL,
        lead=owner,
        branch=None,
        start_on=today - timedelta(days=75),
        due_on=today - timedelta(days=30),
        budget=Decimal("15000000"),
        visibility=Project.Visibility.COMPANY,
        members=["manager", "madina", "jasur", "nigora"],
        labels=[("Marketing", "chart-4"), ("Design", "chart-5")],
        milestones=[("Promo live", -62, True), ("Report", -30, True)],
        now=now,
    )
    promo_cards = [
        (title, who, DONE, labels, -70 + i * 4, {})
        for i, (title, who, labels) in enumerate(PROMO_CARDS)
    ]
    _cards(promo, people, promo_cards, today=today, tz=tz, now=now, rng=rng, start=-74)
    Project.objects.filter(pk=promo.pk).update(completed_at=now - timedelta(days=30))

    _updates(opening, website, promo, people, now)
    _time(company, [opening, website], people, today=today, rng=rng, now=now)
    _links(opening, website, people)
    _files(opening, people)
    _expenses(company, opening, website, promo, owner, today=today)
    timer_card = Task.objects.filter(project=opening, title="Final electrical check").first()
    RunningTimer.objects.create(
        company=company,
        membership=people["worker"],
        task=timer_card,
        project=opening,
        started_at=now - timedelta(minutes=47),
    )
    for project in (opening, website, audit, promo):
        Project.objects.filter(pk=project.pk).update(
            health=queries.health_of(project, now=now) or ""
        )


def _project(company, people, *, members, labels, milestones, now, **fields) -> Project:
    project = Project.objects.create(
        company=company, created_by=people["owner"], budget_currency="UZS", **fields
    )
    Project.objects.filter(pk=project.pk).update(created_at=now - timedelta(days=45))
    names = ["Backlog", "To do", "In progress", "Review", "Done"]
    wip = {"In progress": 6, "Review": 3}
    for index, name in enumerate(names):
        ProjectList.objects.create(
            project=project,
            name=name,
            position=(index + 1) * 1024,
            is_done=name == "Done",
            wip_limit=wip.get(name),
        )
    ProjectMember.objects.create(
        project=project, membership=project.lead, role=ProjectMember.Role.LEAD
    )
    for key in members:
        if people[key].pk != project.lead_id:
            ProjectMember.objects.create(
                project=project, membership=people[key], role=ProjectMember.Role.MEMBER
            )
    for index, (name, color) in enumerate(labels):
        Label.objects.create(project=project, name=name, color=color, position=(index + 1) * 1024)
    today = timezone.localtime(now, ZoneInfo(company.timezone)).date()
    for index, (name, offset, done) in enumerate(milestones):
        Milestone.objects.create(
            project=project,
            name=name,
            due_on=today + timedelta(days=offset),
            status=Milestone.Status.DONE if done else Milestone.Status.OPEN,
            completed_at=now + timedelta(days=offset) if done else None,
            position=(index + 1) * 1024,
        )
    return project


def _audit_cards() -> list[tuple]:
    cards = [
        ("Agree the audit dates with the accountant", "jasur", DONE, ["Reconciliation"], -4, {}),
        ("Export the stock list from 1C", "madina", DONE, ["Reconciliation"], -2, {}),
        ("Print count sheets with barcodes", "jasur", DOING, ["Counting"], 6, {}),
        ("Borrow two scanners from the supplier", "manager", DOING, ["Warehouse"], 8, {}),
        ("Plan the night shifts for counting", "manager", TODO, ["Counting"], 9, {}),
        ("Freeze deliveries on count days", "jasur", TODO, ["Warehouse"], 12, {}),
        ("Brief the counting teams", "jasur", TODO, ["Counting"], 13, {}),
        ("Label every shelf with its location code", "worker", TODO, ["Warehouse"], 14, {}),
    ]
    people = ["worker", "jasur", "madina", "manager"]
    for index, area in enumerate(AUDIT_AREAS):
        cards.append(
            (
                f"Count {area}",
                people[index % len(people)],
                BACKLOG if index > 1 else TODO,
                ["Counting"],
                18 + index,
                {},
            )
        )
    cards += [
        ("Recount items with a difference over 2%", "jasur", BACKLOG, ["Counting"], 38, {}),
        ("Write off expired goods", "manager", BACKLOG, ["Reconciliation"], 40, {}),
        ("Post differences to the ledger", "madina", BACKLOG, ["Reconciliation"], 42, {}),
        ("Audit report for Dilnoza", "jasur", BACKLOG, ["Reconciliation"], 44, {}),
        ("Lessons learned for next year", "jasur", BACKLOG, [], 45, {}),
        ("Archive the count sheets", "madina", BACKLOG, [], 45, {}),
        ("Update minimum stock levels", "jasur", BACKLOG, ["Warehouse"], 45, {}),
        ("Thank-you lunch for the counters", "manager", BACKLOG, [], 45, {}),
    ]
    return cards


def _due(today: date, offset: int, tz: ZoneInfo, rng: random.Random) -> datetime:
    hour = rng.choice((10, 12, 15, 17, 18))
    return datetime.combine(today + timedelta(days=offset), time(hour, 0), tzinfo=tz)


def _cards(project: Project, people, rows, *, today, tz, now, rng, start: int) -> None:
    lists = {row.name: row for row in project.lists.all()}
    by_status = {
        BACKLOG: lists["Backlog"],
        TODO: lists["To do"],
        DOING: lists["In progress"],
        REVIEW: lists["Review"],
        DONE: lists["Done"],
    }
    labels = {label.name: label for label in project.labels.all()}
    milestones = list(project.milestones.order_by("due_on"))
    positions: dict[int, float] = {}
    for number, (title, who, column, label_names, offset, extra) in enumerate(rows, start=1):
        assignee = people[who]
        status = {
            DONE: Task.Status.DONE,
            REVIEW: Task.Status.REVIEW,
            DOING: Task.Status.IN_PROGRESS,
        }.get(column, Task.Status.TODO)
        due_at = _due(today, offset, tz, rng)
        project_list = by_status[column]
        positions[project_list.pk] = positions.get(project_list.pk, 0) + 1024
        created = now + timedelta(days=start + rng.randint(0, 4), hours=rng.randint(-3, 3))
        if created > due_at:
            created = due_at - timedelta(days=rng.randint(2, 6))
        milestone = next((m for m in milestones if m.due_on and m.due_on >= due_at.date()), None)
        task = Task.objects.create(
            company=project.company,
            kind=Task.Kind.ASSIGNED,
            title=title,
            description=extra.get("description", ""),
            assignee=assignee,
            created_by=project.lead,
            branch=assignee.home_branch,
            status=status,
            priority=Task.Priority.HIGH if "Urgent" in label_names else Task.Priority.NORMAL,
            due_at=due_at,
            proof=extra.get("proof", Proof.NONE),
            needs_confirmation=extra.get("needs_confirmation", False),
            started_at=created + timedelta(hours=2) if status != Task.Status.TODO else None,
            completed_at=(due_at - timedelta(hours=rng.randint(2, 30)))
            if status in (Task.Status.DONE, Task.Status.REVIEW)
            else None,
            confirmed_at=due_at - timedelta(hours=1)
            if status == Task.Status.DONE and extra.get("needs_confirmation")
            else None,
            project=project,
            project_list=project_list,
            milestone=milestone,
            list_position=positions[project_list.pk],
        )
        if task.completed_at and task.completed_at > now:
            Task.objects.filter(pk=task.pk).update(
                completed_at=now - timedelta(hours=rng.randint(1, 20))
            )
        Task.objects.filter(pk=task.pk).update(
            created_at=created, project_list=project_list, list_position=positions[project_list.pk]
        )
        start_on = (due_at - timedelta(days=rng.randint(2, 6))).date()
        Card.objects.update_or_create(
            task=task,
            defaults={
                "project": project,
                "number": number,
                "start_on": max(start_on, created.date()),
            },
        )
        TaskLabel.objects.bulk_create(
            TaskLabel(task=task, label=labels[name]) for name in label_names
        )
        for order, (text, done) in enumerate(extra.get("checklist", [])):
            ChecklistItem.objects.create(task=task, text=text, is_done=done, order=order)
        if extra.get("proof") == Proof.PHOTO and status in (Task.Status.REVIEW, Task.Status.DONE):
            _proof_photo(task)
        if column in (DOING, REVIEW) and rng.random() < 0.5:
            TaskComment.objects.create(task=task, author=project.lead, text=rng.choice(COMMENTS))


def _proof_photo(task: Task) -> None:
    """A tiled-floor picture as the card's proof photo."""
    from PIL import Image, ImageDraw

    from apps.core import uploads

    image = Image.new("RGB", (800, 600), (214, 205, 190))
    draw = ImageDraw.Draw(image)
    for x in range(0, 800, 100):
        for y in range(0, 600, 100):
            shade = 200 + ((x + y) // 100 % 2) * 25
            draw.rectangle((x + 3, y + 3, x + 97, y + 97), fill=(shade, shade - 8, shade - 22))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    clean = uploads.sanitize_image(buffer.getvalue())
    task.proof_photo.save(clean.name, clean, save=False)
    Task.objects.filter(pk=task.pk).update(proof_photo=task.proof_photo.name)


COMMENTS = [
    "How is it going? Need anything from me?",
    "Supplier confirmed delivery for Thursday.",
    "Please send a photo when it's done.",
    "Ok, I'll check it tomorrow morning.",
    "Ustalar said two more days.",
]


def _updates(opening, website, promo, people, now) -> None:
    rows = [
        (
            opening,
            people["manager"],
            "on_track",
            "Fit-out started on time. Shelving ordered, contractor on site every day.",
            20,
        ),
        (
            opening,
            people["manager"],
            "on_track",
            "Electrics and painting done. Air conditioners installed, internet is live.",
            9,
        ),
        (
            opening,
            people["manager"],
            "at_risk",
            "Floor tiles took three days longer than planned and the sign is still not up. "
            "Opening on Saturday is possible if the electrical check passes on Thursday.",
            1,
        ),
        (
            website,
            people["owner"],
            "on_track",
            "Design approved. Photographer booked for the remaining products.",
            12,
        ),
        (
            website,
            people["owner"],
            "on_track",
            "200 products uploaded, Click integration in testing. On track for launch.",
            2,
        ),
        (
            promo,
            people["owner"],
            "on_track",
            "Promo closed: school goods +18% vs last year, 14.2 mln spent of 15 mln.",
            30,
        ),
    ]
    for project, author, health, text, days_ago in rows:
        update = ProjectUpdate.objects.create(
            project=project, author=author, health=health, text=text
        )
        ProjectUpdate.objects.filter(pk=update.pk).update(
            created_at=now - timedelta(days=days_ago, hours=3)
        )


def _time(company, projects, people, *, today, rng, now) -> None:
    start = today - timedelta(days=today.weekday() + 7)  # last week's Monday
    work = {
        projects[0].pk: ["manager", "worker", "jasur", "madina", "nigora"],
        projects[1].pk: ["owner", "madina", "nigora"],
    }
    cards = {
        project.pk: list(Task.objects.filter(project=project).exclude(status=Task.Status.TODO))
        for project in projects
    }
    day = start
    while day <= today:
        if day.weekday() < 6:
            for project in projects:
                for who in work[project.pk]:
                    member = people[who]
                    options = [t for t in cards[project.pk] if t.assignee_id == member.pk] or cards[
                        project.pk
                    ]
                    for _ in range(rng.choice((1, 1, 2))):
                        task = rng.choice(options) if options else None
                        TimeEntry.objects.create(
                            company=company,
                            membership=member,
                            project=project,
                            task=task,
                            day=day,
                            minutes=rng.choice((45, 60, 90, 120, 150, 180)),
                            note=rng.choice(("", "", "On site", "Calls with suppliers", "Testing")),
                            source=rng.choice((TimeEntry.Source.MANUAL, TimeEntry.Source.TIMER)),
                            created_by=member,
                        )
        day += timedelta(days=1)


def _links(opening, website, people) -> None:
    for project, title, url, who in (
        (opening, "Floor plan (Figma)", "https://www.figma.com/file/chilonzor-fit-out", "manager"),
        (
            opening,
            "Lease contract (Google Drive)",
            "https://drive.google.com/drive/chilonzor-lease",
            "owner",
        ),
        (opening, "Contractor chat", "https://t.me/ustalar_group", "manager"),
        (website, "Staging site", "https://staging.demoshop.uz", "owner"),
        (website, "Design system (Figma)", "https://www.figma.com/file/demoshop-web", "nigora"),
    ):
        ProjectLink.objects.create(project=project, title=title, url=url, added_by=people[who])


def _files(opening, people) -> None:
    """A storefront mockup picture, drawn here (no files ship with the demo)."""
    from PIL import Image, ImageDraw

    from apps.core import uploads

    image = Image.new("RGB", (960, 600), (247, 243, 236))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 120, 880, 520), fill=(255, 255, 255), outline=(168, 90, 39), width=6)
    draw.rectangle((80, 120, 880, 200), fill=(168, 90, 39))
    draw.rectangle((180, 260, 420, 520), fill=(241, 235, 225), outline=(95, 122, 69), width=4)
    draw.rectangle((520, 260, 780, 420), fill=(241, 235, 225), outline=(74, 106, 138), width=4)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    clean = uploads.accept_document(ContentFile(buffer.getvalue()), allowed=("image",))
    row = ProjectFile(
        project=opening,
        name="Storefront mockup.jpg",
        kind="image",
        size=clean.size,
        uploaded_by=people["nigora"],
    )
    row.file.save(clean.name, clean, save=False)
    row.save()


def _expenses(company, opening, website, promo, owner, *, today: date) -> None:
    """Fund a project account from the owner, then book the projects' expenses on it."""
    from apps.finance import services as finance
    from apps.finance.models import Category, MoneyAccount

    if not Category.objects.filter(company=company, system_code="repairs").exists():
        return  # the finance defaults aren't there (finance switched off in this demo)
    account = MoneyAccount.objects.filter(company=company, name="Kapitalbank · projects").first()
    if account is None:
        account = finance.create_account(
            company, by=owner, kind="bank", name="Kapitalbank · projects"
        )
    finance.record_transaction(
        company,
        by=owner,
        kind="owner",
        amount=Decimal("160000000"),
        account=account,
        occurred_on=today - timedelta(days=80),
        description="Owner funding for the Chilonzor opening, the website and the promo",
    )
    rows = [
        (opening, "repairs", "18500000", -36, "Ustalar Group: demolition and partitions"),
        (opening, "repairs", "21400000", -25, "Ustalar Group: electrics and plastering"),
        (opening, "other_expense", "16800000", -24, "Mebel Lux: shelving and checkout counters"),
        (opening, "other_expense", "9600000", -15, "Two drink fridges and a freezer"),
        (opening, "other_expense", "4200000", -17, "POS terminals and receipt printers"),
        (opening, "marketing", "6900000", -14, "Reklama Pro: storefront sign"),
        (opening, "repairs", "5600000", -8, "Floor tiles and glue"),
        (opening, "utilities", "1150000", -5, "Uzonline fibre: connection and first month"),
        (opening, "marketing", "2250000", -3, "Opening flyers, 5 000 pcs"),
        (website, "other_expense", "6000000", -25, "Web studio: design stage"),
        (website, "other_expense", "1800000", -16, "Hosting and domain for a year"),
        (website, "marketing", "3200000", -12, "Product photography, day 1"),
        (website, "other_expense", "1600000", -6, "Payment gateway setup"),
        (promo, "marketing", "8400000", -64, "Posters, toppers and the display"),
        (promo, "marketing", "5800000", -55, "Instagram ads"),
    ]
    for project, code, amount, offset, description in rows:
        finance.record_transaction(
            company,
            by=owner,
            kind="expense",
            amount=Decimal(amount),
            account=account,
            category=code,
            occurred_on=today + timedelta(days=offset),
            description=description,
            project=project,
        )
