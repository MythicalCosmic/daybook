"""`manage.py davomat_demo`: the example organization "Namuna MChJ" (apps/davomat/demo.py) for
screenshots and demos, in a Davomat install that has no organization yet.

    EDITION=davomat manage.py davomat_demo [--admin-username admin] [--admin-password …]
    EDITION=davomat manage.py davomat_demo --reset      # replace an earlier Namuna MChJ
    EDITION=davomat manage.py davomat_demo --reset --live   # then today's scans as they come
    EDITION=davomat manage.py davomat_demo --reset --scan-mode both   # departures too

`--reset` removes only the demo's own organization (by its name), never a real one. Its people
scan only when they come (Face ID's default); `--scan-mode both` has them scan when they leave too.
"""

import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from django.utils import translation

from apps.accounts.models import User
from apps.companies.models import Company
from apps.core import demo_time
from apps.davomat import conf, demo, queries
from apps.davomat.passwords import FieldError
from apps.faceid.models import FaceEvent, FaceIdSettings

PASSWORD_ENV = "DAVOMAT_ADMIN_PASSWORD"


class Command(BaseCommand):
    help = "Fill an empty Davomat install with the example organization Namuna MChJ."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", default="admin")
        parser.add_argument(
            "--admin-password", default="", help=f"Default {demo.PASSWORD} (or {PASSWORD_ENV})."
        )
        parser.add_argument(
            "--reset", action="store_true", help="Replace an earlier Namuna MChJ demo."
        )
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            choices=range(1, 31),
            metavar="1-30",
            help="Days of scans before today (default 30: a month for the reports).",
        )
        parser.add_argument(
            "--live",
            action="store_true",
            help="Then post today's scans still to come, each at its time (runs until the last).",
        )
        parser.add_argument(
            "--scan-mode",
            choices=FaceIdSettings.ScanMode.values,
            default=FaceIdSettings.ScanMode.ARRIVAL,
            help="How its people use the terminals: arrival (the default: only when they come) "
            "or both (when they leave too, from 18:00).",
        )

    def handle(
        self,
        *args,
        admin_username,
        admin_password,
        reset,
        live=False,
        days=30,
        scan_mode=FaceIdSettings.ScanMode.ARRIVAL,
        **options,
    ):
        if not conf.is_on():
            raise CommandError("Set EDITION=davomat first: this demo is the Davomat edition's.")
        password = admin_password or os.environ.get(PASSWORD_ENV, "") or demo.PASSWORD
        existing = Company.objects.order_by("pk").first()
        if existing is not None:
            if not reset:
                raise CommandError(
                    f"{existing.name} is set up already. Use --reset to replace the demo."
                )
            if not demo.is_demo(existing) or Company.objects.count() > 1:
                raise CommandError(f"{existing.name} isn't the demo: nothing was removed.")
        try:
            with transaction.atomic(), translation.override("uz"), demo_time.quiet():
                if existing is not None:
                    self._remove(existing)
                with demo_time.run_hooks():
                    built = demo.build(
                        username=admin_username,
                        password=password,
                        live=live,
                        days_back=days,
                        scan_mode=scan_mode,
                    )
        except FieldError as exc:
            raise CommandError(f"{exc.field}: {' '.join(exc.messages)}") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"{built.company.name}: "
                f"{queries.employees(built.company, branch_ids=None).count()} employees, "
                f"{len(built.devices)} terminals, {built.scans} scans "
                f"({FaceEvent.objects.filter(company=built.company).count()} kept)."
            )
        )
        self.stdout.write(f"Sign in as {built.owner.user.username} or nodira, password {password}")
        self.stdout.write(
            "People scan when they come and when they leave (--scan-mode both)."
            if built.scan_mode == FaceIdSettings.ScanMode.BOTH
            else "People scan only when they come (--scan-mode both for departures too)."
        )
        if live:
            self._say(f"Live: {len(built.pending)} scans still to come today, each at its time.")
            posted = demo.run_live(built, say=self._say)
            self._say(f"Live: the day is done ({posted} scans).")

    def _say(self, text: str) -> None:
        self.stdout.write(text)
        self.stdout.flush()

    def _remove(self, company: Company) -> None:
        """The demo organization with every row it has, and the accounts only it had."""
        from apps.core.management.commands.seed_demo import Command as SeedDemo

        people = list(
            User.objects.filter(memberships__company=company).values_list("pk", flat=True)
        )
        SeedDemo()._remove_company(company)
        User.objects.filter(pk__in=people).annotate(left=Count("memberships")).filter(
            left=0
        ).delete()
