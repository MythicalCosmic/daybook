"""Face ID terminals from the command line, for platform support before (or besides) the
dashboard page:

    manage.py faceid_device add --company 3 --branch 7 --name "Kirish" [--direction toggle]
    manage.py faceid_device add --company 3 --branch Asosiy --name "Kirish"   (a branch by name)
    manage.py faceid_device list --company 3
    manage.py faceid_device enable-module --company 3
    manage.py faceid_device purge --company 3 [--before 2026-11-09T16:30] [--dry-run]

`add` prints the terminal's id and the exact HTTP Listening values (host, HTTPS on 443 and the
plain-HTTP fallback, the URL with its code, the heartbeat); `enable-module` switches the
`face_id` module on through the same service as the dashboard (audited, defaults made);
`purge` deletes the company's scans received before a time (default now), their snapshots and
the Face ID notifications about them: the cleanup after a terminal's history was taken for live
scans. Attendance records the scans made stay (correct them on the timesheet).
"""

from datetime import datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.attendance import clock
from apps.companies import services as companies
from apps.companies.models import Branch, Company, Feature
from apps.console import pulse
from apps.faceid import services
from apps.faceid.models import FaceDevice, FaceEvent
from apps.inbox.models import Notification
from apps.inbox.services import UNREAD_PULSE


class Command(BaseCommand):
    help = "Add or list Face ID terminals, switch the module on, or delete a company's scans."

    def add_arguments(self, parser):
        commands = parser.add_subparsers(dest="action", required=True)
        add = commands.add_parser("add", help="Add a terminal and print what to type into it.")
        add.add_argument("--company", type=int, required=True)
        add.add_argument("--branch", required=True, help="The branch's id or its name.")
        add.add_argument("--name", required=True)
        add.add_argument(
            "--direction", choices=FaceDevice.Direction.values, default=FaceDevice.Direction.TOGGLE
        )
        listing = commands.add_parser("list", help="The company's terminals.")
        listing.add_argument("--company", type=int, required=True)
        enable = commands.add_parser("enable-module", help="Switch the Face ID module on.")
        enable.add_argument("--company", type=int, required=True)
        purge = commands.add_parser(
            "purge", help="Delete the company's scans (snapshots and notices too) received before."
        )
        purge.add_argument("--company", type=int, required=True)
        purge.add_argument("--before", help="ISO date and time (default: now).")
        purge.add_argument("--dry-run", action="store_true", help="Only count what would go.")

    def handle(self, *args, action, company, **options):
        found = Company.objects.filter(pk=company).first()
        if found is None:
            raise CommandError(f"No company {company}.")
        if action == "add":
            self.add(found, options["branch"], options["name"], options["direction"])
        elif action == "list":
            self.list(found)
        elif action == "purge":
            self.purge(found, options.get("before"), dry_run=options.get("dry_run", False))
        else:
            self.enable(found)

    def purge(self, company, before: str | None, *, dry_run: bool = False):
        """Scans received before `before`, their snapshots, and the Face ID notifications about
        them (who came, unknown faces, numbers), for cleaning up after a bad import. A time
        without an offset is the company's local time."""
        if before:
            try:
                moment = datetime.fromisoformat(before)
            except ValueError as exc:
                raise CommandError("Give --before as an ISO date and time.") from exc
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=clock.zone(company))
        else:
            moment = timezone.now()
        events = FaceEvent.objects.filter(company=company, received_at__lt=moment)
        # A subquery, not a list: a history purge is tens of thousands of scans.
        notices = Notification.objects.filter(
            company=company,
            kind__startswith="faceid.",
            target_type="faceevent",
            target_id__in=events.values("pk"),
        )
        photos = list(events.exclude(photo="").values_list("photo", flat=True))
        records = sorted(set(events.exclude(record_id=None).values_list("record_id", flat=True)))
        when = f"received before {clock.local(company, moment):%Y-%m-%d %H:%M} ({company.name})"
        if dry_run:
            self.stdout.write(
                f"Would delete {events.count()} scans, {len(photos)} snapshots and "
                f"{notices.count()} notifications, {when}."
            )
        else:
            with transaction.atomic():
                notified = notices.delete()[0]
                deleted = events.delete()[1].get(FaceEvent._meta.label, 0)
            storage = FaceEvent._meta.get_field("photo").storage
            for name in photos:
                storage.delete(name)
            pulse.bump(company.pk, services.PULSE_FEED, services.PULSE_UNLINKED, UNREAD_PULSE)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {deleted} scans, {len(photos)} snapshots and {notified} "
                    f"notifications, {when}."
                )
            )
        if records:
            shown = ", ".join(str(pk) for pk in records[:50])
            more = f" and {len(records) - 50} more" if len(records) > 50 else ""
            self.stdout.write(
                f"Attendance records those scans made or changed (kept: check them on the "
                f"timesheet): {len(records)}: {shown}{more}."
            )

    def add(self, company, branch_ref, name, direction):
        branches = Branch.objects.filter(company=company)
        ref = str(branch_ref).strip()
        if ref.isdigit():
            branch = branches.filter(pk=int(ref)).first()
        else:
            named = list(branches.filter(name__iexact=ref)[:2])
            branch = named[0] if len(named) == 1 else None
        if branch is None:
            known = ", ".join(f"{row.pk} {row.name}" for row in branches.order_by("pk"))
            raise CommandError(
                f"Company {company.pk} has no branch {ref!r} (one by that id or name). "
                f"Its branches: {known or 'none'}."
            )
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
            history = ""
            if device.history_skipped:
                newest = (
                    clock.local(company, device.history_until).strftime("%Y-%m-%d %H:%M")
                    if device.history_until
                    else "?"
                )
                coming = ", still coming" if services.history_active(device) else ""
                history = f"  old history skipped {device.history_skipped} (to {newest}{coming})"
            self.stdout.write(
                f"{device.pk:>5}  {device.name:<24} {device.branch.name:<20} {state:<4} "
                f"last seen {seen:<17} scans today {today}{history}"
            )

    def enable(self, company):
        if company.has_feature(Feature.FACE_ID):
            self.stdout.write(f"Face ID is already on for {company.name}.")
            return
        companies.set_features(company, by=None, features=[*company.features, Feature.FACE_ID])
        self.stdout.write(
            self.style.SUCCESS(f"Face ID is on for {company.name} ({timezone.now():%H:%M}).")
        )
