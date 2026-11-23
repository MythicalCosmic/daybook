"""Ko‘z boxes from the command line, to pair one without the dashboard (docs/KOZ.md §6.8):

    manage.py vision_agent create --company 3 --branch 7 --name "Asosiy qutisi"
    manage.py vision_agent create --company 3 --branch Chilonzor --name "Asosiy qutisi"
    manage.py vision_agent pair --company 3 --box 4        (a new code for a box)
    manage.py vision_agent list --company 3

`create` and `pair` print the pairing code (valid 15 minutes, shown once) and the line to run on
the box's PC. Ko‘z must be on for the company (`--enable` switches it on, audited, through the
same service as the dashboard).
"""

from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from apps.attendance import clock
from apps.companies import services as companies
from apps.companies.models import Branch, Company, Feature
from apps.vision import conf, live, services
from apps.vision.models import Agent


def origin() -> str:
    base = settings.DASHBOARD_URL
    if not base:
        return "https://<daybook>"
    parts = urlsplit(base)
    return f"{parts.scheme}://{parts.netloc}"


class Command(BaseCommand):
    help = "Add a Ko‘z box and print its pairing code, give a box a new code, or list the boxes."

    def add_arguments(self, parser):
        commands = parser.add_subparsers(dest="action", required=True)
        create = commands.add_parser("create", help="Add a box and print its pairing code.")
        create.add_argument("--company", type=int, required=True)
        create.add_argument("--branch", required=True, help="The branch's id or its name.")
        create.add_argument("--name", required=True)
        create.add_argument("--enable", action="store_true", help="Switch Ko‘z on if it's off.")
        again = commands.add_parser("pair", help="A new pairing code for a box.")
        again.add_argument("--company", type=int, required=True)
        again.add_argument("--box", type=int, required=True)
        listing = commands.add_parser("list", help="The company's boxes.")
        listing.add_argument("--company", type=int, required=True)

    def handle(self, *args, action, company, **options):
        found = Company.objects.filter(pk=company).first()
        if found is None:
            raise CommandError(f"No company {company}.")
        if action == "list":
            self.list(found)
            return
        if not conf.is_on(found):
            if not options.get("enable"):
                raise CommandError(f"Ko‘z is off for {found.name}: add --enable to switch it on.")
            companies.set_features(found, by=None, features=[*found.features, Feature.VISION])
        if action == "create":
            branch = self.branch(found, options["branch"])
            agent, code = services.create_agent(found, by=None, name=options["name"], branch=branch)
        else:
            agent = Agent.objects.filter(
                company=found, pk=options["box"], removed_at__isnull=True
            ).first()
            if agent is None:
                raise CommandError(f"{found.name} has no box {options['box']}.")
            code = services.new_pairing(agent, by=None)
        expires = clock.local(found, code.expires_at).strftime("%H:%M")
        self.stdout.write(f"Box {agent.pk}: {agent.name} ({agent.branch.name})")
        self.stdout.write(f"Pairing code: {code.code} (valid until {expires}, once)")
        self.stdout.write(f"On the box's PC: koz-agent pair {origin()} {code.code}")

    def branch(self, company: Company, value: str) -> Branch:
        branches = Branch.objects.filter(company=company)
        found = branches.filter(pk=int(value)).first() if value.isdigit() else None
        found = found or branches.filter(name__iexact=value.strip()).first()
        if found is None:
            raise CommandError(f"{company.name} has no branch {value!r}.")
        return found

    def list(self, company: Company):
        boxes = (
            Agent.objects.filter(company=company)
            .select_related("branch")
            .annotate(camera_count=Count("cameras"))
            .order_by("pk")
        )
        if not boxes:
            self.stdout.write("No boxes.")
            return
        for agent in boxes:
            if agent.removed_at:
                state = "removed"
            elif not agent.paired:
                state = "waiting for its code"
            else:
                state = "online" if live.agent_report(agent.pk) or agent.demo else "offline"
            seen = (
                clock.local(company, agent.last_seen_at).strftime("%Y-%m-%d %H:%M")
                if agent.last_seen_at
                else "never"
            )
            self.stdout.write(
                f"{agent.pk:>5}  {agent.name:<24} {agent.branch.name:<20} {state:<20} "
                f"last seen {seen:<17} cameras {agent.camera_count}  {agent.version}"
            )
