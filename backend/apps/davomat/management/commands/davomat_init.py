"""`manage.py davomat_init`: the first-run setup from the shell (the installer, tests), exactly
as the setup page does it (docs/DAVOMAT.md §1.1). Refuses when an organization exists.

    manage.py davomat_init --organization "Namuna MChJ" --admin-username admin \\
        --admin-password '…' [--timezone Asia/Tashkent] [--language uz] \\
        [--admin-first-name Aziza] [--admin-last-name Karimova]

The password may come from the environment instead (DAVOMAT_ADMIN_PASSWORD), so it never shows
in the list of running processes.
"""

import os

from django.core.management.base import BaseCommand, CommandError

from apps.core.exceptions import DomainError
from apps.davomat import services
from apps.davomat.passwords import FieldError

PASSWORD_ENV = "DAVOMAT_ADMIN_PASSWORD"


class Command(BaseCommand):
    help = "Set up the Davomat organization and its owner (once)."

    def add_arguments(self, parser):
        parser.add_argument("--organization", required=True, help="The organization's name.")
        parser.add_argument("--admin-username", required=True)
        parser.add_argument(
            "--admin-password", default="", help=f"Or set {PASSWORD_ENV} in the environment."
        )
        parser.add_argument("--admin-first-name", default="")
        parser.add_argument("--admin-last-name", default="")
        parser.add_argument("--timezone", default="Asia/Tashkent")
        parser.add_argument("--language", default="uz", choices=("uz", "ru", "en"))

    def handle(self, *args, **options):
        password = options["admin_password"] or os.environ.get(PASSWORD_ENV, "")
        if not password:
            raise CommandError(f"Give --admin-password or set {PASSWORD_ENV}.")
        try:
            owner = services.setup_organization(
                name=options["organization"],
                timezone=options["timezone"],
                language=options["language"],
                admin={
                    "username": options["admin_username"],
                    "password": password,
                    "first_name": options["admin_first_name"],
                    "last_name": options["admin_last_name"],
                },
            )
        except FieldError as exc:
            raise CommandError(f"{exc.field}: {' '.join(exc.messages)}") from exc
        except DomainError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"{owner.company.name} is set up (company {owner.company.pk}); "
                f"{owner.user.username} can sign in."
            )
        )
