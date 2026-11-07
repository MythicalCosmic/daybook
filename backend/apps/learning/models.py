"""Models of learning: lessons, courses, quizzes and who did what (docs/PLAN-LEARNING.md §3).

A company teaches its people with **lessons** (a video uploaded or linked from YouTube, with
notes) and the knowledge base's pages, puts them in order in **courses** with **quizzes**
between them, and makes some courses **mandatory** for an audience (positions, branches or
everyone), with a deadline and a renewal. Each person's run through a course is an
**assignment** (one per cycle); each step they finish is a **step completion**.

Who watched what is **lesson progress**: the parts of the video the person actually played
(merged ranges of seconds, so skipping ahead never counts), the share of the video that makes,
where to resume and the time spent. Pages keep their own views (`knowledge.PageView`).

A quiz draws its **questions** (seven kinds) from a fixed list or at random from topics. Each
**attempt** keeps what was drawn and in which order, the answers and the score; every answered
question is also an **answer log** row, the skill matrix's raw data. People also get one
**daily question** on workdays and answer **regular checks** (`RegularCheck`: a quiz sent to an
audience every week or month with a deadline). The tutor agent turns the results into
**suggestions**.

Everything is per company (`TenantModel`); module switch `learning` (`Company.features`).
"""

from datetime import time

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, Company, TenantModel
from apps.core.storage import learning_storage, private_storage, private_upload_to
from apps.knowledge.models import Page, Topic
from apps.members.models import Membership, Position


class Status(models.TextChoices):
    """Where a course, lesson or quiz is: only published ones reach people."""

    DRAFT = "draft", _("Draft")
    PUBLISHED = "published", _("Published")
    ARCHIVED = "archived", _("Archived")


class LearningSettings(models.Model):
    """The company's learning settings. Lazy: `apps.learning.conf.get_settings(company)`."""

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="learning_settings"
    )
    completion_percent = models.PositiveSmallIntegerField(
        default=90, help_text=_("A video counts as watched once this share of it was played.")
    )
    max_speed_percent = models.PositiveSmallIntegerField(
        default=200,
        help_text=_("Watching faster than this (percent of normal speed) doesn't count more."),
    )
    remind_before_days = models.PositiveSmallIntegerField(
        default=2, help_text=_("Remind people this many days before a deadline (0: never).")
    )
    escalate_after_days = models.PositiveSmallIntegerField(
        default=3,
        help_text=_("Tell the person's manager after this many days late (0: never)."),
    )
    certificates = models.BooleanField(
        default=True, help_text=_("Give a certificate when someone finishes a course.")
    )
    certificate_prefix = models.CharField(max_length=8, default="SRT")
    next_certificate_number = models.PositiveIntegerField(default=1)
    catalog_for_staff = models.BooleanField(
        default=True, help_text=_("People can open optional courses meant for them on their own.")
    )
    daily_question = models.BooleanField(
        default=False, help_text=_("Send everyone one question on each workday.")
    )
    daily_at = models.TimeField(default=time(11, 0))
    daily_position_ids = ArrayField(
        models.PositiveBigIntegerField(),
        default=list,
        blank=True,
        help_text=_("Only people in these positions get the daily question (empty: everyone)."),
    )
    storage_limit_mb = models.PositiveIntegerField(
        default=10240, help_text=_("How much video the company may keep, in megabytes.")
    )

    def __str__(self):
        return f"Learning settings of {self.company_id}"


class Video(TenantModel):
    """An uploaded video: received in pieces, then made into a 720p MP4 with a poster by the
    media worker (§5). The original is deleted once the MP4 is ready."""

    class State(models.TextChoices):
        UPLOADING = "uploading", _("Uploading")
        PROCESSING = "processing", _("Processing")
        READY = "ready", _("Ready")
        FAILED = "failed", _("Couldn't be processed")

    state = models.CharField(max_length=12, choices=State.choices, default=State.UPLOADING)
    error = models.CharField(max_length=300, blank=True)
    original_name = models.CharField(max_length=200, blank=True)
    original_bytes = models.PositiveBigIntegerField(default=0)
    received_bytes = models.PositiveBigIntegerField(default=0)
    upload_expires_at = models.DateTimeField(null=True, blank=True)
    file = models.FileField(
        storage=learning_storage, upload_to=private_upload_to("videos"), blank=True
    )
    poster = models.FileField(
        storage=learning_storage, upload_to=private_upload_to("posters"), blank=True
    )
    size_bytes = models.PositiveBigIntegerField(default=0, help_text=_("Size of the MP4 kept."))
    duration_seconds = models.PositiveIntegerField(default=0)
    width = models.PositiveSmallIntegerField(default=0)
    height = models.PositiveSmallIntegerField(default=0)
    processed_at = models.DateTimeField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["company", "state"])]

    def __str__(self):
        return self.original_name or f"Video #{self.pk}"


class LearningImage(TenantModel):
    """A picture in a question (re-encoded on upload, private storage, signed links)."""

    file = models.FileField(storage=private_storage, upload_to=private_upload_to("learning"))
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )


class Lesson(TenantModel):
    """A video lesson with notes. Inside a course the course decides who sees it; on its own a
    published lesson is open to its audience."""

    class Source(models.TextChoices):
        UPLOAD = "upload", _("Uploaded video")
        YOUTUBE = "youtube", _("YouTube")

    title = models.CharField(max_length=200)
    emoji = models.CharField(max_length=16, blank=True)
    summary = models.CharField(max_length=300, blank=True)
    notes = models.TextField(blank=True, help_text=_("Sanitized HTML (knowledge.sanitize)."))
    notes_text = models.TextField(blank=True, help_text=_("Plain text of the notes, for search."))
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.UPLOAD)
    video = models.ForeignKey(
        Video, on_delete=models.SET_NULL, null=True, blank=True, related_name="lessons"
    )
    youtube_id = models.CharField(max_length=16, blank=True)
    duration_seconds = models.PositiveIntegerField(
        default=0, help_text=_("From the video, or the first player report for YouTube.")
    )
    transcript = models.TextField(blank=True, help_text=_("What is said, typed or transcribed."))
    topics = models.ManyToManyField(Topic, blank=True, related_name="lessons")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    audience_all = models.BooleanField(default=True)
    positions = models.ManyToManyField(Position, blank=True, related_name="learning_lessons")
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["company", "status"])]

    def __str__(self):
        return self.title


class Question(TenantModel):
    """One question of the company's bank. `data` holds the options and the right answer in the
    shape of its kind (§4.3); it never leaves the server before an attempt is finished."""

    class Kind(models.TextChoices):
        SINGLE = "single", _("One right answer")
        MULTI = "multi", _("Several right answers")
        TRUE_FALSE = "true_false", _("True or false")
        ORDER = "order", _("Put in order")
        MATCH = "match", _("Match pairs")
        TEXT = "text", _("Type the answer")
        NUMBER = "number", _("Number")

    class Difficulty(models.TextChoices):
        EASY = "easy", _("Easy")
        MEDIUM = "medium", _("Medium")
        HARD = "hard", _("Hard")

    class State(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ACTIVE = "active", _("Active")
        ARCHIVED = "archived", _("Archived")

    class Source(models.TextChoices):
        MANUAL = "manual", _("Written by hand")
        AI = "ai", _("Written by AI")
        RULES = "rules", _("Made from the text")
        COPY = "copy", _("Copied")

    kind = models.CharField(max_length=12, choices=Kind.choices)
    text = models.TextField()
    image = models.ForeignKey(
        LearningImage, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    data = models.JSONField(default=dict)
    explanation = models.TextField(blank=True, help_text=_("Shown once the person has answered."))
    topic = models.ForeignKey(
        Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name="questions"
    )
    difficulty = models.CharField(
        max_length=8, choices=Difficulty.choices, default=Difficulty.MEDIUM
    )
    points = models.PositiveSmallIntegerField(default=1)
    state = models.CharField(max_length=10, choices=State.choices, default=State.ACTIVE)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL)
    lesson = models.ForeignKey(
        Lesson, on_delete=models.SET_NULL, null=True, blank=True, related_name="questions"
    )
    page = models.ForeignKey(
        Page, on_delete=models.SET_NULL, null=True, blank=True, related_name="questions"
    )
    answered = models.PositiveIntegerField(default=0)
    correct = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    draft_job = models.ForeignKey(
        "QuestionDraftJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="questions",
        help_text=_("The job that wrote it from a page or a lesson."),
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["company", "state", "topic"])]

    def __str__(self):
        return self.text[:60]


class Quiz(TenantModel):
    """A test: a fixed list of questions, or `question_count` drawn at random from `topics`
    (and the fixed list) for each attempt."""

    class Mode(models.TextChoices):
        FIXED = "fixed", _("The same questions every time")
        RANDOM = "random", _("Questions drawn at random")

    class ShowAnswers(models.TextChoices):
        AFTER = "after", _("After each attempt")
        PASSED = "passed", _("Only once passed")
        NEVER = "never", _("Never")

    title = models.CharField(max_length=200)
    emoji = models.CharField(max_length=16, blank=True)
    description = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.FIXED)
    question_count = models.PositiveSmallIntegerField(default=10)
    topics = models.ManyToManyField(Topic, blank=True, related_name="quizzes")
    shuffle_questions = models.BooleanField(default=True)
    shuffle_options = models.BooleanField(default=True)
    time_limit_seconds = models.PositiveIntegerField(null=True, blank=True)
    pass_percent = models.PositiveSmallIntegerField(default=70)
    max_attempts = models.PositiveSmallIntegerField(null=True, blank=True)
    retry_after_minutes = models.PositiveIntegerField(default=0)
    partial_credit = models.BooleanField(default=True)
    show_answers = models.CharField(
        max_length=8, choices=ShowAnswers.choices, default=ShowAnswers.AFTER
    )
    audience_all = models.BooleanField(default=True)
    positions = models.ManyToManyField(Position, blank=True, related_name="learning_quizzes")
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["company", "status"])]

    def __str__(self):
        return self.title


class QuizQuestion(TenantModel):
    """A question in a quiz's fixed list, in its place."""

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="items")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="+")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["quiz", "question"], name="learning_unique_quiz_item")
        ]


class Course(TenantModel):
    """Steps in order (lessons, pages, quizzes). A mandatory course is assigned to everyone in its
    audience, with `due_days` to finish and a renewal `renew_months` after finishing."""

    title = models.CharField(max_length=200)
    emoji = models.CharField(max_length=16, blank=True)
    color = models.CharField(max_length=16, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    mandatory = models.BooleanField(default=False)
    audience_all = models.BooleanField(default=True)
    positions = models.ManyToManyField(Position, blank=True, related_name="learning_courses")
    branches = models.ManyToManyField(
        Branch, blank=True, related_name="learning_courses", help_text=_("Empty: every branch.")
    )
    due_days = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text=_("Days to finish once assigned (empty: no deadline).")
    )
    renew_months = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text=_("Assigned again this many months after finishing.")
    )
    sequential = models.BooleanField(default=True, help_text=_("Steps open one after another."))
    certificate = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["position", "pk"]
        indexes = [models.Index(fields=["company", "status", "mandatory"])]

    def __str__(self):
        return self.title


class CourseStep(TenantModel):
    """One step of a course: a lesson, a knowledge base page or a quiz."""

    class Kind(models.TextChoices):
        LESSON = "lesson", _("Lesson")
        PAGE = "page", _("Page")
        QUIZ = "quiz", _("Quiz")

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="steps")
    position = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    lesson = models.ForeignKey(
        Lesson, on_delete=models.PROTECT, null=True, blank=True, related_name="steps"
    )
    page = models.ForeignKey(
        Page, on_delete=models.PROTECT, null=True, blank=True, related_name="learning_steps"
    )
    quiz = models.ForeignKey(
        Quiz, on_delete=models.PROTECT, null=True, blank=True, related_name="steps"
    )
    required = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind="lesson", lesson__isnull=False, page__isnull=True, quiz__isnull=True)
                    | Q(kind="page", lesson__isnull=True, page__isnull=False, quiz__isnull=True)
                    | Q(kind="quiz", lesson__isnull=True, page__isnull=True, quiz__isnull=False)
                ),
                name="learning_step_one_target",
            )
        ]


class Assignment(TenantModel):
    """One person's run through one course, per cycle (a renewal starts the next cycle)."""

    class State(models.TextChoices):
        ASSIGNED = "assigned", _("Not started")
        IN_PROGRESS = "in_progress", _("In progress")
        COMPLETED = "completed", _("Completed")
        EXEMPT = "exempt", _("Exempt")
        CANCELLED = "cancelled", _("Cancelled")

    class Source(models.TextChoices):
        AUDIENCE = "audience", _("Mandatory for their position")
        MANUAL = "manual", _("Assigned by a manager")
        TUTOR = "tutor", _("Suggested by the tutor")
        SELF = "self", _("Started on their own")
        RENEWAL = "renewal", _("Renewal")

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="assignments")
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="learning_assignments"
    )
    cycle = models.PositiveSmallIntegerField(default=1)
    state = models.CharField(max_length=12, choices=State.choices, default=State.ASSIGNED)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    assigned_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    assigned_at = models.DateTimeField()
    due_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    steps_done = models.PositiveSmallIntegerField(default=0)
    steps_total = models.PositiveSmallIntegerField(default=0)
    percent = models.PositiveSmallIntegerField(default=0)
    reminded_at = models.DateTimeField(null=True, blank=True)
    overdue_notices = models.PositiveSmallIntegerField(default=0)
    escalated_at = models.DateTimeField(null=True, blank=True)
    certificate_no = models.CharField(max_length=24, blank=True)
    expires_at = models.DateTimeField(
        null=True, blank=True, help_text=_("When the renewal is due (courses that renew).")
    )
    exempt_reason = models.CharField(max_length=200, blank=True)
    closed_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-assigned_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "membership", "cycle"], name="learning_unique_assignment"
            )
        ]
        indexes = [
            models.Index(fields=["company", "state", "due_at"]),
            models.Index(fields=["membership", "state"]),
        ]

    def __str__(self):
        return f"{self.course_id}/{self.membership_id}#{self.cycle}"


class LessonProgress(TenantModel):
    """Who watched what: the ranges of the video `membership` actually played (merged, in
    seconds), the share they make, where to resume and the playing time accepted (§4.2)."""

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="progress")
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="lesson_progress"
    )
    ranges = models.JSONField(default=list)
    watched_seconds = models.PositiveIntegerField(default=0)
    percent = models.PositiveSmallIntegerField(default=0)
    position = models.PositiveIntegerField(default=0, help_text=_("Where to resume, in seconds."))
    spent_seconds = models.PositiveIntegerField(default=0)
    sessions = models.PositiveIntegerField(default=0)
    first_at = models.DateTimeField()
    last_at = models.DateTimeField()
    last_report_at = models.DateTimeField(null=True, blank=True)
    last_session = models.CharField(max_length=40, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["lesson", "membership"], name="learning_unique_lesson_progress"
            )
        ]
        indexes = [
            models.Index(fields=["company", "lesson"]),
            models.Index(fields=["membership", "-last_at"]),
        ]


class RegularCheck(TenantModel):
    """A regular check: the quiz sent to an audience every week or month, to answer within
    `answer_within_hours` ("every Monday, five questions on the cold chain")."""

    class Every(models.TextChoices):
        WEEK = "week", _("Every week")
        MONTH = "month", _("Every month")

    class State(models.TextChoices):
        ACTIVE = "active", _("Active")
        PAUSED = "paused", _("Paused")
        ARCHIVED = "archived", _("Archived")

    title = models.CharField(max_length=200)
    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT, related_name="checks")
    state = models.CharField(max_length=10, choices=State.choices, default=State.ACTIVE)
    every = models.CharField(max_length=6, choices=Every.choices, default=Every.WEEK)
    weekday = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text=_("0 is Monday (weekly checks).")
    )
    month_day = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text=_("1–28 (monthly checks).")
    )
    at = models.TimeField(default=time(10, 0))
    answer_within_hours = models.PositiveSmallIntegerField(default=48)
    audience_all = models.BooleanField(default=True)
    positions = models.ManyToManyField(Position, blank=True, related_name="learning_checks")
    branches = models.ManyToManyField(Branch, blank=True, related_name="learning_checks")
    next_run_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["title", "pk"]
        indexes = [models.Index(fields=["state", "next_run_at"])]

    def __str__(self):
        return self.title


class CheckRound(TenantModel):
    """One sending of a check: who had to answer by when, and how it went (cached counts)."""

    regular_check = models.ForeignKey(RegularCheck, on_delete=models.CASCADE, related_name="rounds")
    starts_at = models.DateTimeField()
    due_at = models.DateTimeField()
    people = models.PositiveIntegerField(default=0)
    finished = models.PositiveIntegerField(default=0)
    passed = models.PositiveIntegerField(default=0)
    closed_at = models.DateTimeField(null=True, blank=True)
    half_reminded_at = models.DateTimeField(
        null=True, blank=True, help_text=_("When the reminder at half time went out.")
    )
    last_reminded_at = models.DateTimeField(
        null=True, blank=True, help_text=_("When the reminder two hours before the end went out.")
    )

    class Meta:
        ordering = ["-starts_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["regular_check", "starts_at"], name="learning_unique_check_round"
            )
        ]


class Attempt(TenantModel):
    """One go at a quiz. `items` is what was drawn, in the order shown
    (`[{"question": id, "kind": k, "points": p, "order": [option ids as shown]}]`); `answers`
    maps question ids (as strings) to the person's answers; grading happens on the server."""

    class State(models.TextChoices):
        IN_PROGRESS = "in_progress", _("In progress")
        FINISHED = "finished", _("Finished")
        EXPIRED = "expired", _("Time ran out")
        ABANDONED = "abandoned", _("Abandoned")

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="attempts")
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="quiz_attempts"
    )
    assignment = models.ForeignKey(
        Assignment, on_delete=models.SET_NULL, null=True, blank=True, related_name="attempts"
    )
    check_entry = models.ForeignKey(
        "CheckEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="attempts"
    )
    number = models.PositiveSmallIntegerField(default=1)
    state = models.CharField(max_length=12, choices=State.choices, default=State.IN_PROGRESS)
    started_at = models.DateTimeField()
    deadline_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    items = models.JSONField(default=list)
    answers = models.JSONField(default=dict)
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    max_score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    percent = models.PositiveSmallIntegerField(null=True, blank=True)
    passed = models.BooleanField(null=True, blank=True)
    trial = models.BooleanField(
        default=False,
        help_text=_("A manager trying the quiz: never counts in results, skills or points."),
    )
    reset_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("A manager let the person start again: no longer counts against the limit."),
    )
    points = models.SmallIntegerField(
        null=True, blank=True, help_text=_("Points it earned (empty while recognition is off).")
    )
    course_step_done = models.BooleanField(default=False)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["membership", "quiz", "-started_at"]),
            models.Index(fields=["company", "quiz", "state"]),
        ]


class CheckEntry(TenantModel):
    """One person who had to answer one round of a check, and the attempt that answered it."""

    check_round = models.ForeignKey(CheckRound, on_delete=models.CASCADE, related_name="entries")
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="check_entries"
    )
    attempt = models.ForeignKey(
        Attempt, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reminded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["check_round", "membership"], name="learning_unique_check_entry"
            )
        ]


class StepCompletion(TenantModel):
    """A step of a course finished within an assignment's cycle."""

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="completions")
    step = models.ForeignKey(CourseStep, on_delete=models.CASCADE, related_name="completions")
    done_at = models.DateTimeField()
    attempt = models.ForeignKey(
        Attempt, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["done_at"]
        constraints = [
            models.UniqueConstraint(fields=["assignment", "step"], name="learning_unique_step_done")
        ]


class DailyQuestion(TenantModel):
    """The question of the day `membership` got on `day` (the company's date) and their answer."""

    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="daily_questions"
    )
    day = models.DateField()
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="+")
    order = models.JSONField(default=list, help_text=_("Option ids in the order shown."))
    sent_at = models.DateTimeField(null=True, blank=True)
    chat_message_id = models.BigIntegerField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    answer = models.JSONField(null=True, blank=True)
    correct = models.BooleanField(null=True, blank=True)

    class Meta:
        ordering = ["-day"]
        constraints = [
            models.UniqueConstraint(fields=["membership", "day"], name="learning_unique_daily")
        ]
        indexes = [models.Index(fields=["company", "day"])]


class AnswerLog(TenantModel):
    """One answered question (in an attempt, a check or the daily question): the skill matrix's
    raw data. `share` is the part of the points earned (0 to 1; partial credit)."""

    class Source(models.TextChoices):
        ATTEMPT = "attempt", _("Quiz")
        CHECK = "check", _("Regular check")
        DAILY = "daily", _("Question of the day")

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="+")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answer_logs")
    topic = models.ForeignKey(
        Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    source = models.CharField(max_length=8, choices=Source.choices)
    attempt = models.ForeignKey(
        Attempt, on_delete=models.CASCADE, null=True, blank=True, related_name="answer_logs"
    )
    daily = models.ForeignKey(
        DailyQuestion, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    correct = models.BooleanField()
    share = models.DecimalField(max_digits=4, decimal_places=3)
    at = models.DateTimeField()

    class Meta:
        ordering = ["-at"]
        indexes = [
            models.Index(fields=["company", "membership", "topic", "-at"]),
            models.Index(fields=["company", "question"]),
        ]


class QuestionDraftJob(TenantModel):
    """Questions being written from a page or a lesson, by Claude or by the rules (§6.4)."""

    class State(models.TextChoices):
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        DONE = "done", _("Done")
        FAILED = "failed", _("Failed")

    class Engine(models.TextChoices):
        CLAUDE = "claude", _("Claude")
        RULES = "rules", _("Rules")

    page = models.ForeignKey(
        Page, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    lesson = models.ForeignKey(
        Lesson, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    topic = models.ForeignKey(
        Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    count = models.PositiveSmallIntegerField(default=5)
    kinds = ArrayField(models.CharField(max_length=12), default=list, blank=True)
    difficulty = models.CharField(max_length=8, blank=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.QUEUED)
    engine = models.CharField(max_length=8, choices=Engine.choices, default=Engine.RULES)
    made = models.PositiveSmallIntegerField(default=0)
    dropped = models.PositiveSmallIntegerField(
        default=0, help_text=_("Questions left out: not valid, or a number not in the text.")
    )
    error = models.CharField(max_length=300, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]


class TutorSuggestion(TenantModel):
    """Something the tutor proposes about a person (or the whole company, `membership` empty):
    worded when read, from `kind` and `params`. One open suggestion per person, kind, topic and
    course; accepting an `assign` one assigns the course."""

    class Kind(models.TextChoices):
        ASSIGN = "assign", _("Assign a course")
        PRACTICE = "practice", _("Practise a topic")
        LESSON_NEEDED = "lesson_needed", _("A lesson is missing")
        MENTOR = "mentor", _("Could coach others")
        PRAISE = "praise", _("Say thanks")
        OVERDUE = "overdue", _("Late with mandatory training")

    class State(models.TextChoices):
        OPEN = "open", _("Open")
        ACCEPTED = "accepted", _("Accepted")
        DISMISSED = "dismissed", _("Dismissed")
        DONE = "done", _("Resolved")

    membership = models.ForeignKey(
        Membership,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tutor_suggestions",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    state = models.CharField(max_length=10, choices=State.choices, default=State.OPEN)
    topic = models.ForeignKey(
        Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    course = models.ForeignKey(
        Course, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    lesson = models.ForeignKey(
        Lesson, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    params = models.JSONField(default=dict, blank=True)
    decided_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "membership", "kind", "topic", "course"],
                condition=Q(state="open"),
                nulls_distinct=False,
                name="learning_unique_open_suggestion",
            )
        ]
        indexes = [models.Index(fields=["company", "state", "-created_at"])]


# Published, not archived: what reaches people.
LIVE = Q(status=Status.PUBLISHED, archived_at__isnull=True)
