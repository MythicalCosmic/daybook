"""Notification kinds and action handlers: the registry rules."""

import pytest

from apps.console.registry import BadKey, DuplicateKey, RegistryError
from apps.inbox import registry
from apps.inbox.registry import register_action, register_kind

pytestmark = pytest.mark.usefixtures("isolated_registries")


def handler(notification, by, reason):
    return None


def test_a_kind_is_registered_with_its_defaults():
    register_kind("inbox.thing", label="Thing", audience="owner", default_telegram=True)

    kind = registry.get_kind("inbox.thing")
    assert (kind.app, kind.audience, kind.severity, kind.queue_kind) == (
        "inbox",
        "owner",
        "info",
        None,
    )


def test_kinds_are_unique_and_app_prefixed():
    register_kind("inbox.thing", label="Thing", audience="owner", default_telegram=True)

    with pytest.raises(DuplicateKey):
        register_kind("inbox.thing", label="Again", audience="owner", default_telegram=True)
    with pytest.raises(BadKey):
        register_kind("sales.thing", label="Other app", audience="owner", default_telegram=True)


def test_audience_and_severity_are_checked():
    with pytest.raises(RegistryError):
        register_kind("inbox.a", label="A", audience="everyone", default_telegram=True)
    with pytest.raises(RegistryError):
        register_kind(
            "inbox.b", label="B", audience="owner", default_telegram=True, severity="huge"
        )


def test_an_action_needs_its_kind_first():
    with pytest.raises(RegistryError, match="register the kind"):
        register_action("inbox.nothing", "approve", handler)


def test_action_keys_are_short_and_simple():
    register_kind("inbox.thing", label="Thing", audience="owner", default_telegram=True)

    for key in ("Approve", "do it", "x" * 33, "1st"):
        with pytest.raises(RegistryError):
            register_action("inbox.thing", key, handler)


def test_an_action_is_registered_once():
    register_kind("inbox.thing", label="Thing", audience="owner", default_telegram=True)
    register_action("inbox.thing", "approve", handler)

    assert registry.get_handler("inbox.thing", "approve") is handler
    assert registry.get_handler("inbox.thing", "reject") is None
    with pytest.raises(DuplicateKey):
        register_action("inbox.thing", "approve", handler)


def test_an_unknown_kind_is_a_lookup_error():
    with pytest.raises(LookupError, match=r"register it in hooks\.py"):
        registry.get_kind("inbox.missing")
