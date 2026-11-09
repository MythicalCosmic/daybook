"""Demo data of package Q1 (courses, lessons, videos, who watched what), called by `demo.py`.

Demo Dorixona (docs/PLAN-LEARNING.md §14), built through the services at the moments things
happened (`apps.core.demo_time.moment`), on top of the knowledge base demo's pages and topics:

- four video lessons: "Sovuq zanjir: muzlatgich va termometr", "Retseptli dorini berish tartibi",
  "Kassa: chek va qaytarish", "Muddat o‘tgan dorilar bilan ishlash". When ffmpeg is installed each
  gets a 20-second placeholder video made by the real upload and processing code; without it
  the lessons stay drafts without a video (and nobody can watch them);
- four courses: "Yangi xodim kursi" (mandatory for everyone, 14 days), "Sovuq zanjir"
  (mandatory for pharmacists, renews every 12 months), "Retsept bo‘yicha dori berish"
  (mandatory for pharmacists, 21 days) and "Kassa qoidalari" (optional);
- the story: Madina (senior pharmacist) finished every course with certificates; Alisher is
  late with "Sovuq zanjir", a third of its video watched; Nigora (night pharmacist) is half-way
  through "Retsept bo‘yicha dori berish"; Jasur (courier) finished the new-hire course;
  everyone else did what their courses ask on time;
- who read the handbook: page views of the people who confirmed its pages, and a few more.

The quizzes' demo (Q2) runs after this one and may add its quizzes as course steps.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path

from apps.core import demo_plan
from apps.core.demo_time import moment
from apps.knowledge import services as knowledge
from apps.knowledge import topics as topic_services
from apps.knowledge.models import Page, PageAck, PageView, Topic
from apps.learning import courses, lessons, media, progress
from apps.learning.models import Assignment, Lesson, Status, Video
from apps.members.models import Membership, Position

logger = logging.getLogger(__name__)

QUALIFIED = (demo_plan.HEAD, demo_plan.SENIOR, demo_plan.PHARMACIST)
VIDEO_SECONDS = 20

COLD_NOTES = (
    "<h2>Muzlatgichdagi harorat</h2>"
    "<p>Sovuq zanjirdagi dorilar (vaksinalar, insulin, ayrim ko‘z tomchilari) "
    "<strong>+2…+8 °C</strong> da saqlanadi.</p>"
    "<ul><li>Termometrni kuniga ikki marta, smena boshida va oxirida tekshiring.</li>"
    "<li>Ko‘rsatkichni jurnalga yozing: vaqt, harorat, imzo.</li>"
    "<li>Harorat chegaradan chiqsa, dorilarni boshqa muzlatgichga o‘tkazing va mudirga xabar "
    "bering.</li></ul>"
)
RX_NOTES = (
    "<h2>Retseptli dori berish</h2>"
    "<ol><li>Retseptning muddati va shifokor muhrini tekshiring.</li>"
    "<li>Dori nomi, shakli va dozasi retseptga mos kelishiga ishonch hosil qiling.</li>"
    "<li>Berilgan dorini retseptlar jurnaliga yozing.</li></ol>"
    "<p>Nazoratdagi moddalar alohida jurnalga yoziladi.</p>"
)
TILL_NOTES = (
    "<h2>Chek va qaytarish</h2>"
    "<ul><li>Har bir sotuvga chek beriladi, karta bilan ham.</li>"
    "<li>Sotilgan dorilar qaytarilmaydi: qonun shuni talab qiladi, xaridorga muloyim "
    "tushuntiring.</li>"
    "<li>Xato chek urilgan bo‘lsa, mudir bilan bekor qiling va sababini yozing.</li></ul>"
)
EXPIRED_NOTES = (
    "<h2>Muddati o‘tgan dorilar</h2>"
    "<p>Muddati tugagan dori sotilmaydi va javondan darhol olinadi.</p>"
    "<ul><li>Uni karantin javoniga qo‘ying va hisobdan chiqarish dalolatnomasini tuzing.</li>"
    "<li>Muddati 90 kundan kam qolgan dorilarni oldinroq soting (FEFO).</li></ul>"
)

LESSONS = (
    ("cold", "Sovuq zanjir: muzlatgich va termometr", "🧊", "0x1f6f8b", COLD_NOTES),
    ("rx", "Retseptli dorini berish tartibi", "📋", "0x5b4a9b", RX_NOTES),
    ("till", "Kassa: chek va qaytarish", "💳", "0xa8741a", TILL_NOTES),
    ("expired", "Muddat o‘tgan dorilar bilan ishlash", "⏳", "0x2b7a6f", EXPIRED_NOTES),
)


def _placeholder(color: str, folder: Path) -> bytes | None:
    """A 20-second video: a plain colour and a soft tone (ffmpeg's lavfi sources)."""
    if not shutil.which("ffmpeg"):
        return None
    target = folder / f"{color}.mp4"
    args = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=640x360:d={VIDEO_SECONDS}:r=25",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=330:duration={VIDEO_SECONDS}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(target),
    ]
    try:
        subprocess.run(args, check=True, capture_output=True, timeout=120)
    except OSError, subprocess.SubprocessError:
        logger.warning("The demo couldn't make a placeholder video", exc_info=True)
        return None
    return target.read_bytes()


def _video(company, owner, data: bytes, name: str) -> Video | None:
    """The placeholder through the real upload and processing (synchronously, here)."""
    video = media.start_upload(company, by=owner, name=name, size=len(data))
    for offset in range(0, len(data), media.CHUNK_BYTES):
        media.receive_chunk(
            video, by=owner, offset=offset, data=data[offset : offset + media.CHUNK_BYTES]
        )
    Video.objects.filter(pk=video.pk).update(state=Video.State.PROCESSING, upload_expires_at=None)
    if media.process_video(video.pk) != "ready":
        return None
    return Video.objects.get(pk=video.pk)


def _topics(company, owner) -> dict[str, Topic]:
    """The pharmacy topics by their colour (names depend on the company's language)."""
    topic_services.add_pharmacy_topics(company, by=owner)
    by_color = {}
    for topic in Topic.objects.filter(company=company, archived_at__isnull=True):
        by_color.setdefault(topic.color, topic)
    return by_color


def _pages(company) -> dict[str, Page]:
    wanted = {
        "welcome": "Xush kelibsiz!",
        "schedule": "Ish tartibi va smenalar",
        "customers": "Xaridor bilan muloqot",
        "cold": "Sovuq zanjir: +2…+8 °C",
        "rx": "Retsept bo‘yicha dorilar",
        "controlled": "Nazoratdagi moddalar jurnali",
        "close_till": "Kassani yopish va Z-hisobot",
        "terminal": "Terminal ishlamasa nima qilish kerak",
    }
    found = {}
    for key, title in wanted.items():
        page = Page.objects.filter(
            company=company, title=title, published=True, archived_at__isnull=True
        ).first()
        if page is not None:
            found[key] = page
    return found


def _read(page: Page, member: Membership, at, *, seconds: int = 140, scrolled: int = 100):
    """`member` read `page` at `at`: a view, and the confirmation when it asks for one."""
    PageView.objects.update_or_create(
        page=page,
        membership=member,
        defaults={
            "company_id": page.company_id,
            "first_at": at - timedelta(minutes=3),
            "last_at": at,
            "visits": 1 + (member.pk + page.pk) % 3,
            "seconds": seconds,
            "version": page.version,
            "scrolled": scrolled,
        },
    )
    confirmed = PageAck.objects.filter(
        page=page, membership=member, version__gte=page.ack_version
    ).exists()
    if scrolled >= 90 and not confirmed:
        with moment(at):
            knowledge.acknowledge(page, by=member)


def _watch(lesson: Lesson, member: Membership, at, *, until: int | None = None) -> None:
    """`member` plays `lesson` from the start, reporting every 10 s like the mini app's player."""
    if not lessons.ready_for_watching(lesson):
        return
    end = until if until is not None else lesson.duration_seconds
    session = f"demo-{member.pk}-{lesson.pk}-{int(at.timestamp())}"
    position, clock = 0, at
    while position < end:
        step = min(10, end - position)
        clock += timedelta(seconds=step)
        with moment(clock):
            progress.report(
                lesson,
                member,
                session=session,
                position=position + step,
                duration=lesson.duration_seconds,
                ranges=[[position, position + step]],
                playing=True,
                now=clock,
            )
        position += step


def _assignment(course, member) -> Assignment | None:
    return courses.latest(course, member)


def _finish(course, member, steps, at) -> None:
    """Every step of `course` done by `member`, a few hours apart, ending at `at`."""
    when = at - timedelta(hours=len(steps))
    for kind, target in steps:
        when += timedelta(hours=1)
        if kind == "lesson":
            _watch(target, member, when)
        else:
            _read(target, member, when)
    row = _assignment(course, member)
    if row is not None:
        with moment(at):
            courses.refresh(row, now=at)


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    owner = people["owner"]
    madina, alisher, nigora, jasur = (
        people["madina"],
        people["worker"],
        people["nigora"],
        people["jasur"],
    )
    manager = people["manager"]
    positions = {row.name: row for row in Position.objects.filter(company=company)}
    qualified = [positions[name].pk for name in QUALIFIED if name in positions]
    readers = qualified + ([positions[demo_plan.STOCK].pk] if demo_plan.STOCK in positions else [])
    topics = _topics(company, owner)
    pages = _pages(company)

    # Lessons ------------------------------------------------------------------------------
    made: dict[str, Lesson] = {}
    topic_of = {
        "cold": ("sky", "teal"),
        "rx": ("violet",),
        "till": ("amber",),
        "expired": ("teal",),
    }
    with tempfile.TemporaryDirectory(prefix="learning-demo-") as folder:
        for key, title, emoji, color, notes in LESSONS:
            with moment(now - timedelta(days=65)):
                data = _placeholder(color, Path(folder))
                video = _video(company, owner, data, f"{key}.mp4") if data else None
                lesson = lessons.create_lesson(
                    company,
                    by=owner,
                    title=title,
                    emoji=emoji,
                    summary="",
                    notes=notes,
                    source=Lesson.Source.UPLOAD,
                    video_id=video.pk if video else None,
                    topic_ids=[topics[c].pk for c in topic_of[key] if c in topics],
                    audience_all=False,
                    position_ids=readers if key in ("cold", "expired") else qualified,
                )
                if video is not None:
                    lesson = lessons.publish_lesson(lesson, by=owner)
            made[key] = Lesson.objects.select_related("video").get(pk=lesson.pk)

    def steps(*names):
        found = []
        for name in names:
            if name.startswith("lesson:"):
                found.append(("lesson", made[name.split(":", 1)[1]]))
            elif name in pages:
                found.append(("page", pages[name]))
        return found

    def build(at, *, title, emoji, color, description, chosen, **fields):
        with moment(at):
            course = courses.create_course(
                company,
                by=owner,
                title=title,
                emoji=emoji,
                color=color,
                description=description,
                **fields,
            )
            for kind, target in chosen:
                courses.add_step(course, by=owner, kind=kind, target_id=target.pk)
            if chosen:
                course = courses.publish_course(course, by=owner)
        return course

    everyone = [row for row in Membership.objects.filter(company=company, status="approved")]
    story = {owner.pk, manager.pk, madina.pk, alisher.pk, nigora.pk, jasur.pk}
    others = [row for row in everyone if row.pk not in story]

    # 60 days ago: the new-hire course, for everyone; everyone has done it (the owner wrote and
    # so confirmed its pages).
    new_hire_steps = steps("welcome", "schedule", "customers")
    new_hire = build(
        now - timedelta(days=60),
        title="Yangi xodim kursi",
        emoji="🎓",
        color="green",
        description="Dorixonaga xush kelibsiz: ish tartibi, kiyinish va xaridor bilan muloqot.",
        chosen=new_hire_steps,
        mandatory=True,
        due_days=14,
        sequential=True,
        certificate=True,
    )
    for offset, member in enumerate([manager, madina, alisher, nigora, jasur, *others]):
        _finish(new_hire, member, new_hire_steps, now - timedelta(days=57 - offset % 6))

    # 20 days ago: the cold chain, for pharmacists, renewing every year. Alisher watched a
    # third of the video and is late; the others are done.
    cold_steps = steps("lesson:cold", "cold")
    cold = build(
        now - timedelta(days=20),
        title="Sovuq zanjir",
        emoji="🧊",
        color="sky",
        description="Muzlatgich, termometr va harorat jurnali: +2…+8 °C bo‘lishi shart.",
        chosen=cold_steps,
        mandatory=True,
        due_days=14,
        renew_months=12,
        audience_all=False,
        position_ids=qualified,
        certificate=True,
    )
    _finish(cold, madina, cold_steps, now - timedelta(days=15))
    _finish(cold, manager, cold_steps, now - timedelta(days=12))
    _finish(cold, nigora, cold_steps, now - timedelta(days=10))
    for offset, member in enumerate(others):
        if member.position_id in qualified:
            _finish(cold, member, cold_steps, now - timedelta(days=14 - offset % 5))
    _watch(made["cold"], alisher, now - timedelta(days=18), until=VIDEO_SECONDS // 3)
    if "cold" in pages:
        _read(pages["cold"], alisher, now - timedelta(days=18), seconds=40, scrolled=35)

    # 10 days ago: prescriptions, for pharmacists. Madina is done; Nigora is half-way.
    rx_steps = steps("lesson:rx", "rx", "controlled")
    rx = build(
        now - timedelta(days=10),
        title="Retsept bo‘yicha dori berish",
        emoji="📋",
        color="violet",
        description="Retseptni tekshirish, dori berish va jurnalga yozish tartibi.",
        chosen=rx_steps,
        mandatory=True,
        due_days=21,
        audience_all=False,
        position_ids=qualified,
        certificate=True,
    )
    controlled = rx.steps.filter(page__title="Nazoratdagi moddalar jurnali").first()
    if controlled is not None:
        with moment(now - timedelta(days=10)):
            courses.update_step(controlled, by=owner, required=False)
    _finish(rx, madina, rx_steps, now - timedelta(days=6))
    _watch(made["rx"], nigora, now - timedelta(days=4))
    if "rx" in pages:
        _read(pages["rx"], nigora, now - timedelta(days=3), seconds=95, scrolled=60)

    # 5 days ago: the till, optional; Madina took it on her own and finished it.
    # (Not the opening page: the knowledge base's story has Madina still to re-read it.)
    till_steps = steps("lesson:till", "close_till", "terminal")
    till = build(
        now - timedelta(days=5),
        title="Kassa qoidalari",
        emoji="💳",
        color="amber",
        description="Kassani ochish va yopish, chek va qaytarish qoidalari.",
        chosen=till_steps,
        mandatory=False,
        due_days=None,
        audience_all=False,
        position_ids=qualified,
        sequential=False,
        certificate=True,
    )
    if courses.can_start(till, madina, now=now - timedelta(days=4)):
        with moment(now - timedelta(days=4)):
            courses.start(till, madina)
        _finish(till, madina, till_steps, now - timedelta(days=3))

    # The expired-medicines lesson stands on its own: Madina watched it, Alisher is on it.
    _watch(made["expired"], madina, now - timedelta(days=8))
    _watch(made["expired"], alisher, now - timedelta(days=2), until=8)

    # More of the handbook read: the welcome page by people who opened it twice.
    for member in (jasur, nigora):
        if "welcome" in pages:
            _read(pages["welcome"], member, now - timedelta(days=1), seconds=60, scrolled=100)
    logger.info(
        "Learning demo: %s published lessons, 4 courses",
        Lesson.objects.filter(company=company, status=Status.PUBLISHED).count(),
    )
