import json

import pytest

from apps.audit import redaction, registry
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.audit.queries import events
from apps.audit.redaction import SECRET, Redacted
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db


@pytest.fixture
def sensitive(monkeypatch):
    """Membership's names stand in for secret and payroll-only fields in these tests."""
    monkeypatch.setitem(
        redaction._registry,
        "members.membership",
        {"last_name": SECRET, "first_name": Perm.PAYROLL_VIEW, "position": Perm.HR_SENSITIVE},
    )


@pytest.fixture
def worker(company, member):
    return member.registered(company, first_name="Aziz", last_name="Karimov")


def test_the_original_actions_are_registered_with_their_labels():
    assert registry.label("member.approved") == "Approved a join request"
    assert registry.codes()["task.assigned"] == "Gave a task"
    assert registry.label("nobody.registered.this") == "nobody.registered.this"


def test_registering_a_code_twice_raises(monkeypatch):
    monkeypatch.setattr(registry, "_labels", {})
    registry.register({"thing.done": "Did the thing"})

    with pytest.raises(registry.DuplicateAction):
        registry.register({"thing.done": "Again"})
    with pytest.raises(ValueError):
        registry.register({"x" * 49: "Too long"})
    assert AuditLog(action="thing.done").action_label == "Did the thing"


def test_secret_values_never_reach_a_snapshot_or_a_diff(sensitive, worker):
    before = audit.snapshot(worker)
    worker.last_name = "Toshmatov"
    worker.save()
    after = audit.snapshot(worker)

    changes = audit.diff(before, after)

    assert json.loads(json.dumps(before))["last_name"] == "•••"
    assert json.loads(json.dumps(changes)) == {"last_name": ["•••", "•••"]}
    assert "Karimov" not in json.dumps(before) and "Toshmatov" not in json.dumps(changes)


def test_nested_secrets_are_masked_too(sensitive, worker):
    row = audit.record(
        "member.changed",
        company_id=worker.company_id,
        actor=None,
        target=worker,
        before={"last_name": "Karimov", "status": "approved"},
        rows=[{"id": 1, "last_name": "Karimov"}, {"id": 2, "last_name": ""}],
        fields=["last_name"],
    )

    row.refresh_from_db()
    assert row.details == {
        "before": {"last_name": "•••", "status": "approved"},
        "rows": [{"id": 1, "last_name": "•••"}, {"id": 2, "last_name": ""}],
        "fields": ["last_name"],
    }
    assert "Karimov" not in json.dumps(row.details)


def test_an_unchanged_secret_is_not_reported_as_changed(sensitive, worker):
    assert audit.diff(audit.snapshot(worker), audit.snapshot(worker)) == {}


def test_record_masks_secret_values_however_they_arrive(sensitive, worker):
    row = audit.record(
        "member.changed",
        company_id=worker.company_id,
        actor=None,
        target=worker,
        last_name="Karimov",
        changes={"last_name": ["Karimov", "Toshmatov"], "status": ["approved", "left"]},
    )

    row.refresh_from_db()
    assert row.details == {
        "last_name": "•••",
        "changes": {"last_name": ["•••", "•••"], "status": ["approved", "left"]},
    }
    assert "Karimov" not in json.dumps(row.details)
    assert row.required_perm == ""  # a secret is hidden, not permission-gated


def test_record_stamps_the_strictest_permission_of_the_touched_fields(sensitive, worker):
    payroll = audit.record(
        "member.changed",
        company_id=worker.company_id,
        actor=None,
        target=worker,
        changes={"first_name": ["A", "B"]},
    )
    both = audit.record(
        "member.changed",
        company_id=worker.company_id,
        actor=None,
        target=worker,
        changes={"first_name": ["A", "B"]},
        fields=["position"],
    )
    plain = audit.record(
        "member.changed",
        company_id=worker.company_id,
        actor=None,
        target=worker,
        changes={"status": ["a", "b"]},
    )

    assert payroll.required_perm == Perm.PAYROLL_VIEW
    assert both.required_perm == Perm.HR_SENSITIVE  # held by owners only: stricter
    assert plain.required_perm == ""


def test_an_explicit_permission_is_kept_unless_a_field_needs_a_stricter_one(sensitive, worker):
    explicit = audit.record(
        "member.changed",
        company_id=worker.company_id,
        actor=None,
        target=worker,
        required_perm=Perm.HR_VIEW,
    )
    stricter = audit.record(
        "member.changed",
        company_id=worker.company_id,
        actor=None,
        target=worker,
        required_perm=Perm.HR_VIEW,
        changes={"first_name": ["A", "B"]},
    )

    assert explicit.required_perm == Perm.HR_VIEW
    assert stricter.required_perm == Perm.PAYROLL_VIEW


def test_unknown_permissions_are_a_bug(worker):
    with pytest.raises(ValueError):
        audit.record(
            "x.y", company_id=worker.company_id, actor=None, target=worker, required_perm="nope"
        )


def test_registration_rules(monkeypatch):
    monkeypatch.setattr(redaction, "_registry", {})
    redaction.register_sensitive(Membership, {"last_name": SECRET})
    redaction.register_sensitive("members.Membership", {"first_name": Perm.PAYROLL_VIEW})

    assert redaction.sensitive_fields(Membership) == {
        "last_name": SECRET,
        "first_name": Perm.PAYROLL_VIEW,
    }
    with pytest.raises(redaction.DuplicateSensitiveField):
        redaction.register_sensitive(Membership, {"last_name": SECRET})
    with pytest.raises(TypeError):
        redaction.register_sensitive(Membership, {"position": "secret"})


def test_redacted_markers_compare_by_hidden_value():
    assert Redacted("123") == Redacted("123")
    assert Redacted("123") != Redacted("124")
    assert Redacted("123") != "•••"
    assert json.dumps({"x": Redacted("123")}) == '{"x": "\\u2022\\u2022\\u2022"}'
    assert len({Redacted("1"), Redacted("1")}) == 1


def test_viewers_only_get_rows_whose_permission_they_hold(company, member, worker):
    owner = member.registered(company, "Owner")
    manager = member.registered(company, "Manager")
    accountant = member.registered(company, "Accountant")
    for perm in ("", Perm.PAYROLL_VIEW, Perm.HR_SENSITIVE):
        audit.record("x.y", company_id=company.pk, actor=None, target=worker, required_perm=perm)

    def seen(viewer):
        return sorted(row.required_perm for row in events(viewer))

    assert seen(owner) == sorted(["", Perm.PAYROLL_VIEW, Perm.HR_SENSITIVE])
    assert seen(accountant) == ["", Perm.PAYROLL_VIEW]
    assert seen(manager) == [""]


def test_events_stay_in_the_viewers_company(company, other_company, member, worker):
    owner = member.registered(company, "Owner")
    stranger = member.registered(other_company)
    audit.record("x.y", company_id=other_company.pk, actor=None, target=stranger)
    audit.record("x.y", company_id=company.pk, actor=None, target=worker)

    assert [row.company_id for row in events(owner)] == [company.pk]


def test_events_can_be_narrowed(company, member, worker):
    owner = member.registered(company, "Owner")
    role = AccessRole.objects.get(company=company, name="Employee")
    audit.record("a.one", company_id=company.pk, actor=owner.user, target=worker)
    audit.record("a.two", company_id=company.pk, actor=None, target=worker)
    audit.record("a.one", company_id=company.pk, actor=None, target=role)

    assert events(owner, target_type="membership", target_id=worker.pk).count() == 2
    assert events(owner, actions=["a.one"]).count() == 2
    assert events(owner, actor_ids=[owner.user_id]).count() == 1
