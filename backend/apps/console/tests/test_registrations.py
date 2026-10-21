"""What the apps really register (test_registry.py runs every registry empty instead)."""

from django.apps import apps as django_apps

from apps.console import registry


def test_every_registered_key_carries_its_apps_label():
    labels = {config.label for config in django_apps.get_app_configs()}
    for each in registry.REGISTRIES:
        for entry in each:
            assert entry.app in labels, f"{each.name}: {entry.key!r} has no app"
            assert registry.key_belongs_to(entry.key, entry.app), (
                f"{each.name}: {entry.key!r} doesn't start with {entry.app!r}"
            )


def test_a_test_that_empties_a_registry_gets_the_apps_entries_back():
    real = {each.name: each.keys() for each in registry.REGISTRIES}
    assert "companies.branches" in real["setup steps"]

    with registry.SETUP_STEPS.isolated(empty=True, keep=["companies.branches"]):
        assert registry.SETUP_STEPS.keys() == ["companies.branches"]

    assert {each.name: each.keys() for each in registry.REGISTRIES} == real
