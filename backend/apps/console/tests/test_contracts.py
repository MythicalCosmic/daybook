"""The fixed fact and field shapes, and the checker providers use in their own tests."""

from apps.console import contracts


def test_a_fitting_value_has_no_problems():
    facts = {
        "opened_at": "2026-10-20T08:55:00+05:00",
        "opened_by": {"id": 3, "name": "Madina"},
        "open_tills": 2,
        "net": "4250000.00",
        "cash_in_branch": "1200000.00",
    }

    assert contracts.problems(contracts.SalesFacts, facts) == []
    assert contracts.problems(contracts.SalesFacts, facts | {"opened_by": None}) == []


def test_missing_extra_and_mistyped_fields_are_reported():
    found = contracts.problems(
        contracts.SalesFacts,
        {
            "opened_at": None,
            "opened_by": {"id": "3", "name": "Madina"},
            "open_tills": True,
            "net": 4250000,
            "profit": "1",
        },
    )

    assert "cash_in_branch: missing" in found
    assert "profit: not part of SalesFacts" in found
    assert any(problem.startswith("open_tills: expected an int") for problem in found)
    assert any(problem.startswith("net: expected a string") for problem in found)
    assert any(problem.startswith("opened_by:") for problem in found)


def test_a_non_dict_is_reported():
    assert contracts.problems(contracts.TasksFacts, [1, 2]) == ["value: expected a dict, got list"]


def test_person_field_shapes():
    salary = {"salary": {"amount": "5200000.00", "currency": "UZS", "pay_type": "monthly"}}

    assert contracts.problems(contracts.PERSON_FIELDS["payroll"], salary) == []
    assert contracts.problems(contracts.PERSON_FIELDS["payroll"], {"salary": None}) == []
    assert (
        contracts.problems(
            contracts.PERSON_FIELDS["attendance"],
            {"attendance_today": "in", "attendance_30d": "93.5"},
        )
        == []
    )


def test_every_fixed_key_has_a_shape():
    assert set(contracts.BRANCH_FACTS) == {"sales", "attendance", "tasks", "finance"}
    assert set(contracts.COMPANY_FACTS) == {
        "tasks",
        "sales",
        "finance",
        "attendance",
        "payroll",
        "inbox",
        "insights",
    }
    assert (
        contracts.problems(
            contracts.COMPANY_FACTS["payroll"], {"next_run_on": None, "next_run_amount": None}
        )
        == []
    )
