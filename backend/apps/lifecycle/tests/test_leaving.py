"""Leaving: the resignation asked for in the mini app, the last day agreed (or declined), the
handover list, the evening of the last day (the person leaves, payroll prepares the final
payslip), withdrawing, HR starting one, who may, and what the person sees.

The clock stands at 10:00 on Wednesday 21 October 2026 (Asia/Tashkent); Ali's last day is
Wednesday 4 November, two weeks later.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.hr.tests.conftest import DAY, local
from apps.inbox import services as inbox
from apps.inbox.models import Notification
from apps.lifecycle import providers, terminations
from apps.lifecycle.models import JobChange, Termination
from apps.members import services as members
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db

LAST = date(2026, 11, 4)


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/lifecycle/terminations/"


def mine(company) -> str:
    return f"/api/v1/companies/{company.pk}/lifecycle/leaving/"


@pytest.fixture
def paid(staff):
    """Ali is paid 5 200 000 a month since October 2025 (so a final payslip is prepared)."""
    from apps.payroll import services as payroll

    payroll.set_pay(staff.ali, by=None, effective_from=date(2025, 10, 1), amount="5200000")
    return staff


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    """`run(fn, *args, **kwargs)`: call it and run what it queued for after commit."""

    def call(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return call


def ask(staff, run, *, day=LAST, reason="Oilaviy sabab: Samarqandga ko‘chyapmiz"):
    return run(terminations.request, staff.ali, by=staff.ali, wished_last_day=day, reason=reason)


# The whole run -------------------------------------------------------------------------------


def test_asked_in_the_app_agreed_and_left_on_the_evening_with_the_final_payslip(
    shop, paid, api_as, owner_api, freeze, run
):
    staff = paid
    response = run(
        api_as(staff.ali).post,
        mine(shop),
        {"wished_last_day": "2026-11-04", "reason": "Oilaviy sabab"},
        format="json",
    )
    assert response.status_code == 201, response.content
    state = response.json()
    assert state["current"]["status"] == "requested" and state["can_request"] is False
    assert state["current"]["notice_days"] == 14
    termination = Termination.objects.get(membership=staff.ali)

    # HR who may run it hears in Telegram, with buttons; the request waits in Needs you.
    notice = Notification.objects.get(recipient=staff.owner, kind="lifecycle.resignation")
    assert notice.title == "Asks to leave: Ali Valiyev" and notice.in_app is False
    assert [action["key"] for action in notice.actions] == ["agree", "decline"]
    assert "04.11.2026" in notice.body and "Notice: 14 days" in notice.body
    assert not Notification.objects.filter(
        recipient=staff.manager, kind="lifecycle.resignation"
    ).exists()  # hr.view only
    queue = owner_api(staff.owner).get(f"/api/v1/owner/companies/{shop.pk}/queue/").json()
    items = [item for item in queue["items"] if item["kind"] == "lifecycle.resignations"]
    assert [str(item["id"]) for item in items] == [str(termination.pk)]
    assert [action["key"] for action in items[0]["actions"]] == ["agree", "decline"]

    # Agreed: the handover list is made and the person hears the day.
    response = run(owner_api(staff.owner).post, f"{base(shop)}{termination.pk}/agree/", {})
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "agreed" and body["last_day"] == "2026-11-04"
    assert [item["kind"] for item in body["items"]] == ["tasks", "keys", "documents"]
    assert body["items"][0]["done"] is True and body["items"][0]["auto"] is True  # no tasks
    assert body["handover"] == {"done": 1, "total": 3}
    told = Notification.objects.get(recipient=staff.ali, kind="lifecycle.leaving")
    assert told.title == "Your last working day: 04.11.2026"
    assert told.app_screen == "lifecycle.leaving"
    notice.refresh_from_db()
    assert notice.acted_at is not None  # the Telegram copy's buttons are gone

    keys = next(item for item in body["items"] if item["kind"] == "keys")
    response = owner_api(staff.owner).patch(
        f"{base(shop)}{termination.pk}/handover/{keys['id']}/",
        {"done": True, "note": "Farruxga topshirdi"},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["handover"] == {"done": 2, "total": 3}

    # Not before the evening of the last day; then they leave, and payroll prepares the
    # final payslip.
    freeze(local(LAST, 19, 50))
    assert run(terminations.complete_due) == 0
    freeze(local(LAST, 20, 5))
    assert run(terminations.complete_due) == 1
    staff.ali.refresh_from_db()
    termination.refresh_from_db()
    assert staff.ali.status == Membership.Status.LEFT
    assert termination.status == "completed" and termination.left_on == LAST
    assert termination.left_open == ["Documents"]
    from apps.payroll.models import PayrollRun

    final = PayrollRun.objects.get(kind="final", membership=staff.ali)
    assert final.last_day == LAST and final.status == "draft"
    assert Notification.objects.filter(
        recipient=staff.accountant, kind="payroll.final_run"
    ).exists()
    left = Notification.objects.get(recipient=staff.owner, kind="lifecycle.left")
    assert left.title == "Has left: Ali Valiyev"
    assert "The final payslip is waiting in Payroll" in left.body
    assert "Still not handed over: 1 item." in left.body
    assert AuditLog.objects.filter(
        action="lifecycle.leave_completed", target_id=staff.ali.pk
    ).exists()

    # Idempotent: nothing happens twice.
    assert run(terminations.complete_due) == 0
    assert PayrollRun.objects.filter(kind="final", membership=staff.ali).count() == 1

    # The detail links the final payslip (its amount for payroll.view only).
    body = owner_api(staff.owner).get(f"{base(shop)}{termination.pk}/").json()
    assert body["final_run"]["id"] == final.pk and body["final_run"]["net"] is not None
    assert [event["kind"] for event in body["events"]] == ["requested", "agreed", "completed"]
    hidden = owner_api(staff.manager).get(f"{base(shop)}{termination.pk}/").json()
    assert hidden["final_run"]["id"] == final.pk and hidden["final_run"]["net"] is None
    assert hidden["can"]["manage"] is False


def test_the_evening_waits_for_a_late_shift_to_end(shop, staff, freeze, run, monkeypatch):
    termination = run(terminations.agree, ask(staff, run), by=staff.owner)
    monkeypatch.setattr(
        "apps.lifecycle.integrations.last_shift_end", lambda member, day: local(day, 22)
    )
    assert terminations.due_at(termination) == local(LAST, 22, 15)
    freeze(local(LAST, 21))
    assert run(terminations.complete_due) == 0
    freeze(local(LAST, 22, 20))
    assert run(terminations.complete_due) == 1


def test_a_day_that_passed_unnoticed_completes_on_the_next_run(shop, staff, freeze, run):
    termination = ask(staff, run)
    run(terminations.agree, termination, by=staff.owner)
    freeze(local(LAST + timedelta(days=2), 9))
    assert run(terminations.complete_due) == 1
    termination.refresh_from_db()
    assert termination.left_on == LAST


def test_equipment_handed_back_is_taken_back_and_the_rest_stays_with_them(shop, staff, freeze, run):
    from apps.assets import defaults
    from apps.assets import services as assets
    from apps.assets.models import Asset, AssetCategory

    shop.features = [*shop.features, "assets"]
    shop.save(update_fields=["features"])
    defaults.ensure(shop)
    category = AssetCategory.objects.filter(company=shop, kind="low_value").first()
    gown = assets.create_asset(
        shop, by=staff.owner, category=category, name="Xalat", cost=Decimal("190000")
    )
    tablet = assets.create_asset(
        shop, by=staff.owner, category=category, name="Planshet", cost=Decimal("2400000")
    )
    for asset in (gown, tablet):
        assets.issue(asset, by=staff.owner, membership=staff.ali, on=DAY)

    termination = ask(staff, run)
    run(terminations.agree, termination, by=staff.owner)
    items = {item.title: item for item in termination.handover.all() if item.asset_id}
    assert sorted(items) == sorted([f"{gown.number} Xalat", f"{tablet.number} Planshet"])
    run(terminations.set_item, items[f"{gown.number} Xalat"], by=staff.owner, done=True)
    with pytest.raises(DomainError, match="still hold"):
        terminations.remove_item(items[f"{tablet.number} Planshet"], by=staff.owner)

    freeze(local(LAST, 20, 30))
    assert run(terminations.complete_due) == 1
    gown.refresh_from_db()
    tablet.refresh_from_db()
    assert gown.custodian_id is None  # handed back on the last day
    assert tablet.custodian_id == staff.ali.pk and tablet.status != Asset.Status.DISPOSED
    termination.refresh_from_db()
    assert f"{tablet.number} Planshet" in termination.left_open


# Withdrawn, declined, started by HR ----------------------------------------------------------


def test_the_person_withdraws_before_the_last_day_and_hr_hears(shop, staff, api_as, run, freeze):
    termination = ask(staff, run)
    run(terminations.agree, termination, by=staff.owner)

    freeze(local(LAST - timedelta(days=1), 18))
    response = run(api_as(staff.ali).post, f"{mine(shop)}{termination.pk}/withdraw/")
    assert response.status_code == 200, response.content
    assert response.json()["current"]["status"] == "withdrawn"
    assert response.json()["current"]["closed_by_me"] is True
    assert response.json()["can_request"] is True
    note = Notification.objects.get(recipient=staff.owner, kind="lifecycle.leaving_update")
    assert note.title == "Stays after all: Ali Valiyev"
    assert run(terminations.complete_due) == 0


def test_on_the_last_day_it_is_too_late_to_withdraw_in_the_app(shop, staff, run, freeze):
    termination = ask(staff, run)
    run(terminations.agree, termination, by=staff.owner)
    freeze(local(LAST, 9))
    with pytest.raises(DomainError, match="last day has come"):
        terminations.withdraw(termination, by=staff.ali)
    # HR still may, with the reason.
    with pytest.raises(DomainError, match="Say why"):
        terminations.withdraw(termination, by=staff.owner)
    done = run(terminations.withdraw, termination, by=staff.owner, reason="Qolishga kelishdik")
    assert done.status == "withdrawn"
    told = Notification.objects.get(
        recipient=staff.ali, kind="lifecycle.leaving", title="Your leaving is called off"
    )
    assert "Qolishga kelishdik" in told.body


def test_a_request_declined_with_the_reason_the_person_reads(shop, staff, owner_api, run):
    termination = ask(staff, run)
    path = f"{base(shop)}{termination.pk}/decline/"
    response = owner_api(staff.owner).post(path, {}, format="json")
    assert response.status_code == 400  # a reason is required
    response = run(owner_api(staff.owner).post, path, {"reason": "Gaplashdik, qoladi"})
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "declined"
    told = Notification.objects.get(recipient=staff.ali, kind="lifecycle.leaving")
    assert told.title == "Your request to leave was declined"
    assert "Gaplashdik, qoladi" in told.body
    with pytest.raises(DomainError):
        terminations.agree(termination, by=staff.owner)
    # They may ask again.
    again = ask(staff, run)
    assert again.pk != termination.pk


def test_hr_starts_a_leaving_with_the_day_agreed_at_once(shop, staff, owner_api, run):
    path = base(shop)
    payload = {
        "member_id": staff.vali.pk,
        "kind": "contract_end",
        "last_day": "2026-10-31",
        "reason": "Mehnat shartnomasi muddati tugaydi",
        "leave_days": "3.5",
    }
    response = run(owner_api(staff.owner).post, path, payload, format="json")
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["status"] == "agreed" and body["initiated_by"] == "company"
    assert body["leave_days"] == "3.50" and body["final_payslip"] is True
    assert Notification.objects.get(recipient=staff.vali, kind="lifecycle.leaving").title == (
        "Your last working day: 31.10.2026"
    )
    again = owner_api(staff.owner).post(path, payload, format="json")
    assert again.status_code == 400 and "already leaving" in again.json()["detail"]
    past = owner_api(staff.owner).post(
        path, {**payload, "member_id": staff.sara.pk, "last_day": "2026-10-20"}, format="json"
    )
    assert past.status_code == 400 and "past" in past.json()["detail"]


def test_details_change_and_after_leaving_only_notes_and_rehire(
    shop, staff, owner_api, run, freeze
):
    termination = ask(staff, run)
    run(terminations.agree, termination, by=staff.owner)
    path = f"{base(shop)}{termination.pk}/"
    response = owner_api(staff.owner).patch(
        path, {"leave_days": "5", "notes": "Yaxshi xodim", "rehire": "yes"}, format="json"
    )
    assert response.status_code == 200, response.content
    assert response.json()["leave_days"] == "5.00" and response.json()["rehire"] == "yes"
    freeze(local(LAST, 21))
    run(terminations.complete_due)
    response = owner_api(staff.owner).patch(path, {"leave_days": "2"}, format="json")
    assert response.status_code == 400
    response = owner_api(staff.owner).patch(path, {"rehire": "maybe"}, format="json")
    assert response.status_code == 200 and response.json()["rehire"] == "maybe"
    row = AuditLog.objects.filter(action="lifecycle.leave_changed").first()
    assert "Yaxshi xodim" not in str(row.details)


# Who may -------------------------------------------------------------------------------------


def test_who_may_run_a_leaving(shop, staff, owner_api, outsider, run):
    termination = ask(staff, run)
    path = f"{base(shop)}{termination.pk}/agree/"
    assert owner_api(staff.manager).get(base(shop)).status_code == 200  # hr.view reads
    assert owner_api(staff.manager).post(path, {}).status_code == 403
    assert owner_api(staff.accountant).post(path, {}).status_code == 403
    assert owner_api(staff.ali).get(base(shop)).status_code == 403  # no dashboard
    assert owner_api(outsider).get(f"{base(outsider.company)}{termination.pk}/").status_code == 404
    start = {"member_id": outsider.pk, "kind": "company", "last_day": "2026-11-01"}
    assert owner_api(staff.owner).post(base(shop), start, format="json").status_code == 404

    # Someone with hr.terminate at Chilonzor only: Sara (Yunusobod) is out of reach.
    role = AccessRole.objects.create(
        company=shop,
        name="Chilonzor HR",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.HR_VIEW, Perm.HR_TERMINATE],
    )
    staff.lead.role = role
    staff.lead.save(update_fields=["role"])
    sara = run(terminations.request, staff.sara, by=staff.sara, wished_last_day=LAST)
    assert owner_api(staff.lead).get(f"{base(shop)}{sara.pk}/").status_code == 404
    assert owner_api(staff.lead).get(f"{base(shop)}{termination.pk}/").status_code == 200
    listed = owner_api(staff.lead).get(base(shop)).json()["results"]
    assert [row["id"] for row in listed] == [termination.pk]
    # An owner's leaving only by an owner, and nobody runs their own.
    with pytest.raises(PermissionDenied):
        terminations.start(staff.owner, by=staff.lead, kind="company", last_day=LAST)
    with pytest.raises(DomainError):
        terminations.start(staff.owner, by=staff.owner, kind="company", last_day=LAST)
    # Someone else's request can't be withdrawn or answered from the app.
    with pytest.raises(PermissionDenied):
        terminations.answer_exit(termination, by=staff.vali, reason="pay")


def test_the_list_tabs_counts_and_filters(shop, staff, owner_api, run):
    asked = ask(staff, run)
    agreed = run(
        terminations.start, staff.vali, by=staff.owner, kind="company", last_day=LAST, reason="X"
    )
    response = owner_api(staff.owner).get(f"{base(shop)}counts/")
    assert response.json() == {"requested": 1, "agreed": 1, "completed": 0, "closed": 0}
    rows = owner_api(staff.owner).get(base(shop), {"status": "agreed"}).json()["results"]
    assert [row["id"] for row in rows] == [agreed.pk]
    assert rows[0]["handover"] == {"done": 1, "total": 3}
    rows = owner_api(staff.owner).get(base(shop), {"q": "Valiyev"}).json()["results"]
    assert [row["id"] for row in rows] == [asked.pk]
    assert rows[0]["initiated_by"] == "employee" and rows[0]["notice_days"] == 14


# Other ways out ------------------------------------------------------------------------------


def test_offboarded_from_their_page_meanwhile_closes_it_and_cancels_job_changes(shop, staff, run):
    from apps.lifecycle import job_changes

    termination = ask(staff, run)
    run(terminations.agree, termination, by=staff.owner)
    change = run(
        job_changes.propose,
        staff.ali,
        by=staff.owner,
        effective_on=LAST + timedelta(days=10),
        reason="Boshqa filial",
        branch=staff.sara.home_branch,
    )
    step = providers.offboard_step(staff.ali)
    assert any("04.11.2026" in line for line in step.lines)
    run(
        members.complete_offboarding,
        staff.ali,
        by=staff.owner,
        terminated_on=DAY,
        reason="resignation",
    )
    termination.refresh_from_db()
    change.refresh_from_db()
    assert termination.status == "completed" and termination.left_on == DAY
    assert termination.events[-1]["kind"] == "left"
    assert change.status == JobChange.Status.CANCELLED


def test_a_refused_completion_waits_for_try_again(shop, staff, owner_api, run, freeze, monkeypatch):
    termination = ask(staff, run)
    run(terminations.agree, termination, by=staff.owner)

    def refuse(*args, **kwargs):
        raise DomainError("This is the company's only owner.")

    monkeypatch.setattr("apps.members.services.complete_offboarding", refuse)
    freeze(local(LAST, 21))
    assert run(terminations.complete_due) == 0
    termination.refresh_from_db()
    assert termination.status == "agreed" and "only owner" in termination.error
    note = Notification.objects.get(recipient=staff.owner, kind="lifecycle.leaving_update")
    assert note.title == "Leaving not completed: Ali Valiyev"
    assert run(terminations.complete_due) == 0  # waits for a person
    assert Notification.objects.filter(kind="lifecycle.leaving_update").count() == 1

    monkeypatch.undo()
    freeze(local(LAST, 21, 30))
    detail = owner_api(staff.owner).get(f"{base(shop)}{termination.pk}/").json()
    assert detail["can"]["retry"] is True
    response = run(owner_api(staff.owner).post, f"{base(shop)}{termination.pk}/retry/")
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "completed" and response.json()["error"] == ""


def test_agreeing_from_the_telegram_button(shop, staff, run):
    termination = ask(staff, run)
    notice = Notification.objects.get(recipient=staff.owner, kind="lifecycle.resignation")
    message = run(inbox.run_action, notice.pk, "agree", by=staff.owner)
    assert message == "Agreed: last working day 04.11.2026"
    termination.refresh_from_db()
    assert termination.status == "agreed" and termination.agreed_by_id == staff.owner.pk


def test_the_morning_of_the_last_day_hr_hears_what_is_open(shop, staff, run, freeze):
    termination = ask(staff, run)
    run(terminations.agree, termination, by=staff.owner)
    freeze(local(LAST, 8, 50))
    assert terminations.remind_due() == 0
    freeze(local(LAST, 9, 5))
    assert run(terminations.remind_due) == 1
    assert run(terminations.remind_due) == 0  # once
    note = Notification.objects.get(recipient=staff.owner, kind="lifecycle.leaving_update")
    assert note.title == "Last working day today: Ali Valiyev"
    assert note.body == "Handed over: 1. Still open: 2."


def test_last_days_on_the_calendar(shop, staff, run):
    termination = ask(staff, run)
    assert providers.calendar_last_days(shop, DAY, LAST, staff.owner) == []
    run(terminations.agree, termination, by=staff.owner)
    [item] = providers.calendar_last_days(shop, DAY, LAST, staff.owner)
    assert item.title == "Last working day: Ali Valiyev" and item.start == LAST
    assert item.url == f"lifecycle/terminations?termination={termination.pk}"


# What the person sees ------------------------------------------------------------------------


def test_the_person_asks_answers_the_exit_questions_and_never_sees_hr_notes(
    shop, staff, api_as, owner_api, run
):
    client = api_as(staff.ali)
    state = client.get(mine(shop)).json()
    assert state == {
        "current": None,
        "can_request": True,
        "notice_days": 14,
        "today": "2026-10-21",
    }
    past = client.post(mine(shop), {"wished_last_day": "2026-10-20"}, format="json")
    assert past.status_code == 400
    run(client.post, mine(shop), {"wished_last_day": "2026-11-04"}, format="json")
    again = client.post(mine(shop), {"wished_last_day": "2026-11-05"}, format="json")
    assert again.status_code == 400 and "already asked" in again.json()["detail"]
    termination = Termination.objects.get(membership=staff.ali)
    run(terminations.agree, termination, by=staff.owner)
    terminations.update(termination, by=staff.owner, notes="Maxfiy eslatma")

    response = client.post(
        f"{mine(shop)}{termination.pk}/exit/",
        {"reason": "moving", "better": "Ko‘proq dam olish kunlari", "recommend": "yes"},
        format="json",
    )
    assert response.status_code == 200, response.content
    current = response.json()["current"]
    assert current["exit_interview"]["reason"] == "moving"
    assert "notes" not in current and current["can_withdraw"] is True
    assert [item["kind"] for item in current["handover"]] == ["tasks", "keys", "documents"]
    detail = owner_api(staff.owner).get(f"{base(shop)}{termination.pk}/").json()
    assert detail["exit_interview"]["recommend"] == "yes"
    assert detail["notes"] == "Maxfiy eslatma"
    bad = client.post(f"{mine(shop)}{termination.pk}/exit/", {"reason": "x"}, format="json")
    assert bad.status_code == 400
    other = api_as(staff.vali).post(f"{mine(shop)}{termination.pk}/withdraw/")
    assert other.status_code == 404


def test_without_hr_the_leaving_pages_answer_403(shop, staff, api_as, owner_api):
    shop.features = ["payroll"]
    shop.save(update_fields=["features"])
    assert api_as(staff.ali).get(mine(shop)).status_code == 403
    assert owner_api(staff.owner).get(base(shop)).status_code == 403
