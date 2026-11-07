"""Lesson videos through signed links (docs/PLAN-LEARNING.md §5): inline MP4s with byte ranges,
X-Accel-Redirect in production, and the `learning.video` check at download time."""

import pytest
from django.core.files.base import ContentFile

from apps.core.files import signed_url
from apps.core.storage import learning_storage
from apps.learning.models import Lesson, Status, Video
from apps.learning.tests.factories import LessonFactory
from apps.learning.tests.helpers_courses import manager, turn_on
from apps.members.models import Position

pytestmark = pytest.mark.django_db

DATA = bytes(range(256)) * 4  # 1 024 bytes


@pytest.fixture
def video(company):
    turn_on(company)
    name = learning_storage.save(f"videos/{company.pk}/abc.mp4", ContentFile(DATA))
    poster = learning_storage.save(f"posters/{company.pk}/abc.jpg", ContentFile(b"\xff\xd8\xff"))
    return Video.objects.create(
        company=company,
        state=Video.State.READY,
        file=name,
        poster=poster,
        size_bytes=len(DATA),
        duration_seconds=60,
    )


@pytest.fixture
def lesson(company, video):
    return LessonFactory(company=company, source=Lesson.Source.UPLOAD, video=video, youtube_id="")


def link(person, video, *, field="file", company_id=None) -> str:
    return signed_url(
        getattr(video, field),
        user=person.user,
        company_id=company_id or person.company_id,
        check=f"learning.video:{video.pk}",
    )


def content(response) -> bytes:
    return b"".join(response.streaming_content)


def test_the_whole_video_plays_inline_and_says_it_takes_ranges(client, company, member, lesson):
    staff = member(company)
    response = client.get(link(staff, lesson.video))
    assert response.status_code == 200
    assert content(response) == DATA
    assert response["Content-Type"] == "video/mp4"
    assert response["Content-Length"] == str(len(DATA))
    assert response["Accept-Ranges"] == "bytes"
    assert response["Content-Disposition"].startswith("inline")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Cache-Control"] == "private, max-age=3600"


@pytest.mark.parametrize(
    ("asked", "start", "end"),
    [
        ("bytes=0-1", 0, 1),
        ("bytes=100-199", 100, 199),
        ("bytes=1000-", 1000, 1023),
        ("bytes=-24", 1000, 1023),
        ("bytes=1000-5000", 1000, 1023),
    ],
)
def test_a_range_request_answers_206(client, company, member, lesson, asked, start, end):
    staff = member(company)
    response = client.get(link(staff, lesson.video), HTTP_RANGE=asked)
    assert response.status_code == 206
    assert content(response) == DATA[start : end + 1]
    assert response["Content-Range"] == f"bytes {start}-{end}/{len(DATA)}"
    assert response["Content-Length"] == str(end - start + 1)


@pytest.mark.parametrize("asked", ["bytes=2000-", "bytes=500-100", "bytes=-0"])
def test_a_range_outside_the_file_answers_416(client, company, member, lesson, asked):
    staff = member(company)
    response = client.get(link(staff, lesson.video), HTTP_RANGE=asked)
    assert response.status_code == 416
    assert response["Content-Range"] == f"bytes */{len(DATA)}"


def test_production_hands_the_bytes_to_the_web_server(client, company, member, lesson, settings):
    settings.LEARNING_MEDIA_ACCEL = "/_learning/"
    staff = member(company)
    response = client.get(link(staff, lesson.video), HTTP_RANGE="bytes=0-1")
    assert response.status_code == 200
    assert response.content == b""
    assert response["X-Accel-Redirect"] == f"/_learning/{lesson.video.file.name}"
    assert response["Content-Type"] == "video/mp4"
    poster = client.get(link(staff, lesson.video, field="poster"))
    assert poster["X-Accel-Redirect"] == f"/_learning/{lesson.video.poster.name}"


def test_another_companys_video_is_404(client, company, other_company, member, lesson):
    turn_on(other_company)
    stranger = manager(other_company, member)
    # A link made for their own company but naming this company's video.
    assert client.get(link(stranger, lesson.video)).status_code == 404


def test_the_link_stops_working_when_the_person_loses_access(client, company, member, lesson):
    pharmacist = Position.objects.create(company=company, name="Pharmacist")
    staff = member(company, position=pharmacist)
    url = link(staff, lesson.video)
    assert client.get(url).status_code == 200
    lesson.audience_all = False
    lesson.save()
    lesson.positions.set([Position.objects.create(company=company, name="Cashier")])
    assert client.get(url).status_code == 404
    lesson.positions.add(pharmacist)
    assert client.get(url).status_code == 200
    Lesson.objects.filter(pk=lesson.pk).update(status=Status.ARCHIVED)
    assert client.get(url).status_code == 404


def test_managers_open_drafts_and_nothing_opens_with_the_module_off(
    client, company, member, lesson
):
    Lesson.objects.filter(pk=lesson.pk).update(status=Status.DRAFT)
    boss = manager(company, member)
    staff = member(company)
    assert client.get(link(boss, lesson.video)).status_code == 200
    assert client.get(link(staff, lesson.video)).status_code == 404
    company.features = []
    company.save()
    assert client.get(link(boss, lesson.video)).status_code == 404
