"""Fixtures of the Face ID tests: attendance's shop (Chilonzor and Yunusobod, their people, a
clock that can be frozen; Wednesday 21 October 2026, Asia/Tashkent) with Face ID switched on, and
a terminal at Chilonzor's door."""

from datetime import time

import pytest

from apps.attendance.tests.conftest import (  # noqa: F401 (fixtures)
    CHILONZOR,
    DAY,
    YUNUSOBOD,
    chilonzor,
    freeze,
    local,
    staff,
    yunusobod,
)
from apps.companies.models import Branch
from apps.faceid.models import FaceDevice, FaceLink


@pytest.fixture
def shop(company):
    """Attendance's shop, with the Face ID module on too."""
    company.features = ["attendance", "face_id"]
    company.save(update_fields=["features"])
    first = company.branches.order_by("order", "pk").first()
    first.name, first.code = "Chilonzor", "CHL"
    first.latitude, first.longitude = CHILONZOR
    first.geofence_m = 150
    first.opens_at, first.closes_at = time(9, 0), time(21, 0)
    first.save()
    Branch.objects.create(
        company=company,
        name="Yunusobod",
        code="YNS",
        latitude=YUNUSOBOD[0],
        longitude=YUNUSOBOD[1],
        opens_at=time(10, 0),
        closes_at=time(22, 0),
        order=1,
    )
    return company


@pytest.fixture
def device(staff, chilonzor, freeze):  # noqa: F811 (fixtures by name)
    """Chilonzor's door terminal, added at 06:00; Ali is number 12, Vali 13, Sara 21."""
    freeze(local(DAY, 6, 0))
    made = FaceDevice.objects.create(company=chilonzor.company, branch=chilonzor, name="Kirish")
    for number, person in (("12", staff.ali), ("13", staff.vali), ("21", staff.sara)):
        FaceLink.objects.create(company=made.company, employee_no=number, membership=person)
    return made
