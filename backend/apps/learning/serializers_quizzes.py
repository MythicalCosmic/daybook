"""Serializers of package Q2's endpoints: the employee shapes of docs/PLAN-LEARNING.md §13
(the contract with the mini app) and the owner dashboard's.

The services build plain dicts; these describe them for the schema and the clients. Answers
and right answers keep their kind's own shape (§4.3): `{"option": "b"}`, `{"options": ["a",
"c"]}`, `{"value": false}`, `{"order": ["o3", "o1", "o2"]}`, `{"pairs": {"l1": "r2"}}`,
`{"text": "2-8"}`, `{"value": 4.5}`, in the ids the person was shown.
"""

from rest_framework import serializers

from apps.learning.models import Attempt, Question

ANSWER_HELP = (
    "The answer in its kind's shape, in the ids shown: single {option}, multi {options: []}, "
    "true_false {value: bool}, order {order: []}, match {pairs: {left id: right id}}, "
    "text {text}, number {value}."
)


class LearningPlayOptionSerializer(serializers.Serializer):
    id = serializers.CharField()
    text = serializers.CharField()


class LearningQuestionPlaySerializer(serializers.Serializer):
    """A question as the person sees it: never the right answer."""

    id = serializers.IntegerField()
    kind = serializers.ChoiceField(Question.Kind.choices)
    text = serializers.CharField()
    image_url = serializers.CharField(allow_null=True)
    points = serializers.IntegerField()
    options = LearningPlayOptionSerializer(
        many=True, help_text="single, multi and order (steps shuffled, ids by place)."
    )
    left = LearningPlayOptionSerializer(many=True, help_text="match: the left side as written.")
    right = LearningPlayOptionSerializer(many=True, help_text="match: the right side shuffled.")
    unit = serializers.CharField(allow_null=True, help_text="number: the unit, if any.")


class LearningQuizBestSerializer(serializers.Serializer):
    percent = serializers.IntegerField()
    passed = serializers.BooleanField()


class LearningQuizIntroSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    emoji = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    questions = serializers.IntegerField(help_text="How many questions an attempt has.")
    time_limit_seconds = serializers.IntegerField(allow_null=True)
    pass_percent = serializers.IntegerField()
    max_attempts = serializers.IntegerField(allow_null=True, help_text="Null: any number.")
    attempts_used = serializers.IntegerField()
    retry_at = serializers.DateTimeField(allow_null=True)
    best = LearningQuizBestSerializer(allow_null=True)
    in_progress = serializers.IntegerField(
        allow_null=True, help_text="The attempt in progress, resumed by starting."
    )
    can_start = serializers.BooleanField()
    reason = serializers.CharField(allow_null=True, help_text="Why not, in the person's words.")


class LearningAttemptQuizSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    emoji = serializers.CharField(allow_blank=True)
    pass_percent = serializers.IntegerField()


class LearningAttemptPlaySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    quiz = LearningAttemptQuizSerializer()
    number = serializers.IntegerField()
    started_at = serializers.DateTimeField()
    deadline_at = serializers.DateTimeField(allow_null=True)
    questions = LearningQuestionPlaySerializer(many=True)
    answers = serializers.DictField(
        child=serializers.JSONField(), help_text="Question id -> the answer saved so far."
    )


class LearningReviewItemSerializer(serializers.Serializer):
    question = LearningQuestionPlaySerializer()
    answer = serializers.JSONField(allow_null=True, help_text=ANSWER_HELP)
    correct = serializers.BooleanField()
    share = serializers.FloatField(help_text="Share of the question's points earned, 0 to 1.")
    right_answer = serializers.JSONField(
        allow_null=True, help_text="Null when the quiz doesn't show the answers (yet)."
    )
    explanation = serializers.CharField(allow_null=True)


class LearningAttemptResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    state = serializers.ChoiceField(Attempt.State.choices)
    score = serializers.FloatField()
    max_score = serializers.FloatField()
    percent = serializers.IntegerField()
    passed = serializers.BooleanField()
    points = serializers.IntegerField(allow_null=True, help_text="Null while recognition is off.")
    retry_at = serializers.DateTimeField(allow_null=True)
    course_step_done = serializers.BooleanField()
    review = LearningReviewItemSerializer(
        many=True, allow_null=True, help_text="Null when the quiz never shows a review."
    )


class LearningStartAttemptSerializer(serializers.Serializer):
    assignment = serializers.IntegerField(required=False, allow_null=True)
    entry = serializers.IntegerField(required=False, allow_null=True)


class LearningSaveAnswerSerializer(serializers.Serializer):
    question = serializers.IntegerField()
    answer = serializers.JSONField(allow_null=True, help_text=ANSWER_HELP + " Null clears it.")


class LearningDailyCardSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    day = serializers.DateField()
    question = LearningQuestionPlaySerializer()
    answered = serializers.BooleanField()
    correct = serializers.BooleanField(allow_null=True)
    answer = serializers.JSONField(allow_null=True)
    right_answer = serializers.JSONField(allow_null=True)
    explanation = serializers.CharField(allow_null=True, allow_blank=True)


class LearningDailySerializer(serializers.Serializer):
    daily = LearningDailyCardSerializer(allow_null=True)
    streak = serializers.IntegerField(allow_null=True)


class LearningDailyAnswerSerializer(serializers.Serializer):
    answer = serializers.JSONField(help_text=ANSWER_HELP)


class LearningDailyOutcomeSerializer(serializers.Serializer):
    correct = serializers.BooleanField()
    share = serializers.FloatField()
    right_answer = serializers.JSONField()
    explanation = serializers.CharField(allow_blank=True)
    points = serializers.IntegerField(allow_null=True)
    streak = serializers.IntegerField(allow_null=True)


class LearningCheckCardSerializer(serializers.Serializer):
    entry_id = serializers.IntegerField()
    title = serializers.CharField()
    quiz_id = serializers.IntegerField()
    due_at = serializers.DateTimeField()
    done = serializers.BooleanField()
    passed = serializers.BooleanField(allow_null=True)


# The owner dashboard --------------------------------------------------------------------------


class LearningPersonSerializer(serializers.Serializer):
    """A person as owner endpoints name them (the dashboard's PersonRef), with their position."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)
    position = serializers.CharField(allow_null=True)


class LearningTopicRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    color = serializers.CharField(allow_blank=True)


class LearningRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()


class LearningImageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    url = serializers.CharField()
    width = serializers.IntegerField()
    height = serializers.IntegerField()


class LearningImageUploadSerializer(serializers.Serializer):
    file = serializers.FileField()


class LearningQuestionSerializer(serializers.Serializer):
    """A question of the bank, with its answers (managers of learning only)."""

    id = serializers.IntegerField()
    kind = serializers.ChoiceField(Question.Kind.choices)
    text = serializers.CharField()
    data = serializers.JSONField(help_text="The kind's data with the right answer (§4.3).")
    explanation = serializers.CharField(allow_blank=True)
    image = LearningImageSerializer(allow_null=True)
    topic = LearningTopicRefSerializer(allow_null=True)
    difficulty = serializers.ChoiceField(Question.Difficulty.choices)
    points = serializers.IntegerField()
    state = serializers.ChoiceField(Question.State.choices)
    source = serializers.ChoiceField(Question.Source.choices)
    lesson = LearningRefSerializer(allow_null=True)
    page = LearningRefSerializer(allow_null=True)
    draft_job_id = serializers.IntegerField(allow_null=True)
    answered = serializers.IntegerField()
    correct = serializers.IntegerField()
    correct_percent = serializers.IntegerField(allow_null=True)
    quizzes = serializers.IntegerField(help_text="Quizzes whose list holds it.")
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class LearningQuestionWriteSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(Question.Kind.choices, required=False)
    text = serializers.CharField(required=False, allow_blank=True)
    data = serializers.JSONField(required=False)
    explanation = serializers.CharField(required=False, allow_blank=True)
    topic_id = serializers.IntegerField(required=False, allow_null=True)
    difficulty = serializers.ChoiceField(Question.Difficulty.choices, required=False)
    points = serializers.IntegerField(required=False)
    image_id = serializers.IntegerField(required=False, allow_null=True)
    lesson_id = serializers.IntegerField(required=False, allow_null=True)
    page_id = serializers.IntegerField(required=False, allow_null=True)
    state = serializers.ChoiceField(Question.State.choices, required=False)


class LearningQuestionBulkSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), max_length=500)
    state = serializers.ChoiceField(Question.State.choices)


class LearningChangedSerializer(serializers.Serializer):
    changed = serializers.IntegerField()


class LearningQuizRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    emoji = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    mode = serializers.CharField()
    question_count = serializers.IntegerField()
    questions = serializers.IntegerField(help_text="How many questions an attempt has now.")
    topics = LearningTopicRefSerializer(many=True)
    pass_percent = serializers.IntegerField()
    time_limit_seconds = serializers.IntegerField(allow_null=True)
    max_attempts = serializers.IntegerField(allow_null=True)
    attempts = serializers.IntegerField(help_text="Finished attempts that count.")
    people = serializers.IntegerField()
    pass_rate = serializers.IntegerField(allow_null=True, help_text="People who passed, %.")
    average = serializers.IntegerField(allow_null=True, help_text="Average score, %.")
    updated_at = serializers.DateTimeField()


class LearningQuizSerializer(LearningQuizRowSerializer):
    shuffle_questions = serializers.BooleanField()
    shuffle_options = serializers.BooleanField()
    retry_after_minutes = serializers.IntegerField()
    partial_credit = serializers.BooleanField()
    show_answers = serializers.CharField()
    audience_all = serializers.BooleanField()
    position_ids = serializers.ListField(child=serializers.IntegerField())
    topic_ids = serializers.ListField(child=serializers.IntegerField())
    question_ids = serializers.ListField(child=serializers.IntegerField())
    in_courses = serializers.IntegerField()
    in_checks = serializers.IntegerField()


class LearningQuizWriteSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True)
    emoji = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    mode = serializers.CharField(required=False)
    question_count = serializers.IntegerField(required=False)
    shuffle_questions = serializers.BooleanField(required=False)
    shuffle_options = serializers.BooleanField(required=False)
    time_limit_seconds = serializers.IntegerField(required=False, allow_null=True)
    pass_percent = serializers.IntegerField(required=False)
    max_attempts = serializers.IntegerField(required=False, allow_null=True)
    retry_after_minutes = serializers.IntegerField(required=False)
    partial_credit = serializers.BooleanField(required=False)
    show_answers = serializers.CharField(required=False)
    audience_all = serializers.BooleanField(required=False)
    position_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    topic_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    question_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class LearningPreviewItemSerializer(serializers.Serializer):
    question = LearningQuestionPlaySerializer()
    right_answer = serializers.JSONField()
    explanation = serializers.CharField(allow_blank=True)


class LearningPreviewSerializer(serializers.Serializer):
    questions = LearningPreviewItemSerializer(many=True)


class LearningResultsSummarySerializer(serializers.Serializer):
    attempts = serializers.IntegerField()
    people = serializers.IntegerField()
    passed_people = serializers.IntegerField()
    pass_rate = serializers.IntegerField(allow_null=True)
    average = serializers.IntegerField(allow_null=True)


class LearningResultAttemptSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    member = LearningPersonSerializer()
    number = serializers.IntegerField()
    state = serializers.ChoiceField(Attempt.State.choices)
    started_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)
    percent = serializers.IntegerField(allow_null=True)
    passed = serializers.BooleanField(allow_null=True)
    score = serializers.FloatField(allow_null=True)
    max_score = serializers.FloatField(allow_null=True)
    reset = serializers.BooleanField()
    check = serializers.BooleanField(help_text="Answered a regular check.")


class LearningDistributionSerializer(serializers.Serializer):
    start = serializers.IntegerField()
    end = serializers.IntegerField()
    count = serializers.IntegerField()


class LearningHardQuestionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    text = serializers.CharField()
    kind = serializers.ChoiceField(Question.Kind.choices)
    answered = serializers.IntegerField()
    correct = serializers.IntegerField()
    percent = serializers.IntegerField()


class LearningResultsSerializer(serializers.Serializer):
    summary = LearningResultsSummarySerializer()
    attempts = LearningResultAttemptSerializer(many=True)
    distribution = LearningDistributionSerializer(many=True)
    hardest = LearningHardQuestionSerializer(many=True)


class LearningResetSerializer(serializers.Serializer):
    member = serializers.IntegerField()


class LearningOwnerAttemptSerializer(LearningAttemptResultSerializer):
    member = LearningPersonSerializer()
    quiz = LearningRefSerializer()
    number = serializers.IntegerField()
    started_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)
    trial = serializers.BooleanField()


class LearningRoundSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    starts_at = serializers.DateTimeField()
    due_at = serializers.DateTimeField()
    closed_at = serializers.DateTimeField(allow_null=True)
    people = serializers.IntegerField()
    done = serializers.IntegerField()
    passed = serializers.IntegerField()


class LearningCheckSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    quiz = LearningRefSerializer()
    state = serializers.CharField()
    every = serializers.CharField()
    weekday = serializers.IntegerField(allow_null=True)
    month_day = serializers.IntegerField(allow_null=True)
    at = serializers.TimeField(format="%H:%M")
    answer_within_hours = serializers.IntegerField()
    audience_all = serializers.BooleanField()
    position_ids = serializers.ListField(child=serializers.IntegerField())
    branch_ids = serializers.ListField(child=serializers.IntegerField())
    next_run_at = serializers.DateTimeField(allow_null=True)
    last_round = LearningRoundSerializer(allow_null=True)


class LearningCheckWriteSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True)
    quiz_id = serializers.IntegerField(required=False)
    every = serializers.CharField(required=False)
    weekday = serializers.IntegerField(required=False, allow_null=True)
    month_day = serializers.IntegerField(required=False, allow_null=True)
    at = serializers.CharField(required=False, help_text="HH:MM, the company's time.")
    answer_within_hours = serializers.IntegerField(required=False)
    audience_all = serializers.BooleanField(required=False)
    position_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    branch_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class LearningRoundEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    member = LearningPersonSerializer()
    done = serializers.BooleanField()
    passed = serializers.BooleanField(allow_null=True)
    percent = serializers.IntegerField(allow_null=True)
    attempt_id = serializers.IntegerField(allow_null=True)
    reminded_at = serializers.DateTimeField(allow_null=True)


class LearningWeakestSerializer(serializers.Serializer):
    question = serializers.IntegerField()
    text = serializers.CharField()
    percent = serializers.IntegerField()


class LearningRoundDetailSerializer(LearningRoundSerializer):
    entries = LearningRoundEntrySerializer(many=True)
    weakest = LearningWeakestSerializer(allow_null=True)


class LearningSkillCellSerializer(serializers.Serializer):
    score = serializers.IntegerField(allow_null=True)
    answers = serializers.IntegerField()
    band = serializers.ChoiceField(["weak", "ok", "strong", "unrated"])
    last_at = serializers.DateTimeField(allow_null=True)


class LearningSkillTopicSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    color = serializers.CharField(allow_blank=True)
    average = serializers.IntegerField(allow_null=True)
    rated = serializers.IntegerField()
    weak = serializers.IntegerField()
    strong = serializers.IntegerField()


class LearningSkillRowSerializer(serializers.Serializer):
    member = LearningPersonSerializer()
    average = serializers.IntegerField(allow_null=True)
    answers = serializers.IntegerField()
    cells = serializers.DictField(
        child=LearningSkillCellSerializer(), help_text="Topic id -> the person's cell."
    )


class LearningSkillMatrixSerializer(serializers.Serializer):
    topics = LearningSkillTopicSerializer(many=True)
    people = LearningSkillRowSerializer(many=True)


class LearningPersonTopicSerializer(LearningSkillCellSerializer):
    topic = LearningTopicRefSerializer()


class LearningPersonAttemptSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    quiz = LearningRefSerializer()
    state = serializers.ChoiceField(Attempt.State.choices)
    percent = serializers.IntegerField(allow_null=True)
    passed = serializers.BooleanField(allow_null=True)
    finished_at = serializers.DateTimeField(allow_null=True)
    check = serializers.BooleanField()


class LearningPersonDailySerializer(serializers.Serializer):
    asked = serializers.IntegerField()
    answered = serializers.IntegerField()
    right = serializers.IntegerField()


class LearningPersonSkillsSerializer(serializers.Serializer):
    member = LearningPersonSerializer()
    topics = LearningPersonTopicSerializer(many=True)
    attempts = LearningPersonAttemptSerializer(many=True)
    daily = LearningPersonDailySerializer(help_text="The last 30 days.")


class LearningSuggestionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.CharField()
    state = serializers.CharField()
    member = LearningPersonSerializer(allow_null=True)
    topic = LearningTopicRefSerializer(allow_null=True)
    course = LearningRefSerializer(allow_null=True)
    score = serializers.IntegerField(allow_null=True)
    params = serializers.JSONField()
    text = serializers.CharField(help_text="Worded now, in the reader's language.")
    created_at = serializers.DateTimeField()
    decided_at = serializers.DateTimeField(allow_null=True)


class LearningDraftJobSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    state = serializers.CharField()
    engine = serializers.CharField()
    page = LearningRefSerializer(allow_null=True)
    lesson = LearningRefSerializer(allow_null=True)
    topic = LearningTopicRefSerializer(allow_null=True)
    count = serializers.IntegerField()
    kinds = serializers.ListField(child=serializers.CharField())
    difficulty = serializers.CharField(allow_blank=True)
    made = serializers.IntegerField()
    dropped = serializers.IntegerField()
    error = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)


class LearningDraftJobDetailSerializer(LearningDraftJobSerializer):
    questions = LearningQuestionSerializer(many=True)


class LearningDraftCreateSerializer(serializers.Serializer):
    page_id = serializers.IntegerField(required=False, allow_null=True)
    lesson_id = serializers.IntegerField(required=False, allow_null=True)
    count = serializers.IntegerField(min_value=1, max_value=15, default=5)
    kinds = serializers.ListField(
        child=serializers.ChoiceField(Question.Kind.choices), required=False, default=list
    )
    difficulty = serializers.ChoiceField(
        Question.Difficulty.choices, required=False, allow_blank=True, default=""
    )
    topic_id = serializers.IntegerField(required=False, allow_null=True)
    engine = serializers.ChoiceField(
        ["auto", "rules"], default="auto", help_text="auto: Claude when it may run, else rules."
    )


class LearningDailyTodaySerializer(serializers.Serializer):
    day = serializers.DateField()
    asked = serializers.IntegerField()
    answered = serializers.IntegerField()
    right = serializers.IntegerField()


class LearningDailySettingsSerializer(serializers.Serializer):
    daily_question = serializers.BooleanField()
    daily_at = serializers.TimeField(format="%H:%M")
    daily_position_ids = serializers.ListField(child=serializers.IntegerField())
    today = LearningDailyTodaySerializer()


class LearningDailySettingsWriteSerializer(serializers.Serializer):
    daily_question = serializers.BooleanField(required=False)
    daily_at = serializers.CharField(required=False, help_text="HH:MM, the company's time.")
    daily_position_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class LearningTutorConfigSerializer(serializers.Serializer):
    weekly_report = serializers.BooleanField()
    report_day = serializers.CharField(help_text="0 is Monday.")
    at = serializers.CharField()
    nudge_learners = serializers.BooleanField()
    suggest = serializers.BooleanField()
    weak_threshold = serializers.IntegerField()


class LearningTutorAgentSerializer(serializers.Serializer):
    listed = serializers.BooleanField(help_text="The company has the AI module (agents run there).")
    enabled = serializers.BooleanField()
    ai_on = serializers.BooleanField()
    claude = serializers.CharField(help_text="connected, fake, not_configured, budget_reached…")
    chat = serializers.BooleanField(help_text="The viewer may ask the tutor.")
    next_report_at = serializers.DateTimeField(allow_null=True)
    config = LearningTutorConfigSerializer()


class LearningTutorReportSerializer(serializers.Serializer):
    sent_at = serializers.DateTimeField(allow_null=True, help_text="Null: worked out now.")
    week = serializers.CharField(allow_blank=True)
    opening = serializers.CharField(allow_blank=True)
    lines = serializers.ListField(child=serializers.CharField())
    facts = serializers.JSONField()


class LearningTutorEventSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    text = serializers.CharField()
    level = serializers.CharField()


class LearningTutorSerializer(serializers.Serializer):
    agent = LearningTutorAgentSerializer()
    report = LearningTutorReportSerializer(allow_null=True)
    suggestions = serializers.DictField(
        child=serializers.IntegerField(), help_text="Open suggestions by kind, and 'total'."
    )
    weakest = LearningSkillTopicSerializer(many=True)
    events = LearningTutorEventSerializer(many=True)


class LearningTutorConversationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    last_activity_at = serializers.DateTimeField()
