"""The root conftest fixtures every package uses (docs/PLAN-OWNER.md §11.1, rule 22)."""

import pytest
from django.conf import settings as django_settings
from django.core.files.base import ContentFile

from apps.core import redis as core_redis
from apps.core.storage import private_storage
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.notifications import telegram

pytestmark = pytest.mark.django_db


def test_private_files_land_in_a_throwaway_directory(private_media, tmp_path):
    name = private_storage.save("exports/1/a.csv", ContentFile(b"x"))

    assert private_media == tmp_path / "private_media"
    assert (private_media / name).read_bytes() == b"x"
    assert private_media == django_settings.PRIVATE_MEDIA_ROOT


def test_api_as_signs_in_to_the_mini_app(company, member, api_as):
    worker = member(company)

    assert api_as(worker).get("/api/v1/me/").status_code == 200
    assert api_as(worker).get("/api/v1/owner/me/").status_code == 401


def test_owner_api_signs_in_to_the_dashboard(company, member, owner_api):
    owner = member(company, "Owner")

    assert owner_api(owner).get("/api/v1/owner/me/").status_code == 200
    assert owner_api(owner).get("/api/v1/me/").status_code == 401


def test_demo_people_are_the_six_demo_memberships(company, demo_people):
    people = demo_people(company)

    assert set(people) == {"owner", "manager", "worker", "madina", "jasur", "nigora"}
    assert all(p.status == Membership.Status.APPROVED and p.is_onboarded for p in people.values())
    assert people["owner"].role.is_owner
    assert people["manager"].has_perm(Perm.TASKS_VIEW_ALL)
    assert not people["worker"].has_perm(Perm.DASHBOARD_ACCESS)
    assert (people["madina"].full_name, people["madina"].position.name) == (
        "Madina Saidova",
        "Senior pharmacist",
    )
    branch = people["worker"].home_branch
    assert branch is not None and branch.company == company
    assert list(people["worker"].branches.all()) == [branch]


def test_demo_people_can_be_made_for_two_companies(company, other_company, demo_people):
    first, second = demo_people(company), demo_people(other_company)

    assert first["owner"].user != second["owner"].user


def test_fake_redis_is_in_memory_and_prefixed(fake_redis, settings):
    client = core_redis.get_redis()
    client.set(core_redis.key("test", 1), "yes")

    assert client.get(f"{settings.REDIS_KEY_PREFIX}test:1") == "yes"
    assert settings.REDIS_KEY_PREFIX.startswith("t:")


def test_sent_messages_records_the_storage_too(sent_messages):
    telegram.send_message("employee", 1, "Hi", None, "receipts/1/a.jpg", "private")

    assert sent_messages[0]["photo_storage"] == "private"
