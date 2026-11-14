"""Create the branches Asosiy and G‘alaba and ask everyone in the employee bot to pick their
branch, department and job title again (apps.members.profile_fix).

The survey takes answers for `--days` days from now (14 by default; run it again to send
again and to keep it open longer), then the buttons of its messages say it is over.
`--close` ends it at once and sends nothing."""

import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.companies.models import Company
from apps.members import profile_fix
from apps.notifications.telegram import send_message, serialize_markup


class Command(BaseCommand):
    help = "Send the branch / department / job title survey to everyone in a company."

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--only", type=int, help="Send to this Telegram id only (a test).")
        parser.add_argument("--days", type=int, default=14, help="How long answers are taken.")
        parser.add_argument("--close", action="store_true", help="End the survey now.")

    def handle(self, *args, company, dry_run, only, days, close, **options):
        company = Company.objects.get(pk=company)
        if close:
            Company.objects.filter(pk=company.pk).update(profile_fix_until=None)
            self.stdout.write("the survey is closed")
            return
        if not dry_run:
            until = timezone.now() + timedelta(days=max(days, 1))
            Company.objects.filter(pk=company.pk).update(profile_fix_until=until)
            self.stdout.write(f"answers are taken until {until:%Y-%m-%d %H:%M} UTC")
        branches = profile_fix.ensure_branches(company)
        self.stdout.write(f"branches: {[b.name for b in branches]}")
        markup = serialize_markup(profile_fix.branch_keyboard(company))
        people = profile_fix.recipients(company)
        if only:
            people = [m for m in people if m.user.telegram_id == only]
        sent = failed = 0
        for member in people:
            if dry_run:
                self.stdout.write(f"would send to membership {member.pk}")
                continue
            try:
                send_message("employee", member.user.telegram_id, profile_fix.INTRO, markup)
                sent += 1
            except Exception as exc:  # blocked the bot, never started it
                failed += 1
                self.stdout.write(f"membership {member.pk}: {type(exc).__name__}")
            time.sleep(0.05)  # well under Telegram's 30 messages a second
        self.stdout.write(f"people: {len(people)} sent: {sent} failed: {failed}")
