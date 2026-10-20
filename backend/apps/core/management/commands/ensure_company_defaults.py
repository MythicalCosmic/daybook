"""Create every module's missing default rows for every company.

Each app with defaults has `apps/<app>/defaults.py: ensure(company)`, idempotent (payment
methods, leave types, finance categories…). New companies get them from each app's
`company_created` receiver; this command covers the companies that existed before an app was
deployed, and runs after `migrate` whenever the backend container starts. `seed_demo` runs it too.
"""

import importlib
import importlib.util
import logging
from collections.abc import Callable, Iterable

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.companies.models import Company

logger = logging.getLogger(__name__)

Ensure = Callable[[Company], None]


def default_providers(only: Iterable[str] | None = None) -> list[tuple[str, Ensure]]:
    """`(app label, ensure)` for every project app with a `defaults.ensure`, in INSTALLED_APPS
    order (so finance's categories exist before the modules that book into them).

    `only` limits it to those app labels; an unknown label raises `CommandError`.
    """
    configs = [c for c in django_apps.get_app_configs() if c.name.startswith("apps.")]
    wanted = None if only is None else set(only)
    if wanted is not None and (unknown := wanted - {c.label for c in configs}):
        raise CommandError(f"Unknown apps: {', '.join(sorted(unknown))}.")
    providers = []
    for config in configs:
        if wanted is not None and config.label not in wanted:
            continue
        name = f"{config.name}.defaults"
        if importlib.util.find_spec(name) is None:
            continue
        ensure = getattr(importlib.import_module(name), "ensure", None)
        if callable(ensure):
            providers.append((config.label, ensure))
    return providers


def ensure_company_defaults(company: Company, *, only: Iterable[str] | None = None) -> list[str]:
    """Run every app's `defaults.ensure(company)` in one transaction; returns the app labels."""
    providers = default_providers(only)
    with transaction.atomic():
        for _label, ensure in providers:
            ensure(company)
    return [label for label, _ensure in providers]


class Command(BaseCommand):
    help = "Create every module's missing default rows for every company (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            action="append",
            default=[],
            metavar="ID_OR_SLUG",
            help="Only this company (repeat for more).",
        )
        parser.add_argument(
            "--only", default="", metavar="APPS", help="Only these apps, e.g. sales,finance."
        )

    def handle(self, *args, company=(), only="", **options):
        apps = [label.strip() for label in only.split(",") if label.strip()] or None
        labels = [label for label, _ensure in default_providers(apps)]
        failed = []
        companies = self._companies(company)
        for each in companies:
            try:
                ensure_company_defaults(each, only=apps)
            except Exception:
                # One broken company must not keep the others from getting their rows.
                logger.exception("Defaults failed for company %s (%s)", each.pk, each.slug)
                failed.append(each.slug)
        if failed:
            raise CommandError(f"Defaults failed for: {', '.join(failed)}. See the log above.")
        self.stdout.write(
            self.style.SUCCESS(
                f"Defaults checked for {len(companies)} companies "
                f"({', '.join(labels) or 'no app has defaults yet'})."
            )
        )

    def _companies(self, wanted: list[str]) -> list[Company]:
        companies = Company.objects.order_by("pk")
        if not wanted:
            return list(companies)
        found = []
        for key in wanted:
            lookup = {"pk": int(key)} if key.isdigit() else {"slug": key}
            match = companies.filter(**lookup).first()
            if match is None:
                raise CommandError(f"No company {key!r}.")
            found.append(match)
        return found
