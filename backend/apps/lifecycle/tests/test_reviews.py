"""Performance reviews: opening a round (who is in it, who reviews whom, one notice each), the
person's own answers (a draft, sending, the deadline and its reminder), who sees what, the
reviewer's numbers frozen once taken, each outcome becoming the right proposal with nothing
applied before its approval, publishing and acknowledging, the results, and scope.

The clock stands at 10:00 on Wednesday 21 October 2026 (Asia/Tashkent). The round reviews the
third quarter; people answer by Wednesday 28 October, reviewers by Wednesday 4 November.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.utils import translation

from apps.ai import availability, conf
from apps.ai.fakes import FakeAnthropic
from apps.ai.models import AIUsage
from apps.companies.models import Feature
from apps.hr.tests.conftest import local
from apps.inbox.models import Notification
from apps.lifecycle import (
    job_changes,
    review_ai,
    review_kpis,
    review_notify,
    review_queries,
    reviews,
)
from apps.lifecycle.models import DisciplinaryRecord, JobChange, Review, ReviewCycle, ReviewGoal
from apps.members.models import AccessRole, Department, Membership, Position
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db

SELF_DUE = date(2026, 10, 28)
MANAGER_DUE = date(2026, 11, 4)
NOVEMBER = date(2026, 11, 1)


def rounds(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/lifecycle/review-rounds/"


def review_url(company, review) -> str:
    return f"/api/v1/owner/companies/{company.pk}/lifecycle/reviews/{review.pk}/"


def mine(company, rest: str = "") -> str:
    return f"/api/v1/companies/{company.pk}/lifecycle/reviews/{rest}"


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    def call(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return call


@pytest.fixture
def team(shop, staff, chilonzor):
    """Chilonzor's department, headed by the manager (who runs reviews): Ali and Vali."""
    department = Department.objects.create(company=shop, name="Chilonzor", head=staff.manager)
    for person in (staff.manager, staff.ali, staff.vali):
        person.department = department
        person.save(update_fields=["department"])
    return staff


@pytest.fixture
def paid(team):
    from apps.payroll import services as payroll

    payroll.set_pay(team.ali, by=None, effective_from=date(2025, 10, 1), amount="5200000")
    payroll.set_pay(team.vali, by=None, effective_from=date(2025, 10, 1), amount="4800000")
    return team


@pytest.fixture
def senior(shop):
    return Position.objects.create(company=shop, name="Senior pharmacist", order=3)


def make_round(shop, by, **extra):
    fields = {
        "name": "2026, 3rd quarter",
        "period_start": date(2026, 7, 1),
        "period_end": date(2026, 9, 30),
        "self_due_on": SELF_DUE,
        "manager_due_on": MANAGER_DUE,
        "questions": reviews.template(),
    }
    fields.update(extra)
    return reviews.create_cycle(shop, by=by, **fields)


@pytest.fixture
def opened(shop, team, run):
    cycle = make_round(shop, team.manager)
    return run(reviews.open_cycle, cycle, by=team.manager)


def review_of(cycle, person) -> Review:
    return Review.objects.select_related("cycle", "membership").get(cycle=cycle, membership=person)


def all_ratings(cycle, rating: int = 4, text: str = "") -> dict:
    found = {}
    for question in cycle.questions:
        if question["kind"] == "rating":
            found[question["id"]] = {"rating": rating, "text": text}
        else:
            found[question["id"]] = {"rating": None, "text": "Yaxshi ishladim"}
    return found


def to_reviewers(shop, cycle, run):
    """The self deadline passed: the reviewers' part begins."""
    return run(reviews.advance, ReviewCycle.objects.get(pk=cycle.pk), by=None)


# Opening a round ------------------------------------------------------------------------------


def test_a_round_opens_for_everyone_in_it_with_their_reviewer_and_each_hears_once(
    shop, team, owner_api, run
):
    body = {
        "name": "2026, 3rd quarter",
        "period_start": "2026-07-01",
        "period_end": "2026-09-30",
        "self_due_on": "2026-10-28",
        "manager_due_on": "2026-11-04",
        "questions": reviews.template(),
        "open": True,
    }
    response = run(owner_api(team.manager).post, rounds(shop), body, format="json")
    assert response.status_code == 201, response.content
    data = response.json()
    assert data["status"] == "self"
    assert [question["key"] for question in data["questions"]][:2] == ["dispensing", "customers"]
    cycle = ReviewCycle.objects.get(pk=data["id"])

    found = {row.membership_id: row.reviewer_id for row in cycle.reviews.all()}
    # Owners are never in a round; the department's people get their head, the rest the owner.
    assert team.owner.pk not in found
    assert found[team.ali.pk] == team.manager.pk
    assert found[team.vali.pk] == team.manager.pk
    assert found[team.sara.pk] == team.owner.pk
    assert found[team.manager.pk] == team.owner.pk
    assert data["progress"]["people"] == len(found) == 6

    notices = Notification.objects.filter(kind=review_notify.REVIEW)
    assert notices.count() == 6
    ali = notices.get(recipient=team.ali)
    review = review_of(cycle, team.ali)
    assert ali.app_screen == f"lifecycle.review:{review.pk}"
    assert ali.title == "Performance review: 2026, 3rd quarter"
    assert "Deadline: 28.10.2026" in ali.body
    # Telling them again changes nothing.
    review_notify.round_opened(cycle.pk)
    assert Notification.objects.filter(kind=review_notify.REVIEW).count() == 6


def test_the_audience_is_positions_and_branches_without_owners_and_people_leaving(
    shop, team, yunusobod, run
):
    from apps.lifecycle import terminations

    cycle = make_round(shop, team.owner, positions=[team.pharmacist])
    people = set(reviews.audience_of(cycle, branch_ids=None).values_list("pk", flat=True))
    assert people == {team.ali.pk, team.vali.pk, team.sara.pk}

    cycle = make_round(shop, team.owner, branches=[yunusobod])
    people = set(reviews.audience_of(cycle, branch_ids=None).values_list("pk", flat=True))
    # The office people work at both branches; Sara at Yunusobod only.
    assert team.sara.pk in people and team.ali.pk not in people
    assert team.owner.pk not in people

    # Someone whose last day is agreed isn't reviewed.
    leaving = terminations.start(
        team.vali, by=team.owner, kind="resignation", last_day=date(2026, 11, 6)
    )
    assert leaving.status == "agreed"
    cycle = make_round(shop, team.owner, positions=[team.pharmacist])
    people = set(reviews.audience_of(cycle, branch_ids=None).values_list("pk", flat=True))
    assert people == {team.ali.pk, team.sara.pk}

    # Nor someone who joined after the period: Sara came on 1 October.
    team.sara.onboarded_at = local(date(2026, 10, 1), 9)
    team.sara.save(update_fields=["onboarded_at"])
    people = set(reviews.audience_of(cycle, branch_ids=None).values_list("pk", flat=True))
    assert people == {team.ali.pk}


def test_a_reviewer_is_the_nearest_head_who_runs_reviews_else_the_branch_manager(
    shop, team, chilonzor, yunusobod, member, run
):
    # A sub-department whose head (an ordinary pharmacist) can't run reviews: its people go
    # to the head above, who can.
    night = Department.objects.create(
        company=shop, name="Night", head=team.vali, parent=team.manager.department
    )
    team.ali.department = night
    team.ali.save(update_fields=["department"])
    # Yunusobod's manager runs reviews: Sara goes to her.
    head = member.registered(
        shop, "Manager", home_branch=yunusobod, first_name="Malika", last_name="Tosheva"
    )
    head.branches.add(yunusobod)
    yunusobod.manager = head
    yunusobod.save(update_fields=["manager"])

    cycle = run(reviews.open_cycle, make_round(shop, team.owner), by=team.owner)
    assert review_of(cycle, team.ali).reviewer == team.manager
    assert review_of(cycle, team.sara).reviewer == head
    assert review_of(cycle, team.vali).reviewer == team.manager


def test_opening_checks_the_round(shop, team):
    cycle = make_round(shop, team.owner)
    with pytest.raises(reviews.DomainError, match="3 to 10"):
        reviews.update_cycle(cycle, by=team.owner, questions=reviews.template()[:2])
    with pytest.raises(reviews.DomainError, match="on or after"):
        reviews.update_cycle(cycle, by=team.owner, manager_due_on=date(2026, 10, 27))
    nobody = make_round(
        shop, team.owner, positions=[Position.objects.create(company=shop, name="X")]
    )
    with pytest.raises(reviews.DomainError, match="Nobody is in this round"):
        reviews.open_cycle(nobody, by=team.owner)
    late = make_round(shop, team.owner, self_due_on=date(2026, 10, 20))
    with pytest.raises(reviews.DomainError, match="has passed"):
        reviews.open_cycle(late, by=team.owner)


def test_template_questions_follow_the_reader_and_edited_ones_keep_their_words(shop, team):
    from django.utils import translation

    questions = reviews.template()
    questions[0]["text"] = "Retseptli dorilar: qoidalarga rioya"
    cycle = make_round(shop, team.owner, questions=questions)
    assert cycle.questions[0]["key"] == "" and cycle.questions[1]["key"] == "customers"
    with translation.override("ru"):
        shown = reviews.shown_questions(cycle)
    assert shown[0]["text"] == "Retseptli dorilar: qoidalarga rioya"
    assert shown[1]["text"] == str(reviews.TEMPLATE_TEXT["customers"])


# The person's own answers ---------------------------------------------------------------------


def test_the_person_drafts_their_answers_and_sends_them_once(shop, team, opened, api_as, run):
    review = review_of(opened, team.ali)
    client = api_as(team.ali)
    listed = client.get(mine(shop)).json()
    assert [row["id"] for row in listed["open"]] == [review.pk]
    assert listed["open"][0]["state"] == "todo" and listed["open"][0]["can_answer"] is True

    first = opened.questions[0]["id"]
    response = client.patch(
        mine(shop, f"{review.pk}/"), {"answers": {first: {"rating": 5}}}, format="json"
    )
    assert response.status_code == 200, response.content
    assert response.json()["state"] == "draft"
    assert response.json()["answers"][first]["rating"] == 5

    # Every rating first.
    response = client.post(mine(shop, f"{review.pk}/send/"), {}, format="json")
    assert response.status_code == 400
    assert "every rating" in response.json()["detail"]

    response = run(
        client.post,
        mine(shop, f"{review.pk}/send/"),
        {"answers": all_ratings(opened, 4)},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["state"] == "sent"
    assert response.json()["can_answer"] is False
    response = client.patch(
        mine(shop, f"{review.pk}/"), {"answers": {first: {"rating": 1}}}, format="json"
    )
    assert response.status_code == 400
    assert review_of(opened, team.ali).self_answers[first]["rating"] == 4

    # Nobody else's review is ever there.
    other = review_of(opened, team.vali)
    assert client.get(mine(shop, f"{other.pk}/")).status_code == 404
    assert (
        client.patch(mine(shop, f"{other.pk}/"), {"answers": {}}, format="json").status_code == 404
    )


def test_the_person_hears_again_the_day_before_their_deadline_then_the_reviewers_part_begins(
    shop, team, opened, run
):
    reviews.send_self(review_of(opened, team.vali), by=team.vali, answers=all_ratings(opened))
    before = Notification.objects.filter(kind=review_notify.REVIEW).count()
    assert reviews.run_due(local(date(2026, 10, 27), 9, 50)) == 0
    assert run(reviews.run_due, local(date(2026, 10, 27), 10, 5)) == 1
    reminders = Notification.objects.filter(
        kind=review_notify.REVIEW, title="Reminder: your self review is waiting"
    )
    # Everyone still to answer, once; Vali already sent hers.
    assert reminders.count() == 5
    assert not reminders.filter(recipient=team.vali).exists()
    assert run(reviews.run_due, local(date(2026, 10, 27), 10, 20)) == 0
    assert Notification.objects.filter(kind=review_notify.REVIEW).count() == before + 5

    # After the deadline whoever didn't answer is late, and may still answer for three days.
    assert run(reviews.run_due, local(date(2026, 10, 29), 0, 7)) == 0
    opened.refresh_from_db()
    assert opened.status == "self"
    late = reviews.late(opened, opened.reviews.all(), today=date(2026, 10, 29))
    assert review_of(opened, team.ali).pk in late
    assert review_of(opened, team.vali).pk not in late
    reviews.send_self(review_of(opened, team.ali), by=team.ali, answers=all_ratings(opened))

    # Then the reviewers' part begins by itself, and the reviewers hear.
    assert run(reviews.run_due, local(date(2026, 11, 1), 0, 7)) == 1
    opened.refresh_from_db()
    assert opened.status == "manager"
    notice = Notification.objects.get(kind=review_notify.TO_WRITE, recipient=team.manager)
    assert notice.title == "Reviews to write: 2026, 3rd quarter"
    assert notice.body == "2 people wait for your review. Deadline: 04.11.2026."
    assert notice.url == f"/c/{shop.pk}/lifecycle/reviews/{opened.pk}?mine=1"


def test_remind_nudges_whoever_is_behind_once_a_day(shop, team, opened, owner_api, run):
    path = f"{rounds(shop)}{opened.pk}/remind/"
    response = run(owner_api(team.manager).post, path)
    assert response.status_code == 200, response.content
    assert response.json() == {"people": 6, "reviewers": 0}
    nudges = Notification.objects.filter(kind=review_notify.REVIEW, title__startswith="Reminder")
    assert nudges.count() == 6
    run(owner_api(team.manager).post, path)
    assert nudges.count() == 6  # once a day each


# Who sees what --------------------------------------------------------------------------------


def test_self_answers_stay_with_the_person_until_the_reviewers_part(
    shop, team, opened, owner_api, run
):
    review = review_of(opened, team.ali)
    reviews.send_self(review, by=team.ali, answers=all_ratings(opened, 3))
    shown = owner_api(team.manager).get(review_url(shop, review)).json()
    assert shown["self_part"]["visible"] is False and shown["self_part"]["answers"] is None
    assert shown["self_part"]["state"] == "sent"
    assert shown["kpis"] is None and shown["can"]["write"] is False

    to_reviewers(shop, opened, run)
    shown = owner_api(team.manager).get(review_url(shop, review)).json()
    assert shown["self_part"]["visible"] is True
    assert shown["self_part"]["average"] == "3.0"
    assert shown["can"]["write"] is True


def test_a_review_is_read_by_its_reviewer_and_owners_only(shop, team, opened, owner_api, member):
    sara = review_of(opened, team.sara)  # the owner reviews her
    ali = review_of(opened, team.ali)  # the manager reviews him
    # The manager runs the round: he sees Sara's row but not what's in it.
    rows = owner_api(team.manager).get(f"{rounds(shop)}{opened.pk}/reviews/").json()
    row = next(item for item in rows if item["id"] == sara.pk)
    assert row["can_open"] is False and row["rating"] is None
    assert owner_api(team.manager).get(review_url(shop, sara)).status_code == 404
    assert owner_api(team.owner).get(review_url(shop, ali)).status_code == 200
    # Someone without reviews.manage doesn't reach reviews at all.
    assert owner_api(team.accountant).get(rounds(shop)).status_code == 403
    assert owner_api(team.accountant).get(review_url(shop, ali)).status_code == 403
    # Mine only: "?mine=1" is what the reviewer's notice opens.
    rows = owner_api(team.manager).get(f"{rounds(shop)}{opened.pk}/reviews/?mine=1").json()
    assert {item["id"] for item in rows} == {
        review_of(opened, team.ali).pk,
        review_of(opened, team.vali).pk,
    }


def test_a_reviewer_who_doesnt_run_the_round_sees_only_the_reviews_they_give(
    shop, team, chilonzor, member, owner_api, run
):
    role = AccessRole.objects.create(
        company=shop,
        name="Chilonzor head",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.REVIEWS_MANAGE, Perm.HR_VIEW],
    )
    head = member.registered(shop, "Employee", home_branch=chilonzor, first_name="Lola")
    head.role = role
    head.save(update_fields=["role"])
    head.branches.add(chilonzor)
    department = team.manager.department
    department.head = head
    department.save(update_fields=["head"])
    cycle = run(reviews.open_cycle, make_round(shop, team.owner), by=team.owner)

    rows = owner_api(head).get(f"{rounds(shop)}{cycle.pk}/reviews/").json()
    people = {item["member"]["id"] for item in rows}
    assert team.ali.pk in people and team.vali.pk in people
    assert team.sara.pk not in people
    assert all(item["can_open"] for item in rows)
    # The round isn't theirs to run.
    assert owner_api(head).post(f"{rounds(shop)}{cycle.pk}/close/").status_code == 403


def test_a_branch_head_runs_rounds_for_their_branch_only(
    shop, team, chilonzor, member, owner_api, outsider, run
):
    role = AccessRole.objects.create(
        company=shop,
        name="Branch head",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.REVIEWS_MANAGE, Perm.HR_VIEW],
    )
    head = member.registered(shop, "Employee", home_branch=chilonzor, first_name="Bobur")
    head.role = role
    head.save(update_fields=["role"])
    head.branches.add(chilonzor)
    cycle = run(reviews.open_cycle, make_round(shop, head), by=head)
    people = set(cycle.reviews.values_list("membership_id", flat=True))
    assert team.sara.pk not in people and team.ali.pk in people
    # Another company's round answers 404; with HR off everything is closed.
    assert owner_api(outsider).get(f"{rounds(shop)}{cycle.pk}/").status_code == 404
    shop.features = ["payroll"]
    shop.save(update_fields=["features"])
    assert owner_api(team.owner).get(rounds(shop)).status_code == 403


# The reviewer's part --------------------------------------------------------------------------


def test_the_numbers_are_taken_once_when_the_reviewer_opens_it(shop, team, opened, owner_api, run):
    review = review_of(opened, team.ali)
    to_reviewers(shop, opened, run)
    shown = owner_api(team.manager).get(review_url(shop, review)).json()
    assert shown["kpis"]["discipline"]["records"] == 0
    assert shown["kpis"]["start"] == "2026-07-01" and shown["kpis"]["end"] == "2026-09-30"
    assert shown["kpis"]["attendance"] is not None and shown["kpis"]["sales"] is None
    taken = Review.objects.get(pk=review.pk).kpis_at

    DisciplinaryRecord.objects.create(
        company=shop,
        membership=team.ali,
        kind="verbal_warning",
        category="lateness",
        incident_on=date(2026, 9, 10),
        issued_on=date(2026, 9, 11),
        description="Kechikdi",
    )
    shown = owner_api(team.manager).get(review_url(shop, review)).json()
    assert shown["kpis"]["discipline"]["records"] == 0
    assert Review.objects.get(pk=review.pk).kpis_at == taken
    # The numbers as they are now would differ: the snapshot stays as it was.
    assert review_kpis.snapshot(Review.objects.get(pk=review.pk))["discipline"]["records"] == 1


def test_a_raise_becomes_a_pay_change_that_waits_for_approval(shop, paid, owner_api, run, freeze):
    from apps.payroll import queries as payroll_queries

    team = paid
    cycle = run(reviews.open_cycle, make_round(shop, team.manager), by=team.manager)
    review = review_of(cycle, team.ali)
    reviews.send_self(review, by=team.ali, answers=all_ratings(cycle, 4))
    to_reviewers(shop, cycle, run)
    client = owner_api(team.manager)
    body = {
        "answers": all_ratings(cycle, 5, "Muzlatgich jurnalini har kuni to‘ldiradi"),
        "rating": 5,
        "summary": "Kuchli chorak: xatosiz, mijozlar mamnun.",
        "outcome": "raise",
        "raise_percent": "10",
        "effective_on": "2026-11-01",
    }
    response = client.patch(review_url(shop, review), body, format="json")
    assert response.status_code == 200, response.content
    # The manager may propose pay but doesn't see it.
    assert response.json()["pay"] is None and response.json()["can"]["pay"] is True

    response = run(client.post, f"{review_url(shop, review)}publish/")
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["outcome_state"] == "waiting"
    change = JobChange.objects.get(pk=data["job_change"]["id"])
    assert change.status == "proposed" and change.parts == ["pay"]
    assert change.proposed_by == team.manager
    assert change.pay_amount == Decimal("5720000.00")
    assert change.reason == "Performance review «2026, 3rd quarter»: rated 5 of 5."
    # Nothing changed pay: payroll still has the old setup.
    assert payroll_queries.compensation(team.ali, on=NOVEMBER).amount == Decimal("5200000")
    # The owner sees it in Needs you and approves it; it applies on its day.
    queue = owner_api(team.owner).get(f"/api/v1/owner/companies/{shop.pk}/queue/").json()
    assert str(change.pk) in [
        str(item["id"]) for item in queue["items"] if item["kind"] == "lifecycle.job_changes"
    ]
    shown = owner_api(team.owner).get(review_url(shop, review)).json()
    assert shown["pay"]["amount"] == "5200000.00"
    assert shown["job_change"]["pay_after"] == "5720000.00"
    assert shown["job_change"]["can_decide"] is True
    run(job_changes.approve, change, by=team.owner)
    assert payroll_queries.compensation(team.ali, on=NOVEMBER).amount == Decimal("5200000")
    assert owner_api(team.manager).get(review_url(shop, review)).json()["outcome_state"] == (
        "approved"
    )
    freeze(local(NOVEMBER, 0, 5))
    run(job_changes.apply_due)
    assert payroll_queries.compensation(team.ali, on=NOVEMBER).amount == Decimal("5720000")
    assert Review.objects.get(pk=review.pk).job_change.status == "applied"


def test_a_promotion_with_a_raise_is_one_job_change(shop, paid, senior, owner_api, run):
    team = paid
    cycle = run(reviews.open_cycle, make_round(shop, team.manager), by=team.manager)
    to_reviewers(shop, cycle, run)
    review = review_of(cycle, team.vali)
    reviews.save_manager(
        review,
        by=team.manager,
        answers=all_ratings(cycle, 5),
        rating=5,
        outcome="promotion",
        promotion_position=senior,
        raise_percent="15",
        effective_on=NOVEMBER,
    )
    review = run(reviews.publish, review_of(cycle, team.vali), by=team.manager)
    change = review.job_change
    assert change.parts == ["position", "pay"] and change.position == senior
    # 4 800 000 + 15% = 5 520 000.
    assert change.pay_amount == Decimal("5520000.00")
    assert change.status == "proposed"
    team.vali.refresh_from_db()
    assert team.vali.position == team.pharmacist


def test_a_bonus_becomes_a_payroll_proposal(shop, paid, owner_api, run):
    from apps.payroll.models import Adjustment

    team = paid
    cycle = run(reviews.open_cycle, make_round(shop, team.manager), by=team.manager)
    to_reviewers(shop, cycle, run)
    review = review_of(cycle, team.ali)
    reviews.save_manager(
        review,
        by=team.manager,
        answers=all_ratings(cycle, 4),
        rating=4,
        outcome="bonus",
        bonus_amount="500000",
        effective_on=date(2026, 10, 1),
    )
    review = run(reviews.publish, review_of(cycle, team.ali), by=team.manager)
    bonus = Adjustment.objects.get(pk=review.bonus_id)
    assert bonus.kind == "bonus" and bonus.status == "proposed"
    assert bonus.amount == Decimal("500000.00") and bonus.period == date(2026, 10, 1)
    assert bonus.reason.startswith("Performance review «2026, 3rd quarter»")
    shown = owner_api(team.owner).get(review_url(shop, review)).json()
    assert shown["bonus"]["status"] == "proposed" and shown["outcome_state"] == "waiting"


def test_pay_outcomes_need_someone_who_may_propose_pay(shop, team, member, owner_api, run):
    role = AccessRole.objects.create(
        company=shop,
        name="Head",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.REVIEWS_MANAGE, Perm.BRANCHES_ALL],
    )
    team.manager.role = role
    team.manager.save(update_fields=["role"])
    cycle = run(reviews.open_cycle, make_round(shop, team.owner), by=team.owner)
    to_reviewers(shop, cycle, run)
    review = review_of(cycle, team.ali)
    response = owner_api(team.manager).patch(
        review_url(shop, review), {"outcome": "raise", "raise_percent": "10"}, format="json"
    )
    assert response.status_code == 403
    response = owner_api(team.manager).patch(
        review_url(shop, review), {"outcome": "bonus"}, format="json"
    )
    assert response.status_code == 403


def test_an_improvement_plan_has_one_to_three_goals_the_reviewer_marks(
    shop, team, opened, owner_api, api_as, run
):
    to_reviewers(shop, opened, run)
    review = review_of(opened, team.ali)
    client = owner_api(team.manager)
    body = {
        "answers": all_ratings(opened, 2),
        "rating": 2,
        "outcome": "improvement_plan",
        "goals": [
            {"title": "Muzlatgich jurnalini har kuni to‘ldirish", "due_on": "2026-12-31"},
            {"title": "Kechikishlarsiz oy", "due_on": "2026-11-30", "target": "0", "unit": "marta"},
        ],
    }
    assert client.patch(review_url(shop, review), body, format="json").status_code == 200
    too_many = {**body, "goals": body["goals"] * 2}
    assert client.patch(review_url(shop, review), too_many, format="json").status_code == 400
    response = run(client.post, f"{review_url(shop, review)}publish/")
    assert response.status_code == 200, response.content
    goals = response.json()["goals"]
    assert [goal["title"] for goal in goals] == [
        "Muzlatgich jurnalini har kuni to‘ldirish",
        "Kechikishlarsiz oy",
    ]

    goal = ReviewGoal.objects.get(pk=goals[1]["id"])
    path = f"/api/v1/owner/companies/{shop.pk}/lifecycle/review-goals/{goal.pk}/"
    response = client.patch(path, {"status": "done", "progress": "0"}, format="json")
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "done"
    # The person sees their open goals; the reached one is gone from the list.
    listed = api_as(team.ali).get(mine(shop)).json()
    assert [row["id"] for row in listed["goals"]] == [goals[0]["id"]]
    # Someone who can't read the review can't mark its goals.
    assert (
        owner_api(team.accountant).patch(path, {"status": "open"}, format="json").status_code == 403
    )


def test_publishing_needs_every_rating_and_the_overall_one(shop, team, opened, run):
    to_reviewers(shop, opened, run)
    review = review_of(opened, team.ali)
    with pytest.raises(reviews.DomainError, match="Rate every question"):
        reviews.publish(review, by=team.manager)
    reviews.save_manager(review, by=team.manager, answers=all_ratings(opened, 4))
    with pytest.raises(reviews.DomainError, match="overall rating"):
        reviews.publish(review_of(opened, team.ali), by=team.manager)
    reviews.save_manager(review_of(opened, team.ali), by=team.manager, rating=4, outcome="raise")
    with pytest.raises(reviews.DomainError, match="percentage"):
        reviews.publish(review_of(opened, team.ali), by=team.manager)
    # The owner reads it but doesn't write it.
    with pytest.raises(reviews.PermissionDenied):
        reviews.save_manager(review_of(opened, team.ali), by=team.owner, rating=5)


def test_the_person_reads_the_published_review_and_acknowledges_it(shop, team, opened, api_as, run):
    review = review_of(opened, team.ali)
    reviews.send_self(review, by=team.ali, answers=all_ratings(opened, 4))
    to_reviewers(shop, opened, run)
    client = api_as(team.ali)
    before = client.get(mine(shop, f"{review.pk}/")).json()
    assert before["manager_answers"] is None and before["rating"] is None
    reviews.save_manager(
        review_of(opened, team.ali),
        by=team.manager,
        answers=all_ratings(opened, 5),
        rating=5,
        summary="Zo‘r ish",
    )
    run(reviews.publish, review_of(opened, team.ali), by=team.manager)
    notice = Notification.objects.get(
        recipient=team.ali, kind=review_notify.REVIEW, title="Your performance review is ready"
    )
    assert notice.app_screen == f"lifecycle.review:{review.pk}"

    after = client.get(mine(shop, f"{review.pk}/")).json()
    assert after["state"] == "published" and after["rating"] == 5
    assert after["summary"] == "Zo‘r ish"
    assert after["kpis"]["start"] == "2026-07-01"
    listed = client.get(mine(shop)).json()
    assert listed["open"] == [] and [row["id"] for row in listed["past"]] == [review.pk]
    response = client.post(mine(shop, f"{review.pk}/acknowledge/"))
    assert response.status_code == 200 and response.json()["acknowledged_at"]


# Results, scope and the rest ------------------------------------------------------------------


def test_results_count_ratings_outcomes_and_the_cost_for_people_who_see_pay(
    shop, paid, owner_api, run
):
    team = paid
    cycle = run(reviews.open_cycle, make_round(shop, team.manager), by=team.manager)
    to_reviewers(shop, cycle, run)
    reviews.save_manager(
        review_of(cycle, team.ali),
        by=team.manager,
        answers=all_ratings(cycle, 4),
        rating=4,
        outcome="raise",
        raise_percent="10",
        effective_on=NOVEMBER,
    )
    run(reviews.publish, review_of(cycle, team.ali), by=team.manager)
    reviews.save_manager(
        review_of(cycle, team.vali),
        by=team.manager,
        answers=all_ratings(cycle, 5),
        rating=5,
        outcome="bonus",
        bonus_amount="300000",
    )
    run(reviews.publish, review_of(cycle, team.vali), by=team.manager)

    path = f"{rounds(shop)}{cycle.pk}/results/"
    data = owner_api(team.owner).get(path).json()
    assert data["published"] == 2 and data["average"] == "4.5"
    assert data["spread"] == {"1": 0, "2": 0, "3": 0, "4": 1, "5": 1}
    assert data["outcomes"]["raise"] == 1 and data["outcomes"]["bonus"] == 1
    assert data["cost"]["raises_waiting"] == "520000.00"
    assert data["cost"]["bonuses_waiting"] == "300000.00"
    assert data["cost"]["raises_monthly"] == "0.00"
    [chilonzor] = data["by_branch"]
    assert chilonzor["people"] == 2 and chilonzor["raise_cost"] == "520000.00"
    assert data["questions"][0]["manager_average"] == "4.5"
    # The manager runs reviews but doesn't see pay.
    data = owner_api(team.manager).get(path).json()
    assert data["cost"] is None and data["by_branch"][0]["raise_cost"] is None


def test_close_ends_a_round_and_leaves_the_rest_unpublished(shop, team, opened, owner_api, run):
    to_reviewers(shop, opened, run)
    response = run(owner_api(team.manager).post, f"{rounds(shop)}{opened.pk}/close/")
    assert response.status_code == 200 and response.json()["status"] == "closed"
    with pytest.raises(reviews.DomainError):
        reviews.save_manager(review_of(opened, team.ali), by=team.manager, rating=3)
    with pytest.raises(reviews.DomainError):
        reviews.send_self(review_of(opened, team.ali), by=team.ali, answers=all_ratings(opened))


def test_reassigning_and_removing_before_publishing(shop, team, opened, owner_api, run):
    review = review_of(opened, team.sara)
    path = f"{review_url(shop, review)}reviewer/"
    response = owner_api(team.owner).post(path, {"reviewer_id": team.manager.pk}, format="json")
    assert response.status_code == 200, response.content
    assert response.json()["reviewer"]["id"] == team.manager.pk
    # Someone who doesn't run reviews can't be one.
    response = owner_api(team.owner).post(path, {"reviewer_id": team.accountant.pk}, format="json")
    assert response.status_code == 400
    response = owner_api(team.owner).delete(review_url(shop, review))
    assert response.status_code == 204
    assert not Review.objects.filter(pk=review.pk).exists()


def test_the_calendar_the_badge_and_the_export(shop, team, opened, run):
    items = review_queries.calendar_deadlines(
        shop, date(2026, 10, 1), date(2026, 11, 30), team.manager
    )
    assert [item.start for item in items] == [SELF_DUE, MANAGER_DUE]
    assert items[0].url == f"lifecycle/reviews/{opened.pk}"
    assert review_queries.to_write_count(team.manager) == 0
    to_reviewers(shop, opened, run)
    assert review_queries.to_write_count(team.manager) == 2
    reviews.save_manager(
        review_of(opened, team.ali), by=team.manager, answers=all_ratings(opened, 4), rating=4
    )
    run(reviews.publish, review_of(opened, team.ali), by=team.manager)
    assert review_queries.to_write_count(team.manager) == 1
    rows = list(review_queries.export_rows(team.manager, {"round": opened.pk}))
    assert [row["person"] for row in rows] == ["Ali Valiyev"]
    assert rows[0]["rating"] == 4 and rows[0]["bonus"] is None
    # The owner can read every review; the accountant none.
    assert list(review_queries.export_rows(team.accountant, {})) == []


# "Draft my summary" ----------------------------------------------------------------------------
# Claude Haiku 5.5 suggests the summary from the questions, both sides' answers and the numbers
# only (no name, no pay), through the AI client and its budget; nothing is saved; only while the
# AI module is on, to the reviewer who may use AI; a refusal, the day's cap, AI_FAKE's draft.

SAID = "Kassa doim to‘g‘ri chiqdi"
NOTED = "Muddati o‘tayotgan dorilarni o‘z vaqtida qaytardi"


@pytest.fixture
def fake_claude(monkeypatch, settings):
    settings.ANTHROPIC_API_KEY = "sk-test"
    settings.AI_FAKE = False
    fake = FakeAnthropic()
    monkeypatch.setattr("apps.ai.client.get_client", lambda: fake)
    availability.reset_breaker()
    return fake


def ai_on(company, manager: Membership | None = None) -> None:
    """The AI module on with an owner's consent; the manager's role may use AI."""
    company.features = sorted({*company.features, Feature.AI})
    company.save(update_fields=["features"])
    row = conf.get_settings(company)
    row.enabled = True
    row.save()
    if manager is not None:
        role = manager.role
        role.permissions = sorted({*role.permissions, Perm.AI_USE})
        role.save(update_fields=["permissions"])


def written(shop, team, opened, run) -> Review:
    """Ali sent his answers; the manager rated every question and left a comment on one."""
    first = next(q["id"] for q in opened.questions if q["kind"] == "rating")
    own = all_ratings(opened, 4)
    own[first]["text"] = SAID
    reviews.send_self(review_of(opened, team.ali), by=team.ali, answers=own)
    to_reviewers(shop, opened, run)
    answers = all_ratings(opened, 5)
    answers[first]["text"] = NOTED
    reviews.save_manager(review_of(opened, team.ali), by=team.manager, answers=answers)
    return review_of(opened, team.ali)


def draft_url(company, review) -> str:
    return f"{review_url(company, review)}draft-summary/"


def test_the_reviewer_gets_a_suggestion_from_the_answers_and_numbers_only(
    shop, paid, opened, owner_api, run, fake_claude
):
    team = paid
    ai_on(shop, team.manager)
    review = written(shop, team, opened, run)
    client = owner_api(team.manager)
    assert client.get(review_url(shop, review)).json()["can"]["draft_summary"] is True

    said = "Siz kassani  doim to‘g‘ri yuritdingiz.\nKeyingi chorakda o‘qishga e’tibor bering."
    fake_claude.script(FakeAnthropic.json({"summary": said}, model="claude-haiku-5-5"))
    response = client.post(draft_url(shop, review), format="json")
    assert response.status_code == 200, response.content
    # One paragraph, spaces tidied.
    assert response.json() == {"summary": " ".join(said.split()), "engine": "claude"}

    [request] = fake_claude.requests
    assert request["model"] == "claude-haiku-5-5"
    assert request["output_config"]["effort"] == "low"
    assert request["output_config"]["format"]["type"] == "json_schema"
    # Thinking stays adaptive (left out), no sampling settings, no fallback on Haiku.
    for absent in ("temperature", "top_p", "top_k", "thinking", "fallbacks"):
        assert absent not in request
    text = request["messages"][0]["content"][0]["text"]
    assert SAID in text and NOTED in text
    assert 'rating="4"' in text and 'rating="5"' in text
    assert "Shared tasks" in text or "Disciplinary records" in text
    # Never the person's name or their pay.
    assert str(team.ali).split()[0] not in text
    assert "5200000" not in text and "5 200 000" not in text
    # Nothing is saved until the reviewer keeps it; the call is counted on the budget.
    assert Review.objects.get(pk=review.pk).summary == ""
    usage = AIUsage.objects.get(company=shop)
    assert usage.feature == review_ai.FEATURE and usage.membership_id == team.manager.pk


def test_the_draft_is_in_the_readers_language_and_waits_for_the_persons_answers(
    shop, team, opened, run
):
    to_reviewers(shop, opened, run)
    review = review_of(opened, team.vali)
    text = review_ai.prompt(review, language="ru", viewer=team.manager)
    assert "<language>Russian</language>" in text
    # Vali never sent his answers: his side reads "no answer".
    assert text.count("<employee>no answer</employee>") == len(opened.questions)


def test_no_draft_without_ai_for_someone_else_or_before_the_reviewers_part(
    shop, team, opened, owner_api, run, fake_claude
):
    # The self stage: nothing to write yet.
    ai_on(shop, team.manager)
    review = review_of(opened, team.ali)
    client = owner_api(team.manager)
    assert client.get(review_url(shop, review)).json()["can"]["draft_summary"] is False
    assert client.post(draft_url(shop, review)).status_code == 403

    review = written(shop, team, opened, run)
    # The owner reads Ali's review but doesn't write it.
    owner = owner_api(team.owner)
    assert owner.get(review_url(shop, review)).json()["can"]["draft_summary"] is False
    assert owner.post(draft_url(shop, review)).status_code == 403

    # The AI module off: no button, and asking anyway says so.
    row = conf.get_settings(shop)
    row.enabled = False
    row.save()
    assert client.get(review_url(shop, review)).json()["can"]["draft_summary"] is False
    response = client.post(draft_url(shop, review))
    assert response.status_code == 400
    assert "isn't available" in response.json()["detail"]

    # On again, but the manager's role may not use AI.
    row.enabled = True
    row.save()
    role = team.manager.role
    role.permissions = [perm for perm in role.permissions if perm != Perm.AI_USE]
    role.save(update_fields=["permissions"])
    assert client.get(review_url(shop, review)).json()["can"]["draft_summary"] is False
    assert client.post(draft_url(shop, review)).status_code == 403
    assert fake_claude.requests == []


def test_a_refusal_and_the_days_cap_leave_the_summary_to_the_reviewer(
    shop, team, opened, owner_api, run, fake_claude, monkeypatch
):
    ai_on(shop, team.manager)
    review = written(shop, team, opened, run)
    client = owner_api(team.manager)
    fake_claude.script(FakeAnthropic.refusal(model="claude-haiku-5-5"))
    response = client.post(draft_url(shop, review))
    assert response.status_code == 400
    assert "couldn't write a draft" in response.json()["detail"]

    monkeypatch.setattr(review_ai, "DRAFTS_A_DAY", 1)
    response = client.post(draft_url(shop, review))
    assert response.status_code == 400
    assert "enough drafts" in response.json()["detail"]
    assert len(fake_claude.requests) == 1


def test_with_ai_fake_a_canned_draft_follows_the_reviewers_ratings(
    shop, team, opened, owner_api, run, settings
):
    settings.ANTHROPIC_API_KEY = ""
    settings.AI_FAKE = True
    ai_on(shop, team.manager)
    review = written(shop, team, opened, run)
    rated = [q["id"] for q in opened.questions if q["kind"] == "rating"]
    answers = dict(review.manager_answers)
    answers[rated[-1]] = {"rating": 3, "text": ""}
    reviews.save_manager(review, by=team.manager, answers=answers)
    response = owner_api(team.manager).post(draft_url(shop, review))
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["engine"] == "fake"
    # The best rated question's subject first, the weakest next, in the reader's language.
    with translation.override(response["Content-Language"]):
        topics = {q["id"]: q["text"].split(":")[0].lower() for q in reviews.shown_questions(opened)}
    summary = data["summary"].lower()
    assert summary.index(topics[rated[0]]) < summary.index(topics[rated[-1]])
    assert not AIUsage.objects.filter(company=shop).exists()
