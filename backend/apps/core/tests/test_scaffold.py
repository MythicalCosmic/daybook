"""The Wave 0 skeleton every package builds on: apps, their files, hooks and URL mounts."""

import importlib
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.urls import URLResolver, get_resolver

from apps.core import appconfig

APPS_DIR = Path(__file__).resolve().parents[2]

NEW_APPS = (
    "console",
    "inbox",
    "exports",
    "signin",
    "finance",
    "sales",
    "inventory",
    "attendance",
    "hr",
    "payroll",
    "ai",
    "insights",
    "briefings",
    "recognition",
    "projects",
    "lifecycle",
    "knowledge",
    "agenda",
    "crm",
)
# Rule 2 of docs/PLAN-OWNER.md §2.3. finance/models.py comes with the finance core (W0-F).
RULE_2_FILES = (
    "models.py",
    "services.py",
    "queries.py",
    "api.py",
    "urls.py",
    "owner_api.py",
    "owner_urls.py",
    "admin.py",
    "hooks.py",
    "ai_tools.py",
    "defaults.py",
    "conf.py",
    "tasks.py",
    "beat.py",
    "audit_actions.py",
    "bot_messages.py",
    "callbacks.py",
    "demo.py",
    "schema_enums.py",
    "tests/__init__.py",
    "tests/factories.py",
    "migrations/__init__.py",
)
OWNER_URLS_OF_EXISTING_APPS = (
    "tasks",
    "reminders",
    "reports",
    "members",
    "companies",
    "timeoff",
    "announcements",
    "groups",
    "audit",
)


@pytest.mark.parametrize("label", NEW_APPS)
def test_new_apps_are_installed_with_every_file(label):
    assert django_apps.is_installed(f"apps.{label}")
    for name in RULE_2_FILES:
        if (label, name) == ("finance", "models.py"):
            continue
        assert (APPS_DIR / label / name).is_file(), f"apps/{label}/{name}"
        if name.endswith(".py") and not name.startswith("migrations/"):
            importlib.import_module(f"apps.{label}.{name.removesuffix('.py').replace('/', '.')}")


@pytest.mark.parametrize("label", NEW_APPS)
def test_new_apps_start_with_working_stubs(label):
    def module(name):
        return importlib.import_module(f"apps.{label}.{name}")

    assert isinstance(module("urls").urlpatterns, list)
    assert isinstance(module("owner_urls").urlpatterns, list)
    assert isinstance(module("beat").SCHEDULE, dict)
    assert isinstance(module("schema_enums").ENUM_NAME_OVERRIDES, dict)
    assert callable(module("defaults").ensure)
    assert callable(module("demo").seed)


def test_existing_apps_have_owner_urls():
    for label in OWNER_URLS_OF_EXISTING_APPS:
        assert isinstance(importlib.import_module(f"apps.{label}.owner_urls").urlpatterns, list)
    for label in ("announcements", "timeoff"):
        assert isinstance(importlib.import_module(f"apps.{label}.urls").urlpatterns, list)


def test_every_project_app_imports_its_hooks():
    for config in django_apps.get_app_configs():
        if config.name.startswith("apps."):
            assert isinstance(config, appconfig.AppConfig), config.name


def test_hooks_are_imported_when_present():
    assert appconfig.import_hooks("apps.sales") is True  # scaffolded hooks.py
    assert appconfig.import_hooks("apps.core.tests") is False  # a package without one


def mounted() -> dict[str, set[str]]:
    """Each included URL module (by name) -> the prefixes it's mounted at under /api/v1/."""
    found: dict[str, set[str]] = {}

    def walk(resolver, prefix):
        for pattern in resolver.url_patterns:
            if isinstance(pattern, URLResolver):
                route = prefix + str(pattern.pattern)
                module = pattern.urlconf_name
                if hasattr(module, "__name__"):
                    found.setdefault(module.__name__, set()).add(route)
                elif isinstance(module, str):
                    found.setdefault(module, set()).add(route)
                walk(pattern, route)

    walk(get_resolver(), "")
    return found


def test_every_urls_module_is_mounted():
    routes = mounted()
    for path in sorted(APPS_DIR.glob("*/urls.py")):
        assert routes.get(f"apps.{path.parent.name}.urls") == {
            "api/v1/companies/<int:company_id>/"
        }, path


def test_every_owner_urls_module_is_mounted():
    routes = mounted()
    special = {
        "apps.console.owner_urls": {"api/v1/owner/"},
        "apps.signin.owner_urls": {"api/v1/owner/auth/"},
    }
    for path in sorted(APPS_DIR.glob("*/owner_urls.py")):
        module = f"apps.{path.parent.name}.owner_urls"
        expected = special.get(module, {"api/v1/owner/companies/<int:company_id>/"})
        assert routes.get(module) == expected, module
    assert routes["apps.console.company_urls"] == {"api/v1/owner/companies/<int:company_id>/"}
    assert routes["apps.ai.stream_urls"] == {"api/v1/owner/ai/"}
