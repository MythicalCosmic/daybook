"""The companies' Face ID bots (`apps.faceid.bot`): answers /start in each one and marks the
person as started, so Face ID's messages can reach them.

    manage.py faceid_bot              # forever, a round over every bot every --interval seconds
    manage.py faceid_bot --once       # one round (support, tests)

Every round reads the tokens again, so a bot connected, changed or removed in the dashboard is
picked up without a restart. Runs as its own service (`faceid_bot` in docker-compose.prod.yml);
with no company bot it just idles.
"""

import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.faceid import bot

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Answer /start in every company's Face ID bot."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One round, then exit.")
        parser.add_argument("--interval", type=float, default=3.0, help="Seconds between rounds.")

    def handle(self, *args, once=False, interval=3.0, **options):
        if once:
            answered = bot.poll_once()
            self.stdout.write(f"Answered {answered} /start.")
            return
        stopping = False

        def stop(*_):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        self.stdout.write("Face ID bots: polling.")
        while not stopping:
            close_old_connections()
            try:
                bot.poll_once()
            except Exception:  # A bad round never stops the service.
                logger.exception("Face ID bots: round failed")
            slept = 0.0
            while slept < interval and not stopping:
                time.sleep(0.5)
                slept += 0.5
