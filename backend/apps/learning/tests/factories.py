"""factory_boy factories for the models of learning (both packages use them)."""

import factory
from django.utils import timezone

from apps.companies.tests.factories import CompanyFactory
from apps.knowledge.models import Topic
from apps.learning.models import (
    Assignment,
    Attempt,
    Course,
    CourseStep,
    Lesson,
    LessonProgress,
    Question,
    Quiz,
    QuizQuestion,
    RegularCheck,
    Status,
    Video,
)


class TopicFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Topic

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Topic {n}")


class VideoFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Video

    company = factory.SubFactory(CompanyFactory)
    state = Video.State.READY
    original_name = "lesson.mp4"
    duration_seconds = 300
    width = 1280
    height = 720


class LessonFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Lesson

    company = factory.SubFactory(CompanyFactory)
    title = factory.Sequence(lambda n: f"Lesson {n}")
    source = Lesson.Source.YOUTUBE
    youtube_id = "dQw4w9WgXcQ"
    duration_seconds = 300
    status = Status.PUBLISHED
    published_at = factory.LazyFunction(timezone.now)


class QuestionFactory(factory.django.DjangoModelFactory):
    """A one-right-answer question: "b" is right."""

    class Meta:
        model = Question

    company = factory.SubFactory(CompanyFactory)
    kind = Question.Kind.SINGLE
    text = factory.Sequence(lambda n: f"Question {n}?")
    data = factory.LazyFunction(
        lambda: {
            "options": [
                {"id": "a", "text": "One", "correct": False},
                {"id": "b", "text": "Two", "correct": True},
                {"id": "c", "text": "Three", "correct": False},
            ]
        }
    )


class QuizFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Quiz

    company = factory.SubFactory(CompanyFactory)
    title = factory.Sequence(lambda n: f"Quiz {n}")
    status = Status.PUBLISHED
    published_at = factory.LazyFunction(timezone.now)


class QuizQuestionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = QuizQuestion

    quiz = factory.SubFactory(QuizFactory)
    company = factory.SelfAttribute("quiz.company")
    question = factory.SubFactory(QuestionFactory, company=factory.SelfAttribute("..quiz.company"))


class CourseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Course

    company = factory.SubFactory(CompanyFactory)
    title = factory.Sequence(lambda n: f"Course {n}")
    status = Status.PUBLISHED
    published_at = factory.LazyFunction(timezone.now)


class CourseStepFactory(factory.django.DjangoModelFactory):
    """A lesson step by default; pass kind="quiz", quiz=… (and lesson=None) for a quiz step."""

    class Meta:
        model = CourseStep

    course = factory.SubFactory(CourseFactory)
    company = factory.SelfAttribute("course.company")
    kind = CourseStep.Kind.LESSON
    lesson = factory.SubFactory(LessonFactory, company=factory.SelfAttribute("..course.company"))
    position = factory.Sequence(lambda n: n)


class AssignmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Assignment

    course = factory.SubFactory(CourseFactory)
    company = factory.SelfAttribute("course.company")
    membership = factory.SubFactory(
        "apps.members.tests.factories.MembershipFactory",
        company=factory.SelfAttribute("..course.company"),
        status="approved",
    )
    assigned_at = factory.LazyFunction(timezone.now)


class LessonProgressFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LessonProgress

    lesson = factory.SubFactory(LessonFactory)
    company = factory.SelfAttribute("lesson.company")
    membership = factory.SubFactory(
        "apps.members.tests.factories.MembershipFactory",
        company=factory.SelfAttribute("..lesson.company"),
        status="approved",
    )
    first_at = factory.LazyFunction(timezone.now)
    last_at = factory.LazyFunction(timezone.now)


class AttemptFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Attempt

    quiz = factory.SubFactory(QuizFactory)
    company = factory.SelfAttribute("quiz.company")
    membership = factory.SubFactory(
        "apps.members.tests.factories.MembershipFactory",
        company=factory.SelfAttribute("..quiz.company"),
        status="approved",
    )
    started_at = factory.LazyFunction(timezone.now)


class RegularCheckFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RegularCheck

    quiz = factory.SubFactory(QuizFactory)
    company = factory.SelfAttribute("quiz.company")
    title = factory.Sequence(lambda n: f"Check {n}")
    weekday = 0
