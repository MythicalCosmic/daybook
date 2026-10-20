from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.companies.tests.factories import CompanyFactory
from apps.core.management.commands.ensure_company_defaults import (
    default_providers,
    ensure_company_defaults,
)
from apps.members.models import Position

pytestmark = pytest.mark.django_db


def run(*args) -> str:
    out = StringIO()
    call_command("ensure_company_defaults", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def ensured(monkeypatch):
    """Replaces two apps' defaults.ensure with recorders."""
    calls = []
    for label in ("finance", "sales"):

        def ensure(company, label=label):
            calls.append((label, company.slug))

        monkeypatch.setattr(f"apps.{label}.defaults.ensure", ensure)
    return calls


def test_providers_follow_installed_apps_order():
    labels = [label for label, _ensure in default_providers()]

    assert {"finance", "sales", "payroll", "attendance"} <= set(labels)
    assert labels.index("finance") < labels.index("sales")
    assert all(callable(ensure) for _label, ensure in default_providers())
    assert [label for label, _ensure in default_providers(["sales"])] == ["sales"]


def test_unknown_apps_are_refused():
    with pytest.raises(CommandError, match="nope"):
        default_providers(["sales", "nope"])
    with pytest.raises(CommandError, match="nope"):
        run("--only", "nope")


def test_every_company_gets_every_apps_defaults(ensured):
    first, second = CompanyFactory(slug="first"), CompanyFactory(slug="second")

    output = run()

    for company in (first, second):
        assert ("finance", company.slug) in ensured
        assert ("sales", company.slug) in ensured
    assert "Defaults checked for 2 companies" in output


def test_companies_and_apps_can_be_narrowed(ensured):
    CompanyFactory(slug="first")
    second = CompanyFactory(slug="second")

    run("--company", "first", "--company", str(second.pk), "--only", "sales")
    assert sorted(ensured) == [("sales", "first"), ("sales", "second")]

    ensured.clear()
    run("--company", "second", "--only", "finance,sales")
    assert ensured == [("finance", "second"), ("sales", "second")]

    with pytest.raises(CommandError, match="No company"):
        run("--company", "missing")


def test_one_broken_company_doesnt_stop_the_others(monkeypatch):
    broken, fine = CompanyFactory(slug="broken"), CompanyFactory(slug="fine")

    def ensure(company):
        Position.objects.create(company=company, name="Made by defaults")
        if company == broken:
            raise RuntimeError("boom")

    monkeypatch.setattr("apps.sales.defaults.ensure", ensure)

    with pytest.raises(CommandError, match="broken"):
        run("--only", "sales")

    # The broken company's rows were rolled back; the other company kept its own.
    assert not Position.objects.filter(company=broken).exists()
    assert Position.objects.filter(company=fine, name="Made by defaults").exists()


def test_the_function_returns_the_apps_it_ran(ensured):
    company = CompanyFactory(slug="solo")

    assert ensure_company_defaults(company, only=["finance", "sales"]) == ["finance", "sales"]
    assert ensured == [("finance", "solo"), ("sales", "solo")]
