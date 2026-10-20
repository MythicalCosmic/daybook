"""The bridges to `apps.audit.registry` and `apps.core.files` (written by W0-L2)."""

from types import ModuleType

from apps.console import compat


def fake(name: str, **functions) -> ModuleType:
    module = ModuleType(name)
    for attr, value in functions.items():
        setattr(module, attr, value)
    return module


def test_registrations_go_through_when_the_module_exists(monkeypatch):
    calls = []
    monkeypatch.setattr(
        compat,
        "audit_registry",
        lambda: fake("apps.audit.registry", register=lambda actions: calls.append(actions)),
    )
    monkeypatch.setattr(
        compat,
        "files",
        lambda: fake(
            "apps.core.files", register_file_check=lambda kind, check: calls.append((kind, check))
        ),
    )

    assert compat.register_audit_actions("ACTIONS") is True
    assert compat.register_file_check("exports.export", len) is True
    assert calls == ["ACTIONS", ("exports.export", len)]


def test_without_the_modules_nothing_breaks(monkeypatch):
    monkeypatch.setattr(compat, "audit_registry", lambda: None)
    monkeypatch.setattr(compat, "files", lambda: None)

    assert compat.register_audit_actions("ACTIONS") is False
    assert compat.register_file_check("exports.export", len) is False
    assert compat.signed_url("exports/1/a.csv", user=None, company_id=1, check="x:1") is None


def test_signed_url_passes_everything_on(monkeypatch):
    def signed_url(file, *, user, company_id, check, ttl):
        return f"/api/v1/files/{file}|{user}|{company_id}|{check}|{ttl}/"

    monkeypatch.setattr(compat, "files", lambda: fake("apps.core.files", signed_url=signed_url))

    assert compat.signed_url("f", user="u", company_id=3, check="hr.document:12", ttl=60) == (
        "/api/v1/files/f|u|3|hr.document:12|60/"
    )
    assert compat.signed_url("", user="u", company_id=3, check="x:1") is None
    # A module without `filename` still works; the name is simply not passed on.
    assert compat.signed_url("f", user="u", company_id=3, check="x:1", filename="a.csv") == (
        "/api/v1/files/f|u|3|x:1|600/"
    )


def test_signed_url_passes_the_download_name_when_the_module_takes_it(monkeypatch):
    def signed_url(file, *, user, company_id, check, ttl, filename=None):
        return f"/api/v1/files/{file}|{filename}/"

    monkeypatch.setattr(compat, "files", lambda: fake("apps.core.files", signed_url=signed_url))

    assert compat.signed_url("f", user="u", company_id=3, check="x:1", filename="a.csv") == (
        "/api/v1/files/f|a.csv/"
    )
    assert compat.signed_url("f", user="u", company_id=3, check="x:1") == "/api/v1/files/f|None/"


def test_a_missing_module_is_detected():
    assert compat._module("apps.console.no_such_module") is None
    assert compat._module("apps.console.compat") is compat
