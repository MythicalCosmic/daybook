"""Audit action codes and labels of learning (`apps.audit.registry.register`).

`CourseAction` is package Q1's (courses, lessons, videos, assignments), `QuizAction` package
Q2's (questions, quizzes, checks, the tutor's suggestions). Add codes to your own class only.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class CourseAction(models.TextChoices):
    SETTINGS_CHANGED = "learning.settings_changed", _("Changed the training settings")
    VIDEO_UPLOADED = "learning.video_uploaded", _("Uploaded a video")
    VIDEO_DELETED = "learning.video_deleted", _("Deleted a video")
    LESSON_CREATED = "learning.lesson_created", _("Added a lesson")
    LESSON_CHANGED = "learning.lesson_changed", _("Changed a lesson")
    LESSON_PUBLISHED = "learning.lesson_published", _("Published a lesson")
    LESSON_ARCHIVED = "learning.lesson_archived", _("Archived a lesson")
    LESSON_DELETED = "learning.lesson_deleted", _("Deleted a lesson")
    TRANSCRIPT_REQUESTED = "learning.transcript_requested", _("Had a lesson's video written down")
    COURSE_CREATED = "learning.course_created", _("Added a course")
    COURSE_CHANGED = "learning.course_changed", _("Changed a course")
    COURSE_PUBLISHED = "learning.course_published", _("Published a course")
    COURSE_ARCHIVED = "learning.course_archived", _("Archived a course")
    ASSIGNED = "learning.assigned", _("Assigned a course")
    EXEMPTED = "learning.exempted", _("Excused someone from a course")
    ASSIGNMENT_CANCELLED = "learning.assignment_cancelled", _("Took a course back")
    DUE_CHANGED = "learning.due_changed", _("Moved a training deadline")
    REMINDED = "learning.reminded", _("Reminded people about their training")


class QuizAction(models.TextChoices):
    QUESTION_CREATED = "learning.question_created", _("Added a question")
    QUESTION_CHANGED = "learning.question_changed", _("Changed a question")
    QUESTION_ARCHIVED = "learning.question_archived", _("Archived a question")
    QUESTIONS_DRAFTED = "learning.questions_drafted", _("Had questions written from a text")
    QUIZ_CREATED = "learning.quiz_created", _("Added a quiz")
    QUIZ_CHANGED = "learning.quiz_changed", _("Changed a quiz")
    QUIZ_PUBLISHED = "learning.quiz_published", _("Published a quiz")
    QUIZ_ARCHIVED = "learning.quiz_archived", _("Archived a quiz")
    ATTEMPT_RESET = "learning.attempt_reset", _("Let someone take a quiz again")
    CHECK_SAVED = "learning.check_saved", _("Saved a regular check")
    CHECK_ARCHIVED = "learning.check_archived", _("Archived a regular check")
    SUGGESTION_ACCEPTED = "learning.suggestion_accepted", _("Accepted a tutor's suggestion")
    SUGGESTION_DISMISSED = "learning.suggestion_dismissed", _("Dismissed a tutor's suggestion")
    QUESTION_ACTIVATED = "learning.question_activated", _("Put a question into use")
    QUESTION_DELETED = "learning.question_deleted", _("Deleted a question")
    QUIZ_RESTORED = "learning.quiz_restored", _("Brought a quiz back as a draft")
    QUIZ_DELETED = "learning.quiz_deleted", _("Deleted a quiz")
    CHECK_PAUSED = "learning.check_paused", _("Paused a regular check")
    CHECK_RESUMED = "learning.check_resumed", _("Restarted a regular check")
    DAILY_CHANGED = "learning.daily_changed", _("Changed the question of the day")
    TUTOR_QUESTIONS_DRAFTED = (
        "learning.tutor_questions_drafted",
        _("Had the tutor draft questions in a chat"),
    )
    TUTOR_QUIZ_DRAFTED = "learning.tutor_quiz_drafted", _("Had the tutor draft a quiz in a chat")
