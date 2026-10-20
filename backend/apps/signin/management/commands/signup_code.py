"""Make a signup code for someone who will create a company in the owner bot.

    manage.py signup_code --uses 1 --days 14 --note "Malika, Chorsu bakery"

Prints the code and the owner bot link that fills it in (`/start new_<code>`). The code is
shown only here; the database keeps its hash.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.exceptions import DomainError
from apps.signin import signup


class Command(BaseCommand):
    help = "Create a signup code for /new in the owner bot (COMPANY_SIGNUP=code)."

    def add_arguments(self, parser):
        parser.add_argument("--uses", type=int, default=1, help="How many companies it creates.")
        parser.add_argument("--days", type=int, default=0, help="Valid for this many days.")
        parser.add_argument("--note", default="", help="Who it is for (shown in the admin).")

    def handle(self, *args, uses=1, days=0, note="", **options):
        expires_at = timezone.now() + timedelta(days=days) if days > 0 else None
        try:
            _code, raw = signup.create_code(uses=uses, expires_at=expires_at, note=note)
        except DomainError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(raw)
        username = settings.OWNER_BOT_USERNAME or settings.EMPLOYEE_BOT_USERNAME
        if username:
            self.stdout.write(f"https://t.me/{username}?start=new_{signup.normalize(raw)}")
