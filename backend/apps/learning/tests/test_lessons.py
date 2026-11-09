"""Lessons (docs/PLAN-LEARNING.md §4.2, §5): YouTube links, notes, topics, audience, publishing,
archiving, and what may be deleted."""

import pytest
from django.core.exceptions import PermissionDenied

from apps.core.exceptions import DomainError
from apps.knowledge import topics
from apps.learning import lessons, media
from apps.learning.models import Lesson, Status, Video
from apps.learning.tests.factories import CourseStepFactory, LessonFactory
from apps.learning.tests.helpers_courses import manager, turn_on
from apps.members.models import Position

pytestmark = pytest.mark.django_db


@pytest.fixture
def boss(company, member):
    turn_on(company)
    return manager(company, member)


@pytest.mark.parametrize(
    "link",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PL123",
        "http://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?si=abc",
        "youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ?start=10",
        "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
        "  dQw4w9WgXcQ  ",
    ],
)
def test_youtube_links_give_the_video_id(link):
    assert lessons.youtube_id(link) == "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "link",
    [
        "https://vimeo.com/12345678",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch?v=short",
        "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
        "javascript:alert(1)//youtu.be/dQw4w9WgXcQ",
        "ftp://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/@channel",
        "",
    ],
)
def test_anything_else_is_refused(link):
    with pytest.raises(DomainError):
        lessons.youtube_id(link)


def test_a_lesson_keeps_clean_notes_topics_and_its_audience(company, boss):
    cold = topics.create_topic(company, by=None, name="Sovuq zanjir")
    pharmacist = Position.objects.create(company=company, name="Pharmacist")
    lesson = lessons.create_lesson(
        company,
        by=boss,
        title="  Sovuq   zanjir ",
        source=Lesson.Source.YOUTUBE,
        youtube="https://youtu.be/dQw4w9WgXcQ",
        notes='<p onclick="x()">Muzlatgich <b>+2…+8</b></p><script>alert(1)</script>'
        '<img data-image-id="3" alt="">',
        topic_ids=[cold.pk],
        audience_all=False,
        position_ids=[pharmacist.pk],
    )
    assert lesson.title == "Sovuq zanjir"
    assert lesson.status == Status.DRAFT
    assert lesson.notes == "<p>Muzlatgich <b>+2…+8</b></p>"
    assert lesson.notes_text.startswith("Muzlatgich")
    assert list(lesson.topics.values_list("pk", flat=True)) == [cold.pk]
    assert list(lesson.positions.all()) == [pharmacist]
    with pytest.raises(DomainError):
        lessons.update_lesson(lesson, by=boss, position_ids=[])


def test_topics_and_videos_of_other_companies_are_refused(company, other_company, boss):
    theirs = topics.create_topic(other_company, by=None, name="Boshqa")
    with pytest.raises(DomainError):
        lessons.create_lesson(company, by=boss, title="A", topic_ids=[theirs.pk])
    video = Video.objects.create(company=other_company)
    with pytest.raises(DomainError):
        lessons.create_lesson(company, by=boss, title="A", video_id=video.pk)


def test_an_archived_topic_may_stay_on_a_lesson_but_isnt_added(company, boss):
    kept = topics.create_topic(company, by=None, name="Kassa")
    other = topics.create_topic(company, by=None, name="Retsept")
    lesson = lessons.create_lesson(company, by=boss, title="A", topic_ids=[kept.pk])
    topics.archive_topic(kept, by=None)
    topics.archive_topic(other, by=None)
    lessons.update_lesson(lesson, by=boss, topic_ids=[kept.pk])
    with pytest.raises(DomainError):
        lessons.update_lesson(lesson, by=boss, topic_ids=[kept.pk, other.pk])


def test_publishing_needs_something_to_watch(company, boss):
    empty = lessons.create_lesson(company, by=boss, title="Bo‘sh", source=Lesson.Source.UPLOAD)
    with pytest.raises(DomainError, match="Upload"):
        lessons.publish_lesson(empty, by=boss)
    video = Video.objects.create(company=company, state=Video.State.PROCESSING)
    lessons.update_lesson(empty, by=boss, video_id=video.pk)
    published = lessons.publish_lesson(empty, by=boss)  # plays once processed
    assert published.status == Status.PUBLISHED and published.published_at
    assert lessons.processing(published)
    link = lessons.create_lesson(company, by=boss, title="Havola", source=Lesson.Source.YOUTUBE)
    with pytest.raises(DomainError, match="YouTube"):
        lessons.publish_lesson(link, by=boss)


def test_a_failed_video_cant_be_picked(company, boss):
    video = Video.objects.create(company=company, state=Video.State.FAILED)
    with pytest.raises(DomainError, match="processed"):
        lessons.create_lesson(company, by=boss, title="A", video_id=video.pk)


def test_switching_to_youtube_forgets_the_upload_and_its_length(company, boss):
    video = Video.objects.create(company=company, state=Video.State.READY, duration_seconds=90)
    lesson = lessons.create_lesson(company, by=boss, title="A", video_id=video.pk)
    assert lesson.duration_seconds == 90
    lesson = lessons.update_lesson(
        lesson, by=boss, source=Lesson.Source.YOUTUBE, youtube="dQw4w9WgXcQ"
    )
    assert (lesson.video, lesson.youtube_id, lesson.duration_seconds) == (None, "dQw4w9WgXcQ", 0)


def test_archive_and_restore(company, boss):
    lesson = LessonFactory(company=company)
    archived = lessons.archive_lesson(lesson, by=boss)
    assert archived.status == Status.ARCHIVED and archived.archived_at
    with pytest.raises(DomainError):
        lessons.publish_lesson(archived, by=boss)
    restored = lessons.restore_lesson(archived, by=boss)
    assert restored.status == Status.PUBLISHED and restored.archived_at is None
    draft = lessons.create_lesson(company, by=boss, title="Draft")
    lessons.archive_lesson(draft, by=boss)
    assert lessons.restore_lesson(draft, by=boss).status == Status.DRAFT


def test_a_lesson_a_course_uses_isnt_deleted_and_an_unused_video_goes_with_it(
    company, boss, django_capture_on_commit_callbacks
):
    step = CourseStepFactory(course__company=company)
    with pytest.raises(DomainError, match="Archive"):
        lessons.delete_lesson(step.lesson, by=boss)
    video = media.start_upload(company, by=boss, name="x.mp4", size=10)
    lesson = lessons.create_lesson(company, by=boss, title="A", video_id=video.pk)
    shared = lessons.create_lesson(company, by=boss, title="B", video_id=video.pk)
    lessons.delete_lesson(lesson, by=boss)
    assert Video.objects.filter(pk=video.pk).exists()  # B still uses it
    with django_capture_on_commit_callbacks(execute=True):
        lessons.delete_lesson(shared, by=boss)
    assert not Video.objects.filter(pk=video.pk).exists()


def test_only_learning_managers_write_lessons(company, member):
    turn_on(company)
    with pytest.raises(PermissionDenied):
        lessons.create_lesson(company, by=member(company), title="A")
