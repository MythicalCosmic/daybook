"""Create the branches Asosiy and G‘alaba and ask everyone in the employee bot to pick their
branch, department and job title again (apps.members.profile_fix)."""

import time

from django.core.management.base import BaseCommand

from apps.companies.models import Company
from apps.members import profile_fix
from apps.notifications.telegram import send_message, serialize_markup


class Command(BaseCommand):
    help = "Send the branch / department / job title survey to everyone in a company."

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--only", type=int, help="Send to this Telegram id only (a test).")

    def handle(self, *args, company, dry_run, only, **options):
        company = Company.objects.get(pk=company)
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
