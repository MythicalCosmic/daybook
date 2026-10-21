"""Demo data of the inbox: a few messages from the product, so the dashboard's Inbox has
something to show, each in its reader's language (written here in Uzbek, Russian and English,
like the rest of the demo's content). After every other demo, `finish` settles the inbox: what
the others sent more than a day and a half ago has been read by now."""

from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from apps.inbox.models import Notification
from apps.inbox.services import NotificationAction, notify


def said(*, uz: str, ru: str, en: str):
    """A text in its reader's language: `notify` renders every reader's copy with this."""
    texts = {"uz": uz, "ru": ru}
    return lambda person: texts.get(person.user.language, en)


GOT_IT = NotificationAction("got_it", said(uz="Tushunarli", ru="Понятно", en="Got it"), "primary")


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    leaders = [people["owner"], people["manager"]]
    notify(
        leaders,
        "inbox.system",
        title=said(
            uz="Boshqaruv paneliga xush kelibsiz",
            ru="Добро пожаловать в панель управления",
            en="Welcome to your dashboard",
        ),
        body=said(
            uz="Jamoa Telegramda qilgan hamma ish shu yerda: vazifalar, xodimlar, tasdiqlar va "
            "hisobotlar.",
            ru="Всё, что команда делает в Telegram, видно здесь: задачи, люди, согласования "
            "и отчёты.",
            en="Everything your team does in Telegram shows up here: tasks, people, approvals "
            "and reports.",
        ),
        url=f"/c/{company.pk}/",
        actions=[GOT_IT],
        dedupe_key="demo:welcome",
    )
    # The attendance demo leaves next week's roster in draft.
    notify(
        leaders,
        "inbox.system",
        title=said(
            uz="Keyingi hafta jadvali hali e’lon qilinmagan",
            ru="График на следующую неделю ещё не опубликован",
            en="Next week's roster isn't published yet",
        ),
        body=said(
            uz="Qoralamalarni ko‘rib chiqing va e’lon qiling: xodimlar smenalarini Telegramda "
            "ko‘radi.",
            ru="Проверьте черновики и опубликуйте: сотрудники увидят смены в Telegram.",
            en="Check the drafts and publish them: staff see their shifts in Telegram.",
        ),
        url=f"/c/{company.pk}/attendance/roster",
        severity="warning",
        dedupe_key="demo:roster",
    )
    [tip] = notify(
        [people["owner"]],
        "inbox.system",
        title=said(
            uz="Istalgan narsani topish uchun Ctrl+K ni bosing",
            ru="Нажмите Ctrl+K, чтобы найти что угодно",
            en="Press Ctrl+K to find anything",
        ),
        body=said(
            uz="Xodimlar, vazifalar va yozuvlarni istalgan sahifadan qidiring.",
            ru="Ищите людей, задачи и записи с любой страницы.",
            en="Search people, tasks and records from any page.",
        ),
        dedupe_key="demo:search",
    ) or [None]
    if tip is not None:
        Notification.objects.filter(pk=tip.pk).update(read_at=now or timezone.now())


def finish(company, people, now) -> None:
    """Messages the other demos sent more than 36 hours ago were read two hours after they came
    (what waits for a decision keeps its buttons until someone acts)."""
    Notification.objects.filter(
        company=company, read_at__isnull=True, created_at__lt=now - timedelta(hours=36)
    ).update(read_at=F("created_at") + timedelta(hours=2))
