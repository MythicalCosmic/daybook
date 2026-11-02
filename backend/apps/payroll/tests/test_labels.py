"""Payslip lines and run warnings read in the reader's language, numbers written their way."""

import pytest
from django.utils import translation

from apps.payroll import labels
from apps.payroll.models import PayslipLine

Kind = PayslipLine.Kind


def line(kind, **params):
    return PayslipLine(kind=kind, label="stored", params=params)


@pytest.mark.parametrize(
    ("language", "overtime", "night"),
    [
        ("en", "Overtime: 4.5 h at ×2", "Night hours: 32 h at ×1.5"),
        ("uz", "Qo‘shimcha ish: 4,5 soat, ×2", "Tungi soatlar: 32 soat, ×1,5"),
        ("ru", "Сверхурочные: 4,5 ч, ×2", "Ночные часы: 32 ч, ×1,5"),
    ],
)
def test_extras_in_each_language(language, overtime, night):
    with translation.override(language):
        assert (
            labels.line_label(line(Kind.OVERTIME, code="overtime", minutes=270, multiplier="2.00"))
            == overtime
        )
        assert (
            labels.line_label(
                line(Kind.NIGHT_WORK, code="night_work", minutes=1920, multiplier="1.50")
            )
            == night
        )


def test_days_and_leave():
    with translation.override("en"):
        assert labels.line_label(line(Kind.PRORATION, code="absent", days=2)) == "Absent: 2 days"
        assert (
            labels.line_label(
                line(Kind.PRORATION, code="partial_leave", leave_kind="sick", percent=60, days=3)
            )
            == "Sick leave at 60%: 3 days"
        )
        assert labels.line_label(line(Kind.BASE, code="base", pay_type="monthly")) == "Monthly pay"
    with translation.override("ru"):
        assert labels.line_label(line(Kind.PRORATION, code="absent", days=2)) == "Прогулы: 2 дня"


def test_hand_made_lines_keep_their_words():
    assert labels.line_label(line(Kind.MANUAL, code="manual")) == "stored"


def test_warnings():
    with translation.override("en"):
        assert (
            labels.warning_text({"code": "no_pay_setup", "member": {"name": "Vali"}})
            == "Vali has no pay setup: no payslip."
        )
        assert labels.warning_text({"code": "proposed", "count": 1}) == (
            "1 bonus or fine still waits for a decision."
        )
