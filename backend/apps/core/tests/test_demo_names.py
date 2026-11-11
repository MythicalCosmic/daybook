"""The demo's positions and roles end up in Uzbek, and so does what the module demos stored with
their English working names (v12): a promotion's before and after, the audit trail."""

import pytest

from apps.audit.models import AuditLog
from apps.core import demo_plan as plan
from apps.core.management.commands import seed_demo
from apps.members.models import Position

NAMES = {**plan.IN_UZBEK_ROLES, **plan.IN_UZBEK_POSITIONS}


def test_names_under_position_and_role_keys_are_put_in_uzbek():
    before = {
        "role": {"id": 4, "name": "Pharmacist"},
        "position": {"id": 7, "name": plan.SENIOR},
        "branch": {"id": 1, "name": "Chilonzor"},
        "changes": {"position": [plan.PHARMACIST, plan.SENIOR]},
        "positions": [plan.HEAD, plan.COURIER],
        "reason": "Pharmacist of the year",
        "note": plan.PHARMACIST,
    }

    after = seed_demo.in_uzbek(before, NAMES)

    assert after["role"] == {"id": 4, "name": "Farmatsevt"}
    assert after["position"] == {"id": 7, "name": "Provizor"}
    assert after["branch"] == {"id": 1, "name": "Chilonzor"}
    assert after["changes"] == {"position": ["Farmatsevt", "Provizor"]}
    assert after["positions"] == ["Dorixona mudiri", "Kuryer"]
    # Free text and other keys are left alone: only names, word for word.
    assert after["reason"] == "Pharmacist of the year"
    assert after["note"] == plan.PHARMACIST


@pytest.mark.django_db
def test_what_was_stored_with_the_english_names_follows_the_rename(company):
    Position.objects.create(company=company, name=plan.SENIOR)
    promoted = AuditLog.objects.create(
        company=company,
        action="lifecycle.job_change_applied",
        target_type="membership",
        target="Gulnora",
        details={"changes": {"position": [plan.PHARMACIST, plan.SENIOR]}},
    )
    other = AuditLog.objects.create(
        company=company, action="x", target_type="y", target="z", details={"count": 3}
    )

    seed_demo.names_in_uzbek(company)

    assert Position.objects.filter(company=company, name="Provizor").exists()
    promoted.refresh_from_db()
    other.refresh_from_db()
    assert promoted.details == {"changes": {"position": ["Farmatsevt", "Provizor"]}}
    assert other.details == {"count": 3}
