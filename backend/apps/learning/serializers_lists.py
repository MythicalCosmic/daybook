"""Serializers of the unchangeable lists' owner endpoints (`owner_api_lists.py`): what the requests
may carry, and the answers' shapes for the schema. `study_lists.rows` and `study_lists.detail` build
the answers themselves."""

from rest_framework import serializers

from apps.learning.models import StudyList, StudyMark

# Answers ------------------------------------------------------------------------------------


class LearningStudyBranchSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class LearningStudyListRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    teacher = serializers.CharField()
    branch = LearningStudyBranchSerializer(allow_null=True)
    state = serializers.ChoiceField(StudyList.State.choices)
    topics = serializers.IntegerField()
    students = serializers.IntegerField()
    studied = serializers.IntegerField(help_text="Cells holding a standing 'studied' line.")
    cells = serializers.IntegerField(help_text="Topics × students.")
    created_at = serializers.DateTimeField()
    sealed_at = serializers.DateTimeField(allow_null=True)


class LearningStudyTopicSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.IntegerField()
    title = serializers.CharField()
    locked = serializers.BooleanField(help_text="A line mentions it: it can't change any more.")


class LearningStudyStudentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.IntegerField()
    name = serializers.CharField()
    note = serializers.CharField()
    member_id = serializers.IntegerField(allow_null=True)
    position = serializers.CharField(allow_null=True)
    locked = serializers.BooleanField()


class LearningStudyMarkSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.IntegerField()
    kind = serializers.ChoiceField(StudyMark.Kind.choices)
    topic_id = serializers.IntegerField()
    student_id = serializers.IntegerField()
    studied_on = serializers.DateField(allow_null=True)
    note = serializers.CharField()
    corrects_id = serializers.IntegerField(allow_null=True)
    corrected_by_id = serializers.IntegerField(allow_null=True)
    written_by = serializers.CharField()
    written_at = serializers.DateTimeField()
    digest = serializers.CharField()


class LearningStudyListSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    description = serializers.CharField()
    teacher = serializers.CharField()
    branch = LearningStudyBranchSerializer(allow_null=True)
    state = serializers.ChoiceField(StudyList.State.choices)
    created_at = serializers.DateTimeField()
    created_by = serializers.CharField()
    sealed_at = serializers.DateTimeField(allow_null=True)
    sealed_by = serializers.CharField()
    seal_digest = serializers.CharField()
    intact = serializers.BooleanField(help_text="The chain of lines (and the seal) checks out.")
    topics = LearningStudyTopicSerializer(many=True)
    students = LearningStudyStudentSerializer(many=True)
    marks = LearningStudyMarkSerializer(many=True)


class LearningStudyCandidateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    position = serializers.CharField(allow_null=True)
    branch = serializers.CharField(allow_null=True)


# Requests -----------------------------------------------------------------------------------


class LearningStudyListWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    teacher = serializers.CharField(required=False, allow_blank=True, max_length=200)
    branch_id = serializers.IntegerField(required=False, allow_null=True)


class LearningStudyTopicsSerializer(serializers.Serializer):
    titles = serializers.ListField(
        child=serializers.CharField(max_length=300), min_length=1, max_length=100
    )


class LearningStudyTopicWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=300)


class LearningStudyNameSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    note = serializers.CharField(required=False, allow_blank=True, max_length=200)


class LearningStudyStudentsSerializer(serializers.Serializer):
    member_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, max_length=200
    )
    names = serializers.ListField(
        child=LearningStudyNameSerializer(), required=False, max_length=200
    )


class LearningStudyStudentWriteSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, max_length=200)
    note = serializers.CharField(required=False, allow_blank=True, max_length=200)


class LearningStudyMarkWriteSerializer(serializers.Serializer):
    topic_id = serializers.IntegerField()
    student_id = serializers.IntegerField()
    studied_on = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)


class LearningStudyCorrectSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3, max_length=300)
