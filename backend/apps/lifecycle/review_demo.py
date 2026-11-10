"""Demo data of performance reviews (the story is apps/core/demo_plan.py), run from the lifecycle
demo's `finish` before its leaving story, once the other demos have made their rows (pay,
tasks, attendance).

Both pharmacies review the last full quarter:

- **Chilonzor** (closed): Bekzod opened it about four weeks before the 1st of this month; everyone
  answered (Jasur a day late), Bekzod and Dilnoza wrote their parts and published them, and the
  round closed. Sardor and Madina got raises (10 % and 8 %) that Dilnoza approved and that took
  effect on the 1st; Gulnora a bonus on this month's payslip, approved; Otabek an improvement
  plan with three goals (one reached). Most have read their review; Jasur hasn't.
- **Yunusobod** (open, people still answering): Farrux opened it nine days ago for the pharmacy
  staff; the deadline was two days ago. Malika and Nigora sent their answers, Shahzoda has a
  draft, Dilshod (away at his brother's wedding) and Farrux himself haven't started: the round
  page shows them late, the reviewers' part begins by itself in two days.

People without pay in payroll (a module's own test builds no pay) get no raise: the review then
stays without one.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.core import demo_plan as plan
from apps.core.demo_time import moment
from apps.core.exceptions import DomainError
from apps.lifecycle import integrations, job_changes, notify, review_notify, reviews
from apps.lifecycle.models import JobChange, Review, ReviewGoal
from apps.members.models import Position

# Per person: the ratings they give themselves (5 rating questions), their two texts, then the
# reviewer's ratings, a short comment on some questions, the overall rating and the summary.
SELF = {
    "worker": (
        [4, 5, 4, 4, 3],
        "Ertalabki smenalarda kassa doim to‘g‘ri chiqdi, navbat bo‘lmadi.",
        "Muzlatgich jurnalini o‘z vaqtida to‘ldirishim kerak. Yangi preparatlar bo‘yicha qisqa "
        "o‘quv foydali bo‘lardi.",
    ),
    "madina": (
        [5, 5, 4, 5, 4],
        "Без ошибок в рецептурном отпуске, помогала новым сотрудникам с программой.",
        "Хочу пройти курс по фармаконадзору; нужен график, чтобы совмещать его с вечерними "
        "сменами.",
    ),
    "gulnora": (
        [4, 5, 5, 4, 4],
        "Yillik ta’tilgacha hamma smenalarni o‘zim yopdim, kassada farq bo‘lmadi.",
        "Provizorlik ishiga tayyorlanyapman: retseptlar jurnalini yuritishni o‘rganmoqchiman.",
    ),
    "sardor": (
        [5, 4, 5, 5, 4],
        "Kechki smenada xaridorlar ko‘p bo‘ldi, lekin shikoyat bo‘lmadi; muddati tugayotgan "
        "dorilarni o‘z vaqtida qaytardik.",
        "Omborchi bilan kirimni tezroq qabul qilish tartibini kelishib olishimiz kerak.",
    ),
    "manager": (
        [4, 4, 5, 4, 4],
        "Chilonzorda smenalar uzilishsiz yopildi, ikki yangi farmatsevt tez moslashdi.",
        "Tungi navbatchiliklarni oldindan rejalashtirishim kerak.",
    ),
    "jasur": (
        [4, 4, 4, 4, 3],
        "Buyurtmalarni manzilga yetkazishda xato bo‘lmadi.",
        "Ertalab kechikmaslik uchun yo‘lga ertaroq chiqaman.",
    ),
    "otabek": (
        [4, 4, 4, 4, 3],
        "Distribyutor kirimlarini qabul qilishda seriya va yaroqlilik muddatini tekshirib bordim.",
        "Kirimni o‘sha kuni kiritishga ulgurmayapman; ikkinchi skaner kerak.",
    ),
    "aziza": (
        [5, 4, 5, 5, 5],
        "Закрыла сверки с дистрибьюторами без расхождений, зарплата выплачена вовремя.",
        "Нужно автоматизировать выгрузку чеков из кассы.",
    ),
    "malika": (
        [5, 4, 5, 4, 5],
        "Retseptli dorilar jurnali to‘liq, tekshiruvda kamchilik topilmadi.",
        "Kunduzgi va tungi smenalar o‘rtasidagi topshirishni yozma qilsak yaxshi bo‘lardi.",
    ),
    "nigora": (
        [4, 5, 4, 5, 4],
        "Dilshodning ikki tungi smenasini oldim, muzlatgich harorati har soatda yozildi.",
        "Tungi smenada ikkinchi kassir bo‘lsa, navbat kamayardi.",
    ),
}
MANAGER = {
    "worker": (
        [3, 4, 4, 4, 3],
        {1: "Saqlash jurnalida bo‘shliqlar bor: har smenada yozilsin."},
        3,
        "Kassa intizomi yaxshi, xaridorlar mamnun. Saqlash jurnalini o‘z vaqtida to‘ldirishga "
        "e’tibor bering.",
    ),
    "madina": (
        [5, 5, 4, 5, 5],
        {4: "Yangi xodimlarga ustozlik qildi."},
        5,
        "Retsept bo‘yicha xatosiz ishladi, yangi xodimlarga ustozlik qildi. Oylik oshishiga loyiq.",
    ),
    "gulnora": (
        [4, 5, 5, 4, 4],
        {3: "Kassa har kuni farqsiz topshirildi."},
        4,
        "Ta’tildan oldin barcha smenalarni yopib, kassani xatosiz topshirdi. Mukofot beriladi.",
    ),
    "sardor": (
        [5, 5, 5, 5, 4],
        {1: "Muddati tugayotgan dorilar o‘z vaqtida qaytarildi."},
        5,
        "Kechki smenaning tayanchi: shikoyatsiz, muddati tugayotgan dorilar o‘z vaqtida "
        "qaytarildi.",
    ),
    "manager": (
        [4, 4, 5, 4, 4],
        {},
        4,
        "Chilonzor barqaror ishladi. Keyingi chorakda tungi navbatchilik rejasini oldindan tuzing.",
    ),
    "jasur": (
        [4, 4, 4, 3, 3],
        {4: "Ertalabki kechikishlar jamoaga og‘ir tushdi."},
        3,
        "Yetkazib berish sifatli, lekin ertalabki kechikishlar takrorlandi.",
    ),
    "otabek": (
        [3, 4, 3, 4, 3],
        {1: "Kirim kechikib kiritilmoqda.", 3: "Inventarizatsiyada farqlar chiqdi."},
        3,
        "Qabul qilish puxta, lekin kirim kechikib kiritilmoqda. Keyingi chorak uchun reja tuzdik.",
    ),
    "aziza": (
        [5, 4, 5, 5, 5],
        {},
        5,
        "Hisob-kitoblar o‘z vaqtida, dalolatnomalar tartibli.",
    ),
}
RAISES = {"sardor": Decimal("10"), "madina": Decimal("8")}
BONUS = ("gulnora", Decimal("500000"))
PLAN = "otabek"
GOALS = [
    ("Kirim (nakladnoy) o‘sha kuni tizimga kiritilsin", None, "", "done"),
    ("Inventarizatsiyadagi farq: ko‘pi bilan 0,5 %", Decimal("0.5"), "%", "open"),
    ("Ombor harorati va namligi har kuni jurnalga yozilsin", None, "", "open"),
]
# Who in Yunusobod has answered: sent, a draft (the first three ratings), or nothing yet.
YUNUSOBOD = {"malika": "sent", "nigora": "sent", "shahzoda": "draft"}
SHAHZODA_DRAFT = "Быстро освоила новую кассовую программу."


def seed(company, story, owner) -> None:
    """Both rounds (Demo Dorixona only)."""
    if story.small:
        return
    start, end = _last_quarter(story.today.replace(day=1) - timedelta(days=26))
    _chilonzor(company, story, owner, start, end)
    _yunusobod(company, story, owner, start, end)


def _last_quarter(day: date) -> tuple[date, date]:
    """The last full quarter before the one `day` is in."""
    first = date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)
    end = first - timedelta(days=1)
    start = date(end.year, 3 * ((end.month - 1) // 3) + 1, 1)
    return start, end


def _name(story, branch: str, end: date) -> str:
    quarter = (end.month - 1) // 3 + 1
    return f"{branch}: {quarter}-chorak, {end.year}"


def _answers(cycle, ratings: list[int], texts=(), comments=None) -> dict:
    comments = comments or {}
    found = {}
    ids = reviews.rating_ids(cycle)
    for number, (question_id, rating) in enumerate(zip(ids, ratings, strict=False), start=1):
        found[question_id] = {"rating": rating, "text": comments.get(number, "")}
    texts_ids = [q["id"] for q in cycle.questions if q["kind"] == reviews.TEXT]
    for question_id, text in zip(texts_ids, texts, strict=False):
        found[question_id] = {"rating": None, "text": text}
    return found


def _capped(story, at: datetime) -> datetime:
    """Never later than an hour ago (the 1st may be today)."""
    return min(at, timezone.localtime(story.now, story.zone) - timedelta(hours=1))


def _chilonzor(company, story, owner, start: date, end: date) -> None:
    bekzod = story.member("manager")
    if bekzod is None:
        return
    first = story.today.replace(day=1)
    with moment(story.at(first - timedelta(days=27), time(16, 0))):
        cycle = reviews.create_cycle(
            company,
            by=bekzod,
            name=_name(story, "Chilonzor", end),
            period_start=start,
            period_end=end,
            self_due_on=first - timedelta(days=19),
            manager_due_on=first - timedelta(days=9),
            questions=reviews.template(),
        )
    with moment(story.at(first - timedelta(days=26), time(10, 0))):
        cycle = reviews.open_cycle(cycle, by=bekzod)
        review_notify.round_opened(cycle.pk)
    rows = {review.membership_id: review for review in cycle.reviews.all()}
    keys = [key for key in SELF if (member := story.member(key)) and member.pk in rows]
    for index, key in enumerate(keys):
        ratings, best, better = SELF[key]
        # Jasur sends his a day late; the others across the week.
        day = (
            cycle.self_due_on + timedelta(days=1)
            if key == "jasur"
            else (first - timedelta(days=25 - index % 6))
        )
        with moment(story.at(day, time(21, 10 + index))):
            reviews.send_self(
                rows[story.member(key).pk],
                by=story.member(key),
                answers=_answers(cycle, ratings, (best, better)),
            )
    with moment(story.at(cycle.self_due_on + timedelta(days=1), time(9, 0))):
        cycle = reviews.advance(cycle, by=bekzod)
        review_notify.reviewers_part(cycle.pk)

    changes: list[JobChange] = []
    bonus_id = None
    for index, key in enumerate(keys):
        person = story.member(key)
        review = Review.objects.get(pk=rows[person.pk].pk)
        ratings, comments, overall, summary = MANAGER[key]
        reviewer = review.reviewer
        if reviewer is None:
            continue
        at = story.at(first - timedelta(days=16 - index % 6), time(15, 5 * index % 50))
        with moment(at):
            review = reviews.open_for_reviewer(review, by=reviewer)
            fields = {
                "answers": _answers(cycle, ratings, comments=comments),
                "rating": overall,
                "summary": summary,
            }
            fields |= _outcome(key, person, first)
            reviews.save_manager(review, by=reviewer, **fields)
            review = reviews.publish(Review.objects.get(pk=review.pk), by=reviewer)
            review_notify.published(review.pk)
        if review.job_change_id:
            changes.append(review.job_change)
        if review.bonus_id:
            bonus_id = review.bonus_id
        if key != "jasur":
            with moment(at + timedelta(days=1, hours=3)):
                reviews.acknowledge(review, by=person)

    with moment(story.at(first - timedelta(days=8), time(11, 0))):
        for change in changes:
            change = job_changes.approve(change, by=owner)
            notify.change_decided(change.pk)
        if bonus_id:
            from apps.payroll import services as payroll
            from apps.payroll.models import Adjustment

            payroll.approve(Adjustment.objects.get(pk=bonus_id), by=owner)
    with moment(story.at(first - timedelta(days=7), time(18, 0))):
        reviews.close_cycle(cycle, by=bekzod)
    with moment(_capped(story, story.at(first, time(0, 5)))):
        for change in changes:
            job_changes.apply(JobChange.objects.get(pk=change.pk))
    _goals(story, cycle)


def _outcome(key: str, person, first: date) -> dict:
    if key in RAISES and integrations.current_pay(person, on=first) is not None:
        return {"outcome": "raise", "raise_percent": RAISES[key], "effective_on": first}
    if key == BONUS[0] and integrations.payroll_on(person.company):
        return {"outcome": "bonus", "bonus_amount": BONUS[1], "effective_on": first}
    if key == PLAN:
        return {
            "outcome": "improvement_plan",
            "goals": [
                {
                    "title": title,
                    "target": target,
                    "unit": unit,
                    "due_on": first + timedelta(days=58),
                }
                for title, target, unit, _status in GOALS
            ],
        }
    return {"outcome": "none"}


def _goals(story, cycle) -> None:
    """Otabek's first goal is reached; the inventory one is under way."""
    otabek = story.member(PLAN)
    review = cycle.reviews.filter(membership=otabek).first() if otabek else None
    if review is None or review.reviewer is None:
        return
    goals = list(review.goals.order_by("order"))
    with moment(_capped(story, story.at(story.today - timedelta(days=3), time(17, 30)))):
        for goal, (_title, target, _unit, status) in zip(goals, GOALS, strict=False):
            if status == "done":
                reviews.update_goal(goal, by=review.reviewer, status=ReviewGoal.Status.DONE)
            elif target is not None:
                reviews.update_goal(goal, by=review.reviewer, progress=Decimal("0.8"))


def _yunusobod(company, story, owner, start: date, end: date) -> None:
    farrux = story.member("farrux")
    if farrux is None:
        return
    staff = [plan.HEAD, plan.SENIOR, plan.PHARMACIST]
    positions = list(Position.objects.filter(company=company, name__in=staff))
    with moment(story.at(story.day(-10), time(15, 0))):
        cycle = reviews.create_cycle(
            company,
            by=farrux,
            name=_name(story, "Yunusobod", end),
            period_start=start,
            period_end=end,
            self_due_on=story.day(-2),
            manager_due_on=story.day(5),
            questions=reviews.template(),
            positions=positions,
        )
    with moment(story.at(story.day(-9), time(10, 0))):
        try:
            cycle = reviews.open_cycle(cycle, by=farrux)
        except DomainError:
            return  # nobody to review (a module's own test)
        review_notify.round_opened(cycle.pk)
    rows = {review.membership_id: review for review in cycle.reviews.all()}
    for offset, (key, state) in zip((-8, -5, -3), YUNUSOBOD.items(), strict=True):
        person = story.member(key)
        if person is None or person.pk not in rows:
            continue
        with moment(story.at(story.day(offset), time(21, 40))):
            if state == "sent":
                ratings, best, better = SELF[key]
                reviews.send_self(
                    rows[person.pk], by=person, answers=_answers(cycle, ratings, (best, better))
                )
            else:
                reviews.save_self(
                    rows[person.pk],
                    by=person,
                    answers=_answers(cycle, [4, 5, 4], (SHAHZODA_DRAFT,)),
                )
    # The day before the deadline (10:00, the beat's hour): whoever hasn't answered hears again.
    eve = cycle.self_due_on - timedelta(days=1)
    with moment(story.at(eve, time(10, 5))):
        if reviews._mark(cycle, "self_reminded_on", eve):
            review_notify.deadline_reminders(cycle.pk)
