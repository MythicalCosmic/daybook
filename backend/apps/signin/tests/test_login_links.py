"""Desktop sign-in end to end: QR / deep link, number matching, one POST claim (§7.1)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.members.models import Membership
from apps.signin import bot_flow, housekeeping, links
from apps.signin.callbacks import NOT_ME, LoginTap, SessionsAction
from apps.signin.models import DeviceSession, LoginLink
from apps.signin.services import REFRESH_COOKIE
from apps.signin.tests.conftest import LINKS
from apps.signin.tokens import OwnerAccessToken

pytestmark = pytest.mark.django_db


def prompt_numbers(markup) -> list[str]:
    numbers, _not_me = markup.inline_keyboard
    return [button.text for button in numbers]


def tap_right(user, browser) -> tuple[str, bool]:
    _text, markup = bot_flow.start(user, browser.code)
    picks = {
        LoginTap.unpack(button.callback_data).pick: LoginTap.unpack(button.callback_data)
        for button in markup.inline_keyboard[0]
    }
    tap = picks[browser.link["match_code"]]
    return bot_flow.tap(user, tap.link, tap.pick)


def test_a_new_link_has_a_deep_link_a_match_number_and_a_secret(browser):
    link = browser.start()

    assert link["deep_link"].startswith("https://t.me/daybook_test_bot?start=login_")
    # "login_" + 43 characters fits Telegram's 64-character start parameter.
    assert len(f"login_{browser.code}") <= 64 and len(browser.code) == 43
    assert link["match_code"].isdigit() and 10 <= int(link["match_code"]) <= 99
    assert len(link["poll_token"]) == 43
    row = LoginLink.objects.get(pk=link["id"])
    # Only hashes are stored.
    assert browser.code not in (row.code_hash, row.poll_hash)
    assert row.code_hash == links.sha256(browser.code)
    assert row.poll_hash == links.sha256(link["poll_token"])
    assert row.status == LoginLink.Status.PENDING
    assert row.bot == LoginLink.Bot.EMPLOYEE  # no owner bot token here
    assert abs(row.expires_at - row.created_at - links.LINK_LIFETIME) < timedelta(seconds=1)


def test_the_owner_bot_is_used_once_it_has_a_token(browser, bots):
    bots.OWNER_BOT_TOKEN = "43:OWNER"

    link = browser.start()

    assert link["deep_link"].startswith("https://t.me/owner_test_bot?start=login_")
    assert LoginLink.objects.get(pk=link["id"]).bot == LoginLink.Bot.OWNER


def test_without_a_bot_username_sign_in_is_unavailable(client, settings):
    settings.EMPLOYEE_BOT_USERNAME = ""
    settings.OWNER_BOT_TOKEN = ""

    response = client.post(
        LINKS, HTTP_X_REQUESTED_WITH="dashboard", HTTP_ORIGIN="http://testserver"
    )

    assert response.status_code == 503
    assert response.json()["code"] == "signin_unavailable"


def test_creating_a_link_needs_the_dashboard_header_and_origin(client, bots):
    assert client.post(LINKS).status_code == 403
    assert (
        client.post(
            LINKS, HTTP_X_REQUESTED_WITH="dashboard", HTTP_ORIGIN="https://evil.example"
        ).status_code
        == 403
    )


def test_right_number_then_one_claim_end_to_end(
    browser, owner, sent_messages, django_capture_on_commit_callbacks
):
    browser.start()
    assert browser.poll().json() == {"status": "pending"}

    text, markup = bot_flow.start(owner.user, browser.code)
    assert "Sign in to the dashboard?" in text
    assert "Chrome" not in text or "·" in text
    numbers = prompt_numbers(markup)
    assert browser.link["match_code"] in numbers and len(set(numbers)) == 3

    outcome, signed_in = tap_right(owner.user, browser)
    assert signed_in and "Confirmed" in outcome

    # The poll shows the approval but never a token.
    polled = browser.poll()
    assert polled.json() == {"status": "approved"}
    assert "access" not in polled.json() and REFRESH_COOKIE not in polled.cookies

    with django_capture_on_commit_callbacks(execute=True):
        claimed = browser.claim()
    assert claimed.status_code == 200
    access = OwnerAccessToken(claimed.json()["access"])
    session = DeviceSession.objects.get(user=owner.user)
    assert access["sid"] == session.pk
    cookie = claimed.cookies[REFRESH_COOKIE]
    assert cookie["httponly"] and cookie["samesite"] == "Strict"
    assert cookie["path"] == "/api/v1/owner/auth/"
    link = LoginLink.objects.get(pk=browser.link["id"])
    assert link.status == LoginLink.Status.CONSUMED and link.user == owner.user

    # "Signed in on … Not you? [Log out everywhere]" through the bot that confirmed it.
    [notice] = sent_messages
    assert notice["bot"] == "employee" and notice["chat_id"] == owner.user.telegram_id
    assert "Signed in to the dashboard" in notice["text"]
    [[button]] = notice["reply_markup"]["inline_keyboard"]
    assert SessionsAction.unpack(button["callback_data"]).session == session.pk

    # Only once.
    again = browser.claim()
    assert again.status_code == 409 and again.json()["code"] == "used"
    assert browser.poll().json() == {"status": "consumed"}


def test_log_out_everywhere_from_the_bot_ends_every_session(browser, owner, client):
    browser.start()
    tap_right(owner.user, browser)
    assert browser.claim().status_code == 200

    text = bot_flow.log_out_everywhere(owner.user)

    assert "signed out on every device" in text
    assert not DeviceSession.objects.filter(user=owner.user, revoked_at__isnull=True).exists()
    refreshed = client.post(
        "/api/v1/owner/auth/refresh/",
        HTTP_X_REQUESTED_WITH="dashboard",
        HTTP_ORIGIN="http://testserver",
    )
    assert refreshed.status_code == 401


def test_a_wrong_number_cancels_the_link(browser, owner):
    browser.start()
    _text, markup = bot_flow.start(owner.user, browser.code)
    wrong = next(
        LoginTap.unpack(button.callback_data)
        for button in markup.inline_keyboard[0]
        if button.text != browser.link["match_code"]
    )

    outcome, signed_in = bot_flow.tap(owner.user, wrong.link, wrong.pick)

    assert not signed_in and "cancelled" in outcome
    assert browser.poll().json() == {"status": "denied"}
    assert browser.claim().json()["code"] == "denied"
    # Tapping the right number afterwards changes nothing: the link is spent.
    assert links.decide(wrong.link, owner.user, browser.link["match_code"]) == "used"
    # And opening it again tells the person why.
    assert "cancelled" in bot_flow.start(owner.user, browser.code)[0]


def test_it_wasnt_me_denies(browser, owner):
    browser.start()
    _text, markup = bot_flow.start(owner.user, browser.code)
    not_me = LoginTap.unpack(markup.inline_keyboard[1][0].callback_data)
    assert not_me.pick == NOT_ME

    outcome, signed_in = bot_flow.tap(owner.user, not_me.link, not_me.pick)

    assert not signed_in and "Nobody was signed in" in outcome
    assert browser.poll().json() == {"status": "denied"}
    assert DeviceSession.objects.count() == 0


def age(link_id, **fields) -> None:
    """Move a link's moments into the past (instead of moving the clock forward)."""
    LoginLink.objects.filter(pk=link_id).update(**fields)


def test_an_expired_link_is_refused_everywhere(browser, owner):
    browser.start()
    link_id = browser.link["id"]
    age(link_id, expires_at=timezone.now() - timedelta(seconds=1))

    assert browser.poll().json() == {"status": "expired"}
    assert "expired" in bot_flow.start(owner.user, browser.code)[0]
    assert links.decide(link_id, owner.user, browser.link["match_code"]) == "expired"
    assert browser.claim().json()["code"] == "expired"
    assert LoginLink.objects.get(pk=link_id).status == LoginLink.Status.EXPIRED


def test_an_approval_nobody_claims_runs_out(browser, owner):
    browser.start()
    tap_right(owner.user, browser)
    age(browser.link["id"], decided_at=timezone.now() - links.CLAIM_WINDOW - timedelta(seconds=1))

    assert browser.poll().json() == {"status": "expired"}
    response = browser.claim()
    assert response.status_code == 409 and response.json()["code"] == "expired"


def test_a_wrong_poll_token_learns_nothing(browser, owner):
    browser.start()
    tap_right(owner.user, browser)

    assert browser.poll(token="guess").status_code == 404
    assert browser.poll(token="").status_code == 404
    assert browser.claim(token="guess").status_code == 404
    assert client_poll_unknown(browser).status_code == 404
    # The right browser still gets in.
    assert browser.claim().status_code == 200


def client_poll_unknown(browser):
    return browser.client.get(
        f"{LINKS}00000000-0000-0000-0000-000000000000/", HTTP_X_LOGIN_POLL="x"
    )


def test_claiming_needs_the_dashboard_header_and_origin(browser, owner):
    browser.start()
    tap_right(owner.user, browser)

    assert browser.claim(HTTP_X_REQUESTED_WITH="").status_code == 403
    assert browser.claim(HTTP_ORIGIN="https://evil.example").status_code == 403
    assert browser.claim().status_code == 200


def test_claiming_a_pending_link_is_refused(browser):
    browser.start()

    response = browser.claim()

    assert response.status_code == 409 and response.json()["code"] == "pending"


def test_people_without_dashboard_access_are_refused(browser, company, member):
    worker = member(company, "Employee", user__telegram_id=7700002)
    browser.start()

    assert "don't have access" in bot_flow.start(worker.user, browser.code)[0]
    assert links.decide(browser.link["id"], worker.user, browser.link["match_code"]) == "no_access"
    assert browser.poll().json() == {"status": "denied"}


def test_a_platform_admin_without_a_membership_is_refused(browser, settings):
    admin = UserFactory(telegram_id=6589960007, is_superuser=True)
    settings.PLATFORM_ADMIN_TG_IDS = [6589960007]
    browser.start()

    assert "don't have access" in bot_flow.start(admin, browser.code)[0]


def test_access_lost_between_approval_and_claim_is_refused(browser, owner):
    browser.start()
    tap_right(owner.user, browser)
    Membership.objects.filter(pk=owner.pk).update(status=Membership.Status.BLOCKED)

    response = browser.claim()

    assert response.status_code == 403 and response.json()["code"] == "no_access"
    assert DeviceSession.objects.count() == 0


def test_unknown_and_malformed_codes(browser, owner):
    assert "isn't valid" in bot_flow.start(owner.user, "nope")[0]
    assert links.decide("not-a-uuid", owner.user, "47") == "unknown"
    assert links.decide("00000000000000000000000000000000", owner.user, "47") == "unknown"


def test_link_creation_is_throttled_per_client_ip(browser, settings):
    for _ in range(10):
        browser.start(REMOTE_ADDR="10.0.0.1")
    blocked = browser.client.post(
        LINKS,
        HTTP_X_REQUESTED_WITH="dashboard",
        HTTP_ORIGIN="http://testserver",
        REMOTE_ADDR="10.0.0.1",
    )
    assert blocked.status_code == 429
    # Behind one proxy (NUM_PROXIES=1) the client is the last X-Forwarded-For hop, not Caddy.
    other_client = browser.client.post(
        LINKS,
        HTTP_X_REQUESTED_WITH="dashboard",
        HTTP_ORIGIN="http://testserver",
        REMOTE_ADDR="10.0.0.1",
        HTTP_X_FORWARDED_FOR="84.54.70.1",
    )
    assert other_client.status_code == 201


def test_the_stored_ip_is_the_client_behind_the_proxy(browser):
    link = browser.start(
        REMOTE_ADDR="172.18.0.5", HTTP_X_FORWARDED_FOR="203.0.113.9, 213.230.86.14"
    )

    assert LoginLink.objects.get(pk=link["id"]).ip == "213.230.86.14"


def test_polling_is_throttled_per_link(browser):
    browser.start()
    for _ in range(60):
        assert browser.poll().status_code == 200

    assert browser.poll().status_code == 429
    # Another link has its own allowance.
    browser.start()
    assert browser.poll().status_code == 200


def test_claiming_is_throttled_per_ip(browser):
    browser.start()
    for _ in range(10):
        browser.claim(token="guess", REMOTE_ADDR="10.0.0.7")

    assert browser.claim(REMOTE_ADDR="10.0.0.7").status_code == 429


def test_the_hourly_job_stores_expiry_and_deletes_old_links(browser, owner):
    browser.start()
    old = LoginLink.objects.get(pk=browser.link["id"])
    approved = browser.start()
    tap_right(owner.user, browser)

    fresh = browser.start()  # still within its 3 minutes

    expired, deleted = housekeeping.expire_login_links(
        now=timezone.now() + timedelta(minutes=2, seconds=30)
    )
    assert (expired, deleted) == (1, 0)  # only the approval nobody claimed in 2 minutes
    assert LoginLink.objects.get(pk=approved["id"]).status == LoginLink.Status.EXPIRED

    expired, deleted = housekeeping.expire_login_links(now=timezone.now() + timedelta(minutes=10))
    assert (expired, deleted) == (2, 0)
    assert LoginLink.objects.get(pk=old.pk).status == LoginLink.Status.EXPIRED
    assert LoginLink.objects.get(pk=fresh["id"]).status == LoginLink.Status.EXPIRED

    assert housekeeping.expire_login_links(now=timezone.now() + timedelta(days=8)) == (0, 3)
    assert not LoginLink.objects.exists()


def test_the_prompt_names_the_browser_and_masks_the_ip(browser, owner):
    browser.start(
        HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0 Safari/537.36",
        REMOTE_ADDR="213.230.86.14",
    )

    text, _markup = bot_flow.start(owner.user, browser.code)

    assert "Chrome · Windows" in text
    assert "213.230.x.x" in text and "86.14" not in text
