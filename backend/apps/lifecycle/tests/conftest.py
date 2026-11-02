"""The lifecycle tests use HR's pharmacy (two branches, the HR module on) and its people; see
`apps/hr/tests/conftest.py`. The Manager role holds hr.discipline, the Owner every permission
(hr.suspend among them); the Accountant only reads HR."""

from apps.hr.tests.conftest import (  # noqa: F401  (fixtures)
    chilonzor,
    freeze,
    outsider,
    shop,
    staff,
    yunusobod,
)
