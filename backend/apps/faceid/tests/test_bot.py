"""The company's own Face ID bot (`apps.faceid.bot`): the token (encrypted, never returned,
checked with getMe), who may set it, the delivery switch for every kind of Face ID message,
Telegram's 403 (recorded, not retried), /start and the poller picking up a new token."""

from itertools import count

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import SendMessage
from django.db import connection

from apps.attendance import notify as attendance_notify
from apps.attendance.models import AttendanceRecord
from apps.audit.models import AuditLog
from apps.davomat.telegram import BotInfo, TelegramUnreachable, TokenRefused
from apps.faceid import bot, conf
from apps.faceid.models import FaceBotChat, FaceIdSettings
from apps.faceid.tests.conftest import DAY, local
from apps.groups.models import GroupEvent, TelegramGroup
from apps.groups.services import broadcast
from apps.inbox import services as inbox

pytestmark = pytest.mark.django_db

TOKEN = "123456:AAFakeFaceIdBotTokenForTestsOnly000000"
OTHER_TOKEN = "654321:AAAnotherFakeFaceIdBotTokenForTests00"


def url(company, path="bot/"):
    return f"/api/v1/owner/companies/{company.pk}/faceid/{path}"


def forbidden(chat_id=1):
    return TelegramForbiddenError(SendMessage(chat_id=chat_id, text="x"), "bot can't initiate")


class FakeTelegram:
    """Both the shared bots (`send_message`) and company bots (`send_with_token`)."""

    def __init__(self):
        self.shared, self.own = [], []
        self.ids = count(500)
        self.refuse_own: set[int] = set()
        self.not_in_group = False

    def send_message(self, bot_name, chat_id, text, reply_markup=None, photo=None, *a, **kw):
        self.shared.append({"bot": bot_name, "chat_id": chat_id, "text": text, "photo": photo})
        return next(self.ids)

    def send_with_token(
        self, token, chat_id, text, reply_markup=None, photo=None, storage="default"
    ):
        if chat_id in self.refuse_own:
            raise forbidden(chat_id)
        if chat_id < 0 and self.not_in_group:
            raise TelegramBadRequest(SendMessage(chat_id=chat_id, text=text), "chat not found")
        self.own.append({"token": token, "chat_id": chat_id, "text": text, "photo": photo})
        return next(self.ids)


@pytest.fixture
def tg(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr("apps.notifications.telegram.send_message", fake.send_message)
    monkeypatch.setattr("apps.notifications.telegram.send_with_token", fake.send_with_token)
    return fake


@pytest.fixture
def getme(monkeypatch):
    bots = {TOKEN: BotInfo(id=111, username="pharm_faceid_bot", name="Pharm Face ID")}
    bots[OTHER_TOKEN] = BotInfo(id=222, username="other_faceid_bot", name="Other")

    def check(token):
        if token not in bots:
            raise TokenRefused("no")
        return bots[token]

    monkeypatch.setattr("apps.davomat.telegram.check_token", check)
    return bots


@pytest.fixture
def connected(staff, getme, tg, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        bot.connect(staff.manager.company, by=staff.manager, token=TOKEN)
    return conf_row(staff.manager.company)


def conf_row(company):
    return conf.get_settings(company)


def stranger_notice(person, captured):
    with captured(execute=True):
        inbox.notify([person], "faceid.stranger", title="Unknown face at Kirish, 09:58")


# The token -------------------------------------------------------------------------------------


def test_the_token_is_checked_kept_encrypted_and_never_returned(staff, owner_api, getme, tg):
    company = staff.manager.company
    client = owner_api(staff.manager)
    assert client.get(url(company)).json()["configured"] is False

    response = client.put(url(company), {"token": f"  {TOKEN} "}, format="json")
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["configured"] is True and data["status"] == "ok"
    assert data["bot_username"] == "pharm_faceid_bot"
    assert data["start_url"] == "https://t.me/pharm_faceid_bot?start=faceid"
    assert TOKEN not in response.content.decode()
    assert TOKEN not in client.get(url(company)).content.decode()
    assert TOKEN not in client.get(url(company, "settings/")).content.decode()

    row = conf_row(company)
    assert row.bot_token == TOKEN
    with connection.cursor() as cursor:
        cursor.execute("SELECT bot_token FROM faceid_faceidsettings WHERE id = %s", [row.pk])
        stored = cursor.fetchone()[0]
    assert stored and TOKEN not in stored

    log = AuditLog.objects.get(action="faceid.bot_connected")
    assert TOKEN not in str(log.details) and log.details["bot"] == "@pharm_faceid_bot"


def test_a_token_telegram_refuses_or_cant_check(staff, owner_api, getme, tg, monkeypatch):
    company = staff.manager.company
    client = owner_api(staff.manager)
    response = client.put(url(company), {"token": "123:nope"}, format="json")
    assert response.status_code == 400 and "token" in response.json()

    def down(token):
        raise TelegramUnreachable("timeout")

    monkeypatch.setattr("apps.davomat.telegram.check_token", down)
    assert client.put(url(company), {"token": TOKEN}, format="json").status_code == 400
    assert conf_row(company).bot_token == ""


def test_one_bot_serves_one_company(staff, getme, tg, other_company, member):
    bot.connect(staff.manager.company, by=staff.manager, token=TOKEN)
    with pytest.raises(bot.TokenError):
        bot.connect(other_company, by=None, token=TOKEN)


def test_remove(staff, owner_api, connected, tg):
    company = staff.manager.company
    FaceBotChat.objects.create(company=company, telegram_id=5)
    assert owner_api(staff.manager).delete(url(company)).status_code == 204
    row = conf_row(company)
    assert (row.bot_token, row.bot_username, row.bot_status) == ("", "", "not_set")
    assert not FaceBotChat.objects.filter(company=company).exists()
    assert AuditLog.objects.filter(action="faceid.bot_removed").exists()


def test_who_may_set_it(staff, owner_api, getme, tg, other_company):
    company = staff.manager.company
    accountant = owner_api(staff.accountant)  # attendance.view only
    assert accountant.get(url(company)).status_code == 403
    assert accountant.put(url(company), {"token": TOKEN}, format="json").status_code == 403
    assert owner_api(staff.manager).get(url(other_company)).status_code == 404
    company.features = ["attendance"]
    company.save()
    assert owner_api(staff.manager).get(url(company)).status_code == 404


def test_send_a_test(staff, owner_api, connected, tg):
    company = staff.manager.company
    client = owner_api(staff.manager)
    response = client.post(url(company, "bot/test/"))
    assert response.status_code == 200 and response.json() == {"sent": True}
    assert tg.own[-1]["chat_id"] == staff.manager.user.telegram_id
    assert tg.own[-1]["token"] == TOKEN

    tg.refuse_own.add(staff.lead.user.telegram_id)
    response = owner_api(staff.lead).post(url(company, "bot/test/"))
    assert response.status_code == 400 and "Start" in response.json()["detail"]


# Delivery --------------------------------------------------------------------------------------


def test_without_a_bot_nothing_changes(staff, tg, django_capture_on_commit_callbacks):
    stranger_notice(staff.manager, django_capture_on_commit_callbacks)
    assert [sent["bot"] for sent in tg.shared] == ["employee"] and tg.own == []


def test_with_a_bot_face_id_notices_go_through_it(
    staff, connected, tg, django_capture_on_commit_callbacks
):
    stranger_notice(staff.manager, django_capture_on_commit_callbacks)
    assert tg.shared == []
    assert tg.own[0]["token"] == TOKEN
    assert tg.own[0]["chat_id"] == staff.manager.user.telegram_id
    # Other modules' notices keep the shared bots.
    with django_capture_on_commit_callbacks(execute=True):
        inbox.notify([staff.manager], "attendance.overtime", title="Late")
    assert len(tg.own) == 1


def test_a_revoked_token_falls_back_to_the_shared_bot(
    staff, connected, tg, django_capture_on_commit_callbacks
):
    FaceIdSettings.objects.filter(pk=connected.pk).update(bot_status="invalid")
    stranger_notice(staff.manager, django_capture_on_commit_callbacks)
    assert tg.own == [] and len(tg.shared) == 1


def test_403_is_recorded_once_and_not_retried_until_start(
    staff, connected, tg, django_capture_on_commit_callbacks
):
    company = staff.manager.company
    chat_id = staff.manager.user.telegram_id
    tg.refuse_own.add(chat_id)
    stranger_notice(staff.manager, django_capture_on_commit_callbacks)
    chat = FaceBotChat.objects.get(company=company, telegram_id=chat_id)
    assert chat.refused and tg.shared == []  # no fallback to the shared bot

    tg.refuse_own.clear()
    with django_capture_on_commit_callbacks(execute=True):
        inbox.notify([staff.manager], "faceid.stranger", title="Again")
    assert tg.own == []  # skipped: they haven't pressed Start

    pending = bot.recipients(company)
    assert any(p.member == staff.manager and p.state == "refused" for p in pending)

    row = conf_row(company)
    update = bot.Update(1, chat_id, "private", chat_id, "ru", "/start faceid")
    assert bot.handle(row, update)
    assert not FaceBotChat.objects.get(pk=chat.pk).refused
    with django_capture_on_commit_callbacks(execute=True):
        inbox.notify([staff.manager], "faceid.stranger", title="Third")
    assert tg.own[-1]["text"].count("Third") == 1


def test_the_persons_own_check_in_message(staff, connected, tg, chilonzor, freeze):
    freeze(local(DAY, 9, 0))
    record = AttendanceRecord.objects.create(
        company=staff.ali.company,
        membership=staff.ali,
        branch=chilonzor,
        check_in_at=local(DAY, 9, 0),
        date=DAY,
    )
    assert attendance_notify.scan_message(record.pk, checked_in=True)
    assert tg.own and tg.own[0]["chat_id"] == staff.ali.user.telegram_id and tg.shared == []


def test_group_posts_through_the_bot_when_it_is_in_the_group(
    staff, connected, tg, django_capture_on_commit_callbacks
):
    company = staff.manager.company
    TelegramGroup.objects.create(
        company=company, chat_id=-100500, title="Staff", events=[GroupEvent.ATTENDANCE]
    )
    with django_capture_on_commit_callbacks(execute=True):
        broadcast(company.pk, GroupEvent.ATTENDANCE, "Ali came", channel="faceid")
    assert tg.own[-1]["chat_id"] == -100500 and tg.shared == []

    tg.not_in_group = True
    with django_capture_on_commit_callbacks(execute=True):
        broadcast(company.pk, GroupEvent.ATTENDANCE, "Vali came", channel="faceid")
    assert tg.shared[-1]["chat_id"] == -100500  # not in the group: the employee bot posts


# /start and the poller -------------------------------------------------------------------------


def test_the_poller_answers_start_and_picks_up_a_new_token(
    staff, connected, tg, getme, other_company, monkeypatch, django_capture_on_commit_callbacks
):
    asked: list[tuple[str, int]] = []
    waiting = {
        TOKEN: [bot.Update(10, 77, "private", 77, "uz", "/start faceid")],
        OTHER_TOKEN: [bot.Update(40, 88, "private", 88, "en", "/start")],
    }

    def get_updates(token, offset):
        asked.append((token, offset))
        return [update for update in waiting.get(token, []) if update.update_id >= offset]

    monkeypatch.setattr(bot, "get_updates", get_updates)
    assert bot.poll_once() == 1
    assert FaceBotChat.objects.get(company=staff.manager.company, telegram_id=77).started_at
    assert tg.own[-1]["chat_id"] == 77 and "Face ID" in tg.own[-1]["text"]
    assert conf_row(staff.manager.company).bot_offset == 11

    other_company.features = ["attendance", "face_id"]
    other_company.save()
    with django_capture_on_commit_callbacks(execute=True):
        bot.connect(other_company, by=None, token=OTHER_TOKEN)
    assert bot.poll_once() == 1  # the new bot, without a restart; the first has nothing new
    assert (TOKEN, 11) in asked and (OTHER_TOKEN, 0) in asked
    assert FaceBotChat.objects.filter(company=other_company, telegram_id=88).exists()


def test_who_still_has_to_press_start(staff, owner_api, connected, tg):
    company = staff.manager.company
    FaceBotChat.objects.create(
        company=company, telegram_id=staff.manager.user.telegram_id, started_at=connected.created_at
    )
    data = owner_api(staff.manager).get(url(company)).json()
    names = {person["name"] for person in data["pending"]}
    assert staff.manager.full_name not in names
    assert staff.accountant.full_name in names and data["started"] == 1
    assert all(person["state"] == "waiting" for person in data["pending"])


def test_a_group_or_other_text_isnt_a_start(staff, connected):
    row = conf_row(staff.manager.company)
    assert not bot.handle(row, bot.Update(1, -5, "group", 9, "", "/start"))
    assert not bot.handle(row, bot.Update(2, 9, "private", 9, "", "hello"))
