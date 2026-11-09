"""The question bank and quizzes (package Q2; docs/PLAN-LEARNING.md §4.3, §4.7).

    question = quizzes.create_question(company, by=manager, kind="single", text="…", data={…})
    quiz = quizzes.create_quiz(company, by=manager, title="Sovuq zanjir testi", mode="random",
                               topic_ids=[3], question_count=5)
    quizzes.publish_quiz(quiz, by=manager)
    drawn = quizzes.draw(quiz, member)        # the questions of a new attempt, in order

Holders of `learning.manage` (or the system) write; every change is audited and moves the
`learning.quizzes` pulse key after commit. A question's `data` goes through `grading.clean_data`
on every save; its picture through `apps.core.uploads.sanitize_image` into a `LearningImage`
(private storage, signed links checked by `learning.image`).

**The draw** (§4.7). A fixed quiz asks its list in order (shuffled when `shuffle_questions`); a
random one draws `question_count` active questions from its topics and its list, spread over the
topics in turn, each topic giving first what the person didn't answer right in their last two
attempts of the quiz, and among those the kind drawn least so far (a mix of kinds, not five
true-or-false in a row). Fewer available than asked: all of them. Drafts and archived questions
are never drawn.
"""

from __future__ import annotations

import io
import random
from collections import Counter
from collections.abc import Iterable

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _
from PIL import Image

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.core.files import signed_url
from apps.core.uploads import sanitize_image
from apps.knowledge import topics as topic_services
from apps.knowledge.models import Page
from apps.learning import grading
from apps.learning.audit_actions import QuizAction
from apps.learning.models import (
    LIVE,
    AnswerLog,
    Attempt,
    DailyQuestion,
    LearningImage,
    Lesson,
    Question,
    Quiz,
    QuizQuestion,
    Status,
)
from apps.learning.services import ensure_manager
from apps.members.models import Membership, Position
from apps.members.permissions import Perm

PULSE_KEY = "learning.quizzes"
IMAGE_CHECK = "learning.image"
# Signed links of pictures last as long as a long attempt.
IMAGE_TTL = 6 * 60 * 60
IMAGE_SIDE = 1600
POINTS = (1, 10)
COUNT = (1, 50)
TIME_LIMIT = (30, 4 * 60 * 60)
MAX_ATTEMPTS = (1, 20)
RETRY_MINUTES = (0, 30 * 24 * 60)
EXPLANATION_MAX = 1000
TITLE_MAX = 200
DESCRIPTION_MAX = 500
# Finished attempts whose right answers a random draw avoids asking again.
RECENT_ATTEMPTS = 2

QUESTION_FIELDS = {
    "kind",
    "text",
    "data",
    "explanation",
    "topic_id",
    "difficulty",
    "points",
    "image_id",
    "lesson_id",
    "page_id",
}
QUIZ_FIELDS = {
    "title",
    "emoji",
    "description",
    "mode",
    "question_count",
    "shuffle_questions",
    "shuffle_options",
    "time_limit_seconds",
    "pass_percent",
    "max_attempts",
    "retry_after_minutes",
    "partial_credit",
    "show_answers",
    "audience_all",
    "position_ids",
    "topic_ids",
    "question_ids",
}


def _record(action: str, target, by: Membership | None, **details) -> None:
    audit.record(
        action,
        company_id=target.company_id,
        actor=by.user if by is not None else None,
        target=target,
        **details,
    )
    company_id = target.company_id
    transaction.on_commit(lambda: pulse.bump(company_id, PULSE_KEY))


def _whole(value, bounds: tuple[int, int], message: str, *, empty: bool = False) -> int | None:
    if value in (None, "") and empty:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            value = int(value)
        except TypeError, ValueError:
            raise DomainError(message) from None
    low, high = bounds
    if not low <= value <= high:
        raise DomainError(message)
    return value


# Pictures ----------------------------------------------------------------------------------


@transaction.atomic
def save_image(company, upload, *, by: Membership | None) -> LearningImage:
    """A picture for a question: decoded and re-encoded as JPEG (anything that isn't a
    picture is refused), kept privately."""
    ensure_manager(by)
    clean = sanitize_image(upload, max_side=IMAGE_SIDE)
    with Image.open(io.BytesIO(clean.read())) as picture:
        width, height = picture.size
    clean.seek(0)
    return LearningImage.objects.create(
        company=company,
        file=clean,
        width=width,
        height=height,
        uploaded_by=by.user if by is not None else None,
    )


def image_url(image: LearningImage | None, user) -> str | None:
    """A signed link to a question's picture for `user` (valid six hours)."""
    if image is None or not image.file:
        return None
    return signed_url(
        image.file,
        user=user,
        company_id=image.company_id,
        check=f"{IMAGE_CHECK}:{image.pk}",
        ttl=IMAGE_TTL,
    )


def may_open_image(user, company_id: int, image_id: int) -> bool:
    """`learning.image`: people who see training results, and anyone who was asked a question
    with this picture (in an attempt or as the question of the day)."""
    member = (
        Membership.objects.select_related("role")
        .filter(company_id=company_id, user=user, status=Membership.Status.APPROVED)
        .first()
    )
    if (
        member is None
        or not LearningImage.objects.filter(company_id=company_id, pk=image_id).exists()
    ):
        return False
    if member.has_perm(Perm.LEARNING_VIEW) or member.has_perm(Perm.LEARNING_MANAGE):
        return True
    asked = list(
        Question.objects.filter(company_id=company_id, image_id=image_id).values_list(
            "pk", flat=True
        )
    )
    if not asked:
        return False
    if DailyQuestion.objects.filter(membership=member, question_id__in=asked).exists():
        return True
    in_attempts = Q()
    for pk in asked:
        in_attempts |= Q(items__contains=[{"question": pk}])
    return Attempt.objects.filter(membership=member).filter(in_attempts).exists()


# Questions ---------------------------------------------------------------------------------


def _related(company, model, pk, message: str):
    if pk in (None, ""):
        return None
    found = model.objects.filter(company=company, pk=pk).first()
    if found is None:
        raise DomainError(message)
    return found


def _topic(company, topic_id, *, current: int | None = None):
    if topic_id in (None, ""):
        return None
    if current is not None and int(topic_id) == current:
        return current  # archived since, but kept where it was
    return topic_services.live_ids(company.pk, [topic_id])[0]


def _question_values(company, kind: str, changes: dict, question: Question | None) -> dict:
    values: dict = {}
    if "text" in changes:
        values["text"] = grading.clean_text(changes["text"])
    if "data" in changes or "kind" in changes:
        data = changes.get("data", question.data if question else None)
        values["data"] = grading.clean_data(kind, data)
    if "explanation" in changes:
        explanation = (changes["explanation"] or "").strip()
        if len(explanation) > EXPLANATION_MAX:
            raise DomainError(
                _("Keep the explanation under %(max)s characters.") % {"max": EXPLANATION_MAX}
            )
        values["explanation"] = explanation
    if "topic_id" in changes:
        values["topic_id"] = _topic(
            company, changes["topic_id"], current=question.topic_id if question else None
        )
    if "difficulty" in changes:
        if changes["difficulty"] not in Question.Difficulty.values:
            raise DomainError(_("Pick how hard the question is."))
        values["difficulty"] = changes["difficulty"]
    if "points" in changes:
        values["points"] = _whole(changes["points"], POINTS, _("A question is worth 1–10 points."))
    if "image_id" in changes:
        image = _related(
            company, LearningImage, changes["image_id"], _("Upload the picture again.")
        )
        values["image"] = image
    if "lesson_id" in changes:
        values["lesson"] = _related(company, Lesson, changes["lesson_id"], _("Pick a lesson."))
    if "page_id" in changes:
        values["page"] = _related(company, Page, changes["page_id"], _("Pick a page."))
    return values


@transaction.atomic
def create_question(
    company,
    *,
    by: Membership | None,
    kind: str,
    text: str,
    data: dict,
    state: str = Question.State.ACTIVE,
    source: str = Question.Source.MANUAL,
    draft_job=None,
    author: Membership | None = None,
    **fields,
) -> Question:
    """A question of the bank (`fields`: explanation, topic_id, difficulty, points, image_id,
    lesson_id, page_id). `author`: who asked for it, when the system writes it (`by` None)."""
    ensure_manager(by)
    unknown = set(fields) - QUESTION_FIELDS
    if unknown:
        raise ValueError(f"Unknown question fields: {sorted(unknown)}")
    if kind not in Question.Kind.values:
        raise grading.InvalidQuestion({"kind": [_("Pick a kind of question.")]})
    if state not in (Question.State.DRAFT, Question.State.ACTIVE):
        raise DomainError(_("A new question is a draft or in use."))
    values = _question_values(company, kind, {"text": text, "data": data, **fields}, None)
    question = Question.objects.create(
        company=company,
        kind=kind,
        state=state,
        source=source,
        created_by=by or author,
        draft_job=draft_job,
        **values,
    )
    _record(QuizAction.QUESTION_CREATED, question, by, kind=kind, source=source)
    return question


@transaction.atomic
def update_question(question: Question, *, by: Membership | None, **changes) -> Question:
    """Change what `QUESTION_FIELDS` names. The kind stays once someone has answered it (a new
    question is the honest way: the answers given were to the old one)."""
    ensure_manager(by)
    unknown = set(changes) - QUESTION_FIELDS
    if unknown:
        raise ValueError(f"Unknown question fields: {sorted(unknown)}")
    question = Question.objects.select_for_update().get(pk=question.pk)
    kind = changes.get("kind", question.kind)
    if kind not in Question.Kind.values:
        raise grading.InvalidQuestion({"kind": [_("Pick a kind of question.")]})
    if kind != question.kind and question.answered:
        raise DomainError(_("People have answered this question: make a new one instead."))
    values = _question_values(question.company, kind, changes, question)
    values["kind"] = kind
    before = {name: _value(question, name) for name in values}
    for name, value in values.items():
        setattr(question, name, value)
    changed = sorted(name for name in values if _value(question, name) != before[name])
    question.save()
    if changed:
        _record(QuizAction.QUESTION_CHANGED, question, by, fields=changed)
    return question


def _value(question: Question, name: str):
    return getattr(question, f"{name}_id" if name in ("image", "lesson", "page") else name)


@transaction.atomic
def set_question_state(question: Question, state: str, *, by: Membership | None) -> Question:
    """Put a question into use, back to draft or into the archive (never drawn again; quizzes
    and answers keep it)."""
    ensure_manager(by)
    if state not in Question.State.values:
        raise DomainError(_("Pick a state."))
    question = Question.objects.select_for_update().get(pk=question.pk)
    if question.state == state:
        return question
    if state == Question.State.ACTIVE:
        # A draft written from a text is checked again before it is asked.
        grading.clean_data(question.kind, question.data)
        grading.clean_text(question.text)
    question.state = state
    question.save(update_fields=["state", "updated_at"])
    action = {
        Question.State.ACTIVE: QuizAction.QUESTION_ACTIVATED,
        Question.State.ARCHIVED: QuizAction.QUESTION_ARCHIVED,
    }.get(state, QuizAction.QUESTION_CHANGED)
    _record(action, question, by, state=state)
    return question


def in_use(question: Question) -> bool:
    """Whether anyone was asked the question (an attempt, the question of the day)."""
    return (
        question.answered > 0
        or DailyQuestion.objects.filter(question=question).exists()
        or Attempt.objects.filter(
            company_id=question.company_id, items__contains=[{"question": question.pk}]
        ).exists()
    )


@transaction.atomic
def delete_question(question: Question, *, by: Membership | None) -> None:
    """Delete a question nobody was asked (a draft turned down); others go to the archive."""
    ensure_manager(by)
    if in_use(question):
        raise DomainError(_("People were asked this question: archive it instead."))
    _record(QuizAction.QUESTION_DELETED, question, by, kind=question.kind)
    QuizQuestion.objects.filter(question=question).delete()
    question.delete()


@transaction.atomic
def bulk_state(company, ids: Iterable[int], state: str, *, by: Membership | None) -> int:
    """`set_question_state` for each of the company's questions in `ids`; how many changed.
    A draft that isn't valid any more stays a draft (DomainError names the first)."""
    ensure_manager(by)
    rows = Question.objects.filter(company=company, pk__in=list(ids)).exclude(state=state)
    changed = 0
    for question in rows.order_by("pk"):
        set_question_state(question, state, by=by)
        changed += 1
    return changed


# Quizzes -----------------------------------------------------------------------------------


def _quiz_values(company, changes: dict) -> dict:
    values: dict = {}
    if "title" in changes:
        title = " ".join((changes["title"] or "").split())
        if not title:
            raise DomainError(_("Give the quiz a name."))
        if len(title) > TITLE_MAX:
            raise DomainError(_("Keep the name under %(max)s characters.") % {"max": TITLE_MAX})
        values["title"] = title
    if "emoji" in changes:
        values["emoji"] = (changes["emoji"] or "").strip()[:16]
    if "description" in changes:
        description = (changes["description"] or "").strip()
        if len(description) > DESCRIPTION_MAX:
            raise DomainError(
                _("Keep the description under %(max)s characters.") % {"max": DESCRIPTION_MAX}
            )
        values["description"] = description
    if "mode" in changes:
        if changes["mode"] not in Quiz.Mode.values:
            raise DomainError(_("Pick fixed or random questions."))
        values["mode"] = changes["mode"]
    if "question_count" in changes:
        values["question_count"] = _whole(
            changes["question_count"], COUNT, _("Ask 1–50 questions.")
        )
    for name in ("shuffle_questions", "shuffle_options", "partial_credit", "audience_all"):
        if name in changes:
            values[name] = bool(changes[name])
    if "time_limit_seconds" in changes:
        values["time_limit_seconds"] = _whole(
            changes["time_limit_seconds"],
            TIME_LIMIT,
            _("A time limit is 30 seconds to 4 hours, or none."),
            empty=True,
        )
    if "pass_percent" in changes:
        values["pass_percent"] = _whole(
            changes["pass_percent"], (1, 100), _("The pass mark is 1–100 %.")
        )
    if "max_attempts" in changes:
        values["max_attempts"] = _whole(
            changes["max_attempts"], MAX_ATTEMPTS, _("Allow 1–20 attempts, or any."), empty=True
        )
    if "retry_after_minutes" in changes:
        values["retry_after_minutes"] = _whole(
            changes["retry_after_minutes"] or 0,
            RETRY_MINUTES,
            _("The wait before another try is at most 30 days."),
        )
    if "show_answers" in changes:
        if changes["show_answers"] not in Quiz.ShowAnswers.values:
            raise DomainError(_("Pick when people see the right answers."))
        values["show_answers"] = changes["show_answers"]
    return values


def _set_relations(quiz: Quiz, changes: dict) -> list[str]:
    changed = []
    company = quiz.company
    if "position_ids" in changes:
        wanted = [int(pk) for pk in changes["position_ids"] or []]
        found = list(Position.objects.filter(company=company, pk__in=wanted))
        if len(found) != len(set(wanted)):
            raise DomainError(_("Pick positions of this company."))
        quiz.positions.set(found)
        changed.append("positions")
    if "topic_ids" in changes:
        current = set(quiz.topics.values_list("pk", flat=True))
        wanted = [int(pk) for pk in changes["topic_ids"] or []]
        fresh = [pk for pk in wanted if pk not in current]
        topic_services.live_ids(company.pk, fresh)  # new ones must be live; kept ones stay
        quiz.topics.set(wanted)
        changed.append("topics")
    if "question_ids" in changes:
        _set_list(quiz, changes["question_ids"] or [])
        changed.append("questions")
    return changed


def _set_list(quiz: Quiz, question_ids: list) -> None:
    wanted = list(dict.fromkeys(int(pk) for pk in question_ids))
    found = set(
        Question.objects.filter(company=quiz.company, pk__in=wanted)
        .exclude(state=Question.State.ARCHIVED)
        .values_list("pk", flat=True)
    )
    if len(found) != len(wanted):
        raise DomainError(_("Pick questions of this company that aren't archived."))
    QuizQuestion.objects.filter(quiz=quiz).exclude(question_id__in=wanted).delete()
    kept = {row.question_id: row for row in QuizQuestion.objects.filter(quiz=quiz)}
    for position, pk in enumerate(wanted):
        row = kept.get(pk)
        if row is None:
            QuizQuestion.objects.create(
                company=quiz.company, quiz=quiz, question_id=pk, position=position
            )
        elif row.position != position:
            row.position = position
            row.save(update_fields=["position", "updated_at"])


@transaction.atomic
def create_quiz(company, *, by: Membership | None, **fields) -> Quiz:
    ensure_manager(by)
    unknown = set(fields) - QUIZ_FIELDS
    if unknown:
        raise ValueError(f"Unknown quiz fields: {sorted(unknown)}")
    if "title" not in fields:
        raise DomainError(_("Give the quiz a name."))
    values = _quiz_values(company, fields)
    quiz = Quiz.objects.create(company=company, created_by=by, updated_by=by, **values)
    _set_relations(quiz, fields)
    _record(QuizAction.QUIZ_CREATED, quiz, by, mode=quiz.mode)
    return quiz


@transaction.atomic
def update_quiz(quiz: Quiz, *, by: Membership | None, **changes) -> Quiz:
    """Change what `QUIZ_FIELDS` names; attempts already started keep what they drew."""
    ensure_manager(by)
    unknown = set(changes) - QUIZ_FIELDS
    if unknown:
        raise ValueError(f"Unknown quiz fields: {sorted(unknown)}")
    quiz = Quiz.objects.select_for_update().get(pk=quiz.pk)
    values = _quiz_values(quiz.company, changes)
    changed = sorted(name for name, value in values.items() if getattr(quiz, name) != value)
    for name, value in values.items():
        setattr(quiz, name, value)
    quiz.updated_by = by
    quiz.save()
    changed += _set_relations(quiz, changes)
    if quiz.status == Status.PUBLISHED and not available(quiz):
        raise DomainError(_("A published quiz needs at least one question in use."))
    if changed:
        _record(QuizAction.QUIZ_CHANGED, quiz, by, fields=changed)
    return quiz


@transaction.atomic
def set_questions(quiz: Quiz, question_ids: list, *, by: Membership | None) -> Quiz:
    """The quiz's fixed list, in this order."""
    return update_quiz(quiz, by=by, question_ids=question_ids)


@transaction.atomic
def publish_quiz(quiz: Quiz, *, by: Membership | None) -> Quiz:
    ensure_manager(by)
    quiz = Quiz.objects.select_for_update().get(pk=quiz.pk)
    if not available(quiz):
        if quiz.mode == Quiz.Mode.FIXED:
            raise DomainError(_("Add at least one question in use to the list first."))
        raise DomainError(_("Pick topics with questions in use, or add questions to the list."))
    if quiz.status == Status.PUBLISHED and quiz.archived_at is None:
        return quiz
    quiz.status = Status.PUBLISHED
    quiz.published_at = quiz.published_at or timezone.now()
    quiz.archived_at = None
    quiz.updated_by = by
    quiz.save(update_fields=["status", "published_at", "archived_at", "updated_by", "updated_at"])
    _record(QuizAction.QUIZ_PUBLISHED, quiz, by)
    return quiz


@transaction.atomic
def archive_quiz(quiz: Quiz, *, by: Membership | None) -> Quiz:
    """Nobody starts it any more; attempts in progress can still be finished."""
    ensure_manager(by)
    quiz = Quiz.objects.select_for_update().get(pk=quiz.pk)
    if quiz.status == Status.ARCHIVED:
        return quiz
    quiz.status = Status.ARCHIVED
    quiz.archived_at = timezone.now()
    quiz.updated_by = by
    quiz.save(update_fields=["status", "archived_at", "updated_by", "updated_at"])
    _record(QuizAction.QUIZ_ARCHIVED, quiz, by)
    return quiz


@transaction.atomic
def restore_quiz(quiz: Quiz, *, by: Membership | None) -> Quiz:
    """An archived quiz back as a draft, to edit and publish again."""
    ensure_manager(by)
    quiz = Quiz.objects.select_for_update().get(pk=quiz.pk)
    if quiz.status != Status.ARCHIVED:
        return quiz
    quiz.status = Status.DRAFT
    quiz.archived_at = None
    quiz.updated_by = by
    quiz.save(update_fields=["status", "archived_at", "updated_by", "updated_at"])
    _record(QuizAction.QUIZ_RESTORED, quiz, by)
    return quiz


@transaction.atomic
def delete_quiz(quiz: Quiz, *, by: Membership | None) -> None:
    """Only a quiz nobody took and no course or check uses; others go to the archive."""
    ensure_manager(by)
    if quiz.attempts.exists() or quiz.steps.exists() or quiz.checks.exists():
        raise DomainError(_("This quiz was taken or is in a course or a check: archive it."))
    _record(QuizAction.QUIZ_DELETED, quiz, by, title=quiz.title)
    quiz.delete()


def is_live(quiz: Quiz) -> bool:
    return quiz.status == Status.PUBLISHED and quiz.archived_at is None


def live_quizzes(company) -> QuerySet[Quiz]:
    return Quiz.objects.filter(company=company).filter(LIVE)


# The draw ----------------------------------------------------------------------------------


def fixed_list(quiz: Quiz) -> list[Question]:
    """The quiz's list in order, questions in use only."""
    rows = (
        QuizQuestion.objects.filter(quiz=quiz, question__state=Question.State.ACTIVE)
        .select_related("question__image")
        .order_by("position", "pk")
    )
    return [row.question for row in rows]


def pool(quiz: Quiz) -> QuerySet[Question]:
    """What a random draw takes from: the questions in use of the quiz's topics and its list."""
    listed = QuizQuestion.objects.filter(quiz=quiz).values("question_id")
    return (
        Question.objects.filter(company_id=quiz.company_id, state=Question.State.ACTIVE)
        .filter(Q(topic__in=quiz.topics.all()) | Q(pk__in=listed))
        .select_related("image")
        .distinct()
    )


def available(quiz: Quiz) -> int:
    """How many questions an attempt of the quiz has."""
    if quiz.mode == Quiz.Mode.FIXED:
        return QuizQuestion.objects.filter(quiz=quiz, question__state=Question.State.ACTIVE).count()
    return min(quiz.question_count, pool(quiz).count())


def answered_right_lately(quiz: Quiz, member: Membership) -> set[int]:
    """Questions `member` answered right in their last two finished attempts of `quiz`."""
    recent = (
        Attempt.objects.filter(quiz=quiz, membership=member, trial=False)
        .filter(state__in=(Attempt.State.FINISHED, Attempt.State.EXPIRED))
        .order_by("-finished_at", "-pk")
        .values_list("pk", flat=True)[:RECENT_ATTEMPTS]
    )
    return set(
        AnswerLog.objects.filter(attempt_id__in=list(recent), correct=True).values_list(
            "question_id", flat=True
        )
    )


def draw(quiz: Quiz, member: Membership, *, rng: random.Random | None = None) -> list[Question]:
    """The questions of `member`'s next attempt, in the order they are asked (§4.7)."""
    rng = rng or random.SystemRandom()
    if quiz.mode == Quiz.Mode.FIXED:
        chosen = fixed_list(quiz)
    else:
        chosen = spread(
            list(pool(quiz).order_by("pk")),
            quiz.question_count,
            avoid=answered_right_lately(quiz, member),
            rng=rng,
        )
    if quiz.shuffle_questions:
        rng.shuffle(chosen)
    return chosen


def spread(
    questions: list[Question], count: int, *, avoid: set[int], rng: random.Random
) -> list[Question]:
    """`count` of `questions` taken from each topic in turn (no topic is one group too); each
    topic offers first what isn't in `avoid`, and of those the kind taken least so far."""
    groups: dict[int | None, tuple[list[Question], list[Question]]] = {}
    for question in questions:
        fresh, seen = groups.setdefault(question.topic_id, ([], []))
        (seen if question.pk in avoid else fresh).append(question)
    for fresh, seen in groups.values():
        rng.shuffle(fresh)
        rng.shuffle(seen)
    turns = list(groups)
    rng.shuffle(turns)
    kinds: Counter[str] = Counter()
    picked: list[Question] = []
    while len(picked) < count and any(fresh or seen for fresh, seen in groups.values()):
        for topic in turns:
            if len(picked) >= count:
                break
            fresh, seen = groups[topic]
            queue = fresh or seen
            if not queue:
                continue
            least = min(kinds[question.kind] for question in queue)
            choice = next(question for question in queue if kinds[question.kind] == least)
            queue.remove(choice)
            kinds[choice.kind] += 1
            picked.append(choice)
    return picked
