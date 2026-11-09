"""Face ID terminals from the command line, for platform support before (or besides) the
dashboard page:

    manage.py faceid_device add --company 3 --branch 7 --name "Kirish" [--direction toggle]
    manage.py faceid_device list --company 3
    manage.py faceid_device enable-module --company 3

`add` prints the terminal's id and the exact HTTP Listening values (host, HTTPS on 443 and the
plain-HTTP fallback, the URL with its code, the heartbeat); `enable-module` switches the
`face_id` module on through the same service as the dashboard (audited, defaults made).
"""

from datetime import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.attendance import clock
from apps.companies import services as companies
from apps.companies.models import Branch, Company, Feature
from apps.faceid import services
from apps.faceid.models import FaceDevice, FaceEvent


class Command(BaseCommand):
    help = "Add or list Face ID terminals, or switch the Face ID module on for a company."

    def add_arguments(self, parser):
        commands = parser.add_subparsers(dest="action", required=True)
        add = commands.add_parser("add", help="Add a terminal and print what to type into it.")
        add.add_argument("--company", type=int, required=True)
        add.add_argument("--branch", type=int, required=True)
        add.add_argument("--name", required=True)
        add.add_argument(
            "--direction", choices=FaceDevice.Direction.values, default=FaceDevice.Direction.TOGGLE
        )
        listing = commands.add_parser("list", help="The company's terminals.")
        listing.add_argument("--company", type=int, required=True)
        enable = commands.add_parser("enable-module", help="Switch the Face ID module on.")
        enable.add_argument("--company", type=int, required=True)

    def handle(self, *args, action, company, **options):
        found = Company.objects.filter(pk=company).first()
        if found is None:
            raise CommandError(f"No company {company}.")
        if action == "add":
            self.add(found, options["branch"], options["name"], options["direction"])
        elif action == "list":
            self.list(found)
        else:
            self.enable(found)

    def add(self, company, branch_id, name, direction):
        branch = Branch.objects.filter(company=company, pk=branch_id).first()
        if branch is None:
            raise CommandError(f"Company {company.pk} has no branch {branch_id}.")
        device = services.create_device(
            company, by=None, name=name, branch=branch, direction=direction
        )
        values = services.setup(device)
        write = self.stdout.write
        write(f"Terminal {device.pk}: {device.name} ({branch.name}, {device.direction})")
        write("")
        write("On the terminal: Configuration > Network > Advanced Settings > HTTP Listening")
        write(f"  Destination IP or host name: {values['host'] or '(set PUBLIC_DEVICE_HOST)'}")
        write(f"  Addressing:                  {values['addressing']}")
        write(f"  URL:                         {values['path']}")
        write("  Protocol and port:           HTTPS, 443")
        write(f"  Heartbeat:                   on, every {values['heartbeat_minutes']} minutes")
        write("")
        write(f"  HTTPS:                {values['https']['url']}")
        write(f"  Plain HTTP fallback:  {values['http']['url']}  (port 80)")
        if not company.has_feature(Feature.FACE_ID):
            write("")
            write(self.style.WARNING("Face ID is off for this company: run enable-module."))

    def list(self, company):
        start = clock.at(company, clock.today(company), time(0, 0))
        devices = FaceDevice.objects.filter(company=company).select_related("branch")
        if not devices:
            self.stdout.write("No terminals.")
            return
        for device in devices.order_by("pk"):
            today = FaceEvent.objects.filter(device=device, event_at__gte=start).count()
            seen = (
                clock.local(company, device.last_seen_at).strftime("%Y-%m-%d %H:%M")
                if device.last_seen_at
                else "never"
            )
            state = "on" if device.enabled else "off"
            self.stdout.write(
                f"{device.pk:>5}  {device.name:<24} {device.branch.name:<20} {state:<4} "
                f"last seen {seen:<17} scans today {today}"
            )

    def enable(self, company):
        if company.has_feature(Feature.FACE_ID):
            self.stdout.write(f"Face ID is already on for {company.name}.")
            return
        companies.set_features(company, by=None, features=[*company.features, Feature.FACE_ID])
        self.stdout.write(
            self.style.SUCCESS(f"Face ID is on for {company.name} ({timezone.now():%H:%M}).")
        )
