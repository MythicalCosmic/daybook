"""Hiring's rules: vacancies, applying in the bot, and the way from the first answer to the
hire (docs/PLAN-OWNER.md §3.11, v11 package G)."""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.hr.hiring import queries, questions, services
from apps.hr.hiring.services import LinkState
from apps.hr.models import Applicant, ApplicantEvent, EmployeeProfile, Vacancy
from apps.hr.tests.conftest import DAY
from apps.hr.tests.hiring.conftest import jpeg
from apps.inbox.models import Notification
from apps.members.models import Membership

pytestmark = pytest.mark.django_db
Stage = Applicant.Stage


def actions(target) -> list[str]:
    return list(
        AuditLog.objects.filter(target_type=target._meta.model_name, target_id=target.pk)
        .order_by("pk")
        .values_list("action", flat=True)
    )


# Vacancies --------------------------------------------------------------------------------


def test_a_vacancy_starts_as_a_draft_and_opens_when_published(shop, hirers, vacancy):
    draft = vacancy(publish=False)
    assert draft.status == Vacancy.Status.DRAFT and draft.published_at is None
    assert len(draft.code) == 10 and draft.code.isalnum()
    assert draft.start_param() == f"job_{draft.code}"
    assert draft.start_param(qr=True) == f"job_{draft.code}-q"
    [yes_no, choice, number] = draft.questions
    assert yes_no["kind"] == "yes_no" and yes_no["required"] and yes_no["id"].startswith("q")
    assert choice["options"] == ["Kunduzgi", "Tungi", "Farqi yo‘q"]
    assert number["required"] is False
    assert len({q["id"] for q in draft.questions}) == 3

    published = vacancy(title="  Kassir   (kechki) ")
    assert published.status == Vacancy.Status.OPEN and published.published_at is not None
    assert published.title == "Kassir (kechki)"
    assert actions(published) == ["hr.vacancy_created"]


def test_bot_links_need_the_bot_username(settings, vacancy):
    opening = vacancy()
    settings.EMPLOYEE_BOT_USERNAME = ""
    assert opening.bot_link() == ""
    settings.EMPLOYEE_BOT_USERNAME = "daybook_bot"
    assert opening.bot_link() == f"https://t.me/daybook_bot?start=job_{opening.code}"
    assert opening.bot_link(qr=True).endswith(f"job_{opening.code}-q")


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"title": " "}, "title"),
        ({"salary_from": 5_000_000, "salary_to": 3_000_000}, "upper end"),
        ({"salary_from": -1}, "positive"),
        ({"closes_on": DAY - timedelta(days=1)}, "past"),
        ({"opens_on": DAY + timedelta(days=5), "closes_on": DAY + timedelta(days=2)}, "before"),
        ({"questions": [{"text": "Smena?", "kind": "choice", "options": ["Kunduzgi"]}]}, "two"),
        ({"questions": [{"text": "", "kind": "text"}]}, "no text"),
        ({"questions": [{"text": "Nima?", "kind": "essay"}]}, "unknown kind"),
        ({"questions": [{"text": f"Savol {n}?"} for n in range(9)]}, "at most 8"),
        (
            {"questions": [{"text": "Smena?", "kind": "choice", "options": ["Tun", "tun"]}]},
            "twice",
        ),
    ],
)
def test_a_vacancy_is_checked(vacancy, fields, message):
    with pytest.raises(DomainError, match=message):
        vacancy(**fields)


def test_a_branch_hirer_posts_only_for_their_branches(hirers, vacancy, yunusobod):
    with pytest.raises(PermissionDenied):
        vacancy(branch=yunusobod, by=hirers.scout)
    with pytest.raises(DomainError, match="one of your branches"):
        vacancy(branch=None, by=hirers.scout)
    assert vacancy(by=hirers.scout).created_by == hirers.scout
    # Someone with every branch may post a vacancy for the whole company.
    assert vacancy(branch=None, by=hirers.manager).branch is None


def test_only_hirers_post_vacancies(shop, hirers):
    with pytest.raises(PermissionDenied):
        services.create_vacancy(shop, by=hirers.accountant, title="Farmatsevt")


def test_open_pause_close_and_open_again(hirers, vacancy, freeze):
    opening = vacancy(publish=False)
    with pytest.raises(DomainError, match="Only an open vacancy"):
        services.set_status(opening, "paused", by=hirers.owner)
    for status in ("open", "paused", "open", "closed", "open"):
        opening = services.set_status(opening, status, by=hirers.manager)
        assert opening.status == status
    assert opening.closed_at is None
    assert actions(opening) == [
        "hr.vacancy_created",
        "hr.vacancy_opened",
        "hr.vacancy_paused",
        "hr.vacancy_opened",
        "hr.vacancy_closed",
        "hr.vacancy_opened",
    ]
    # Past its last day, it opens only once the day changes.
    services.update_vacancy(opening, by=hirers.owner, closes_on=DAY)
    services.set_status(opening, "closed", by=hirers.owner)
    freeze(timezone.now() + timedelta(days=2))
    with pytest.raises(DomainError, match="passed"):
        services.set_status(opening, "open", by=hirers.owner)


def test_a_change_is_audited_with_the_fields(hirers, vacancy):
    opening = vacancy()
    services.update_vacancy(opening, by=hirers.owner, title="Farmatsevt", description="")
    assert actions(opening) == ["hr.vacancy_created"]  # nothing changed
    services.update_vacancy(opening, by=hirers.owner, title="Katta farmatsevt", salary_to=6e6)
    row = AuditLog.objects.filter(action="hr.vacancy_changed").get()
    assert row.details["fields"] == ["salary_to", "title"]


def test_a_vacancy_with_applicants_is_closed_not_deleted(hirers, vacancy, applicant):
    empty = vacancy(publish=False)
    services.delete_vacancy(empty, by=hirers.owner)
    assert not Vacancy.objects.filter(pk=empty.pk).exists()
    assert AuditLog.objects.filter(action="hr.vacancy_deleted").exists()

    wanted = vacancy()
    applicant(wanted)
    with pytest.raises(DomainError, match="Close it instead"):
        services.delete_vacancy(wanted, by=hirers.owner)


# Opening the link and applying ------------------------------------------------------------


def stranger(telegram_id=7100, **fields) -> User:
    return User.objects.create(username=f"tg{telegram_id}", telegram_id=telegram_id, **fields)


def test_what_a_link_answers(hirers, vacancy, applicant, freeze):
    person = stranger()
    assert services.open_link(person, "nope").state == LinkState.GONE
    draft = vacancy(publish=False)
    assert services.open_link(person, draft.code).state == LinkState.DRAFT
    later = vacancy(opens_on=DAY + timedelta(days=3))
    assert services.open_link(person, later.code).state == LinkState.NOT_YET
    paused = services.set_status(vacancy(), "paused", by=hirers.owner)
    assert services.open_link(person, paused.code).state == LinkState.PAUSED
    closed = services.set_status(vacancy(), "closed", by=hirers.owner)
    assert services.open_link(person, closed.code).state == LinkState.CLOSED
    ending = vacancy(closes_on=DAY)
    assert services.open_link(person, ending.code).state == LinkState.OK
    freeze(timezone.now() + timedelta(days=1))
    assert services.open_link(person, ending.code).state == LinkState.CLOSED

    opening = vacancy()
    opened = services.open_link(person, f"{opening.code}-q")
    assert opened.state == LinkState.OK and opened.source == "qr"
    assert services.open_link(person, opening.code).source == "link"
    mine = applicant(opening, person.telegram_id)
    again = services.open_link(person, opening.code)
    assert again.state == LinkState.APPLIED and again.applicant == mine


def test_people_who_work_here_dont_apply(staff, vacancy):
    opening = vacancy()
    assert services.open_link(staff.ali.user, opening.code).state == LinkState.MEMBER
    with pytest.raises(DomainError, match="already work here"):
        services.apply(opening.pk, staff.ali.user, name="Ali Valiyev", phone="", answers=[])


def test_link_opens_count_once_a_day_per_person(vacancy):
    opening = vacancy()
    first, second = stranger(7101), stranger(7102)
    for person in (first, first, second):
        services.open_link(person, opening.code)
    opening.refresh_from_db()
    assert opening.link_opens == 2


def test_applying_makes_a_new_applicant_and_tells_the_team(hirers, vacancy, applicant):
    opening = vacancy()
    answers = [
        questions.answer_row(opening.questions[0], "yes"),
        questions.answer_row(opening.questions[1], "Tungi"),
        questions.answer_row(opening.questions[2], ""),
    ]
    made = applicant(opening, 7200, answers=answers, source="qr", phone="+998901112200")
    assert made.stage == Stage.NEW and made.stage_changed_at is not None
    assert made.source == "qr" and made.phone == "+998901112200"
    assert made.telegram_username == "user7200" and made.language == "uz"
    assert [row["answer"] for row in made.answers] == ["yes", "Tungi", ""]
    assert [event.kind for event in made.events.all()] == ["applied"]
    row = AuditLog.objects.get(action="hr.applicant_applied")
    assert row.actor == made.user and row.details == {"vacancy": opening.pk, "source": "qr"}
    # Everyone running hiring who sees Chilonzor; the Chilonzor-only scout too; not the
    # accountant (no hr.hiring).
    told = Notification.objects.filter(kind="hr.applicant", target_id=made.pk)
    assert set(told.values_list("recipient_id", flat=True)) == {
        hirers.owner.pk,
        hirers.manager.pk,
        hirers.scout.pk,
        hirers.recruiter.pk,
    }
    notice = told.first()
    assert "Aziza Karimova" in notice.title  # in each reader's language
    assert notice.url == f"/c/{opening.company_id}/hr/hiring/{opening.pk}?applicant={made.pk}"


def test_the_team_of_another_branch_doesnt_hear(hirers, vacancy, applicant, yunusobod):
    made = applicant(vacancy(branch=yunusobod), 7201)
    told = set(
        Notification.objects.filter(kind="hr.applicant", target_id=made.pk).values_list(
            "recipient_id", flat=True
        )
    )
    assert hirers.scout.pk not in told and hirers.owner.pk in told


def test_one_application_per_person_and_vacancy(vacancy, applicant):
    opening = vacancy()
    applicant(opening, 7300)
    with pytest.raises(DomainError, match="already applied"):
        applicant(opening, 7300)
    assert Applicant.objects.filter(vacancy=opening).count() == 1


def test_a_closed_vacancy_refuses_new_applicants(hirers, vacancy, applicant):
    opening = vacancy()
    applicant(opening, 7400)
    services.set_status(opening, "closed", by=hirers.owner)
    with pytest.raises(DomainError, match="closed"):
        applicant(opening, 7401)
    services.set_status(opening, "open", by=hirers.owner)
    services.set_status(opening, "paused", by=hirers.owner)
    with pytest.raises(DomainError, match="paused"):
        applicant(opening, 7402)
    assert Applicant.objects.filter(vacancy=opening).count() == 1


def test_a_name_is_two_words_of_letters(vacancy, applicant):
    opening = vacancy()
    for bad in ("Aziza", "A1 B2", "http://spam.example", "@aziza karimova", "  "):
        with pytest.raises(DomainError, match="first and last name"):
            applicant(opening, 7500, name=bad)
    assert services.clean_name("  o‘g‘iloy   jo‘rayeva ") == "o‘g‘iloy jo‘rayeva"
    assert services.clean_name("Ким Елена") == "Ким Елена"
    assert services.clean_name("Anna-Maria O'Neil") == "Anna-Maria O'Neil"


def test_a_person_applies_at_most_five_times_a_day(vacancy, applicant):
    for number in range(services.MAX_APPLICATIONS_A_DAY):
        applicant(vacancy(title=f"Farmatsevt {number}"), 7600)
    person = User.objects.get(telegram_id=7600)
    later = vacancy(title="Kassir")
    assert services.open_link(person, later.code).state == LinkState.LIMIT
    with pytest.raises(DomainError, match="tomorrow"):
        applicant(later, 7600)


def test_a_diploma_photo_is_kept_when_the_vacancy_asks(vacancy, applicant):
    asking = vacancy(asks_document=True)
    made = applicant(asking, 7700, document=jpeg())
    assert made.document.name.endswith(".jpg") and made.document.storage.exists(made.document.name)
    plain = applicant(vacancy(title="Kuryer"), 7701, document=jpeg())
    assert not plain.document  # it didn't ask


def test_answers_keep_their_shape(vacancy, applicant):
    made = applicant(
        vacancy(),
        7800,
        answers=[{"id": "q1", "text": "x" * 900, "kind": "text", "answer": "y" * 900}, "junk"],
    )
    [row] = made.answers
    assert len(row["text"]) == questions.TEXT_MAX and len(row["answer"]) == questions.ANSWER_MAX


# The pipeline -----------------------------------------------------------------------------


def test_moving_on_and_back(hirers, vacancy, applicant, sent_messages, committed):
    made = applicant(vacancy(), 8000, language="en")
    with committed():
        made = services.move(made, Stage.SCREENING, by=hirers.manager)
    assert made.stage == Stage.SCREENING and sent_messages == []  # nothing to say yet
    with committed():
        made = services.move(made, Stage.INTERVIEW, by=hirers.manager, message="Seshanba 10:00")
    [invite] = sent_messages
    assert invite["chat_id"] == 8000 and invite["bot"] == "employee"
    assert "interview" in invite["text"] and "Seshanba 10:00" in invite["text"]
    with committed():
        made = services.move(made, Stage.SCREENING, by=hirers.owner, notify=False)
    assert len(sent_messages) == 1
    events = list(made.events.order_by("pk").values_list("kind", "from_stage", "to_stage"))
    assert events == [
        ("applied", "", "new"),
        ("moved", "new", "screening"),
        ("moved", "screening", "interview"),
        ("moved", "interview", "screening"),
    ]
    interview = made.events.get(to_stage="interview")
    assert interview.by == hirers.manager and interview.notified
    assert interview.message == "Seshanba 10:00"
    assert actions(made).count("hr.applicant_moved") == 3


def test_an_offer_is_told_and_a_message_goes_with_any_move(
    hirers, vacancy, applicant, sent_messages, committed
):
    made = applicant(vacancy(), 8001, language="en")
    with committed():
        services.move(made, Stage.OFFER, by=hirers.owner)
        services.move(made, Stage.SCREENING, by=hirers.owner, message="Пришлите копию диплома")
    offer, note = sent_messages
    assert "offer you the job" in offer["text"]
    assert "Пришлите копию диплома" in note["text"]


def test_hired_and_rejected_have_their_own_actions(hirers, vacancy, applicant):
    made = applicant(vacancy(), 8002)
    with pytest.raises(DomainError, match="Hire"):
        services.move(made, Stage.HIRED, by=hirers.owner)
    with pytest.raises(DomainError, match="Reject"):
        services.move(made, Stage.REJECTED, by=hirers.owner)


def test_rejecting_needs_a_reason_and_tells_kindly(
    hirers, vacancy, applicant, sent_messages, committed
):
    made = applicant(vacancy(), 8003)
    with pytest.raises(DomainError, match="why"):
        services.reject(made, by=hirers.owner, reason=" ")
    with committed():
        made = services.reject(made, by=hirers.owner, reason="Diplom yo‘q", message="Omad!")
    assert made.stage == Stage.REJECTED and made.rejected_reason == "Diplom yo‘q"
    [refusal] = sent_messages
    assert "Omad!" in refusal["text"] and "Diplom" not in refusal["text"]  # the reason stays inside
    with pytest.raises(DomainError, match="already turned down"):
        services.reject(made, by=hirers.owner, reason="Yana")
    # Reconsidered: back in the pipeline, the reason goes.
    made = services.move(made, Stage.SCREENING, by=hirers.owner)
    assert made.rejected_reason == ""
    quiet = applicant(vacancy(title="Kassir"), 8004)
    with committed():
        services.reject(quiet, by=hirers.owner, reason="Tajriba kam", notify=False)
    assert len(sent_messages) == 1
    assert ApplicantEvent.objects.get(applicant=quiet, to_stage="rejected").text == "Tajriba kam"


def test_hire_makes_an_approved_member_with_the_vacancys_job(
    hirers, vacancy, applicant, sent_messages, chilonzor, committed
):
    made = applicant(
        vacancy(position=hirers.cashier, title="Kassir"),
        8100,
        name="Dilfuza Raximova",
        language="en",
    )
    with committed():
        made = services.hire(made, by=hirers.owner, message="Dushanba 09:00 da keling")
    member = made.membership
    assert made.stage == Stage.HIRED and made.hired_at is not None
    assert member.status == Membership.Status.APPROVED and member.user == made.user
    assert member.position == hirers.cashier and member.role.name == "Cashier"
    assert member.home_branch == chilonzor and list(member.branches.all()) == [chilonzor]
    assert (member.first_name, member.last_name) == ("Dilfuza", "Raximova")
    assert not member.is_onboarded  # they create their account like anyone else
    # The normal onboarding: HR's profile, and the usual welcome after our message.
    assert EmployeeProfile.objects.filter(membership=member).exists()
    texts = [message["text"] for message in sent_messages if message["chat_id"] == 8100]
    assert "Congratulations" in texts[0] and "Dushanba 09:00" in texts[0]
    assert any("was approved" in text for text in texts[1:])
    assert actions(made)[-1] == "hr.applicant_hired"
    assert AuditLog.objects.filter(
        action=AuditLog.Action.MEMBER_APPROVED, target_id=member.pk
    ).exists()


def test_the_hirer_gives_only_a_role_they_hold_themselves(hirers, vacancy, applicant):
    # The Manager role sells nothing itself, so it can't hand out the cashier's access.
    cashier = vacancy(position=hirers.cashier, title="Kassir")
    assert services.hire_blocker(hirers.manager, cashier) == (
        "You can only give a role whose permissions you have yourself."
    )
    assert services.hire_blocker(hirers.owner, cashier) is None
    assert "approve join requests" in services.hire_blocker(hirers.recruiter, cashier)
    with pytest.raises(PermissionDenied, match="role whose permissions"):
        services.hire(applicant(cashier, 8110), by=hirers.manager)
    assert not Membership.objects.filter(user__telegram_id=8110).exists()


def test_a_position_without_a_role_gives_the_default_one(hirers, vacancy, applicant):
    made = services.hire(applicant(vacancy(), 8101), by=hirers.owner)
    assert made.membership.role.is_default and made.membership.position == hirers.pharmacist


def test_hire_happens_once(hirers, vacancy, applicant):
    made = services.hire(applicant(vacancy(), 8102), by=hirers.owner)
    with pytest.raises(DomainError, match="already hired"):
        services.hire(made, by=hirers.owner)
    with pytest.raises(DomainError, match="already hired"):
        services.move(made, Stage.OFFER, by=hirers.owner)
    assert Membership.objects.filter(user=made.user, company=made.company).count() == 1


def test_hiring_needs_the_right_to_let_people_in(hirers, vacancy, applicant):
    made = applicant(vacancy(), 8103)
    with pytest.raises(PermissionDenied, match="approve join requests"):
        services.hire(made, by=hirers.recruiter)
    with pytest.raises(PermissionDenied):
        services.hire(made, by=hirers.accountant)
    assert not Membership.objects.filter(user=made.user).exists()


def test_a_branch_hirer_runs_only_their_branches(hirers, vacancy, applicant, yunusobod):
    far = applicant(vacancy(branch=yunusobod), 8104)
    for act in (
        lambda: services.move(far, Stage.SCREENING, by=hirers.scout),
        lambda: services.reject(far, by=hirers.scout, reason="x"),
        lambda: services.hire(far, by=hirers.scout),
        lambda: services.add_note(far, by=hirers.scout, text="x"),
    ):
        with pytest.raises(PermissionDenied):
            act()
    near = services.hire(applicant(vacancy(), 8105), by=hirers.scout)
    assert near.membership.home_branch.name == "Chilonzor"


def test_a_company_wide_vacancy_asks_where_they_work(hirers, vacancy, applicant, yunusobod):
    made = applicant(vacancy(branch=None), 8106)
    with pytest.raises(DomainError, match="branch"):
        services.hire(made, by=hirers.owner)
    made = services.hire(made, by=hirers.owner, branch=yunusobod)
    assert made.membership.home_branch == yunusobod


def test_a_rejected_applicant_is_reconsidered_before_the_hire(hirers, vacancy, applicant):
    made = services.reject(applicant(vacancy(), 8107), by=hirers.owner, reason="Kech qoldi")
    with pytest.raises(DomainError, match="back to the pipeline"):
        services.hire(made, by=hirers.owner)


def test_someone_who_joined_meanwhile_isnt_hired_again(hirers, vacancy, applicant, member, shop):
    made = applicant(vacancy(), 8108)
    member(shop, user=made.user)
    with pytest.raises(DomainError, match="already works here"):
        services.hire(made, by=hirers.owner)


def test_a_waiting_join_request_becomes_the_hire(hirers, vacancy, applicant, shop):
    made = applicant(vacancy(), 8109)
    waiting = Membership.objects.create(company=shop, user=made.user)
    made = services.hire(made, by=hirers.owner)
    waiting.refresh_from_db()
    assert made.membership == waiting and waiting.status == Membership.Status.APPROVED


def test_notes_go_into_the_history(hirers, vacancy, applicant):
    made = applicant(vacancy(), 8200)
    with pytest.raises(DomainError):
        services.add_note(made, by=hirers.owner, text="  ")
    note = services.add_note(made, by=hirers.manager, text="Qo‘ng‘iroq qildim, ertaga keladi")
    assert note.kind == "note" and note.by == hirers.manager
    assert actions(made)[-1] == "hr.applicant_noted"


# What members see -------------------------------------------------------------------------


def test_counts_scope_and_search(hirers, vacancy, applicant, yunusobod):
    near = vacancy()
    far = vacancy(branch=yunusobod, title="Kassir")
    applicant(near, 8300, name="Sanjar Qosimov")
    second = applicant(near, 8301, name="Елена Ким", phone="+998935551234")
    applicant(far, 8302, name="Nilufar Sobirova")
    services.move(second, Stage.INTERVIEW, by=hirers.owner, notify=False)

    assert queries.new_count(hirers.owner) == 2
    assert queries.new_count(hirers.scout) == 1  # only Chilonzor's
    assert queries.new_count(hirers.accountant) == 0
    counted = queries.with_counts(queries.vacancies(near.company, branch_ids=None)).get(pk=near.pk)
    assert (counted.count_new, counted.count_interview, counted.count_total) == (1, 1, 2)
    assert queries.vacancy(near.company, far.pk, branch_ids=[near.branch_id]) is None

    [hit] = queries.search(hirers.owner, "5551234", 5)
    assert hit.title == "Елена Ким" and hit.url.endswith(f"?applicant={second.pk}")
    assert queries.search(hirers.scout, "Nilufar", 5) == []
    assert [hit.title for hit in queries.search(hirers.owner, "user830", 5)]


def test_number_answers():
    assert questions.number_answer("3") == "3"
    assert questions.number_answer("2,5 yil") == "2.5"
    assert questions.number_answer("5 000 000 so‘m") == "5000000"
    assert questions.number_answer("5.000.000") == "5000000"
    assert questions.number_answer("10 лет") == "10"
    for bad in ("", "uch", "2-3", "-1", "3 4 5"):
        assert questions.number_answer(bad) is None, bad
