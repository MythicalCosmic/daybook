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
