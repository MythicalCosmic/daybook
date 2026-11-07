"""Owner endpoints of topics (`knowledge/topics/`), routed in `owner_urls.py`.

Everyone with dashboard access reads them (the pickers of pages, lessons and questions); holders
of `knowledge.manage` or `learning.manage` change them (docs/PLAN-LEARNING.md §3.1).
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.console.base import OwnerViewSet
from apps.console.perms import AnyOf
from apps.knowledge import topics
from apps.knowledge.models import Topic
from apps.members.permissions import Perm

MANAGE = AnyOf(Perm.KNOWLEDGE_MANAGE, Perm.LEARNING_MANAGE)


class KnowledgeTopicSerializer(serializers.ModelSerializer):
    page_count = serializers.IntegerField(read_only=True, default=0)
    lesson_count = serializers.IntegerField(read_only=True, default=0)
    question_count = serializers.IntegerField(read_only=True, default=0)
    archived = serializers.SerializerMethodField()

    class Meta:
        model = Topic
        fields = [
            "id",
            "name",
            "color",
            "description",
            "position",
            "archived",
            "page_count",
            "lesson_count",
            "question_count",
        ]
        read_only_fields = fields

    def get_archived(self, topic) -> bool:
        return topic.archived_at is not None


class KnowledgeTopicWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    color = serializers.CharField(max_length=16, required=False, allow_blank=True)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)


class KnowledgeTopicOrderSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), max_length=500)


class TopicViewSet(mixins.ListModelMixin, OwnerViewSet):
    """The company's topics, in order (`?archived=true` adds the archived ones)."""

    serializer_class = KnowledgeTopicSerializer
    pagination_class = None
    lookup_value_regex = r"\d+"
    perm = None
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "archive": MANAGE,
        "restore": MANAGE,
        "reorder": MANAGE,
        "pharmacy": MANAGE,
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Topic.objects.none()
        archived = self.request.query_params.get("archived") == "true"
        return topics.topics(self.company, include_archived=archived or self.action != "list")

    @extend_schema(parameters=[OpenApiParameter("archived", bool)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def _one(self, topic: Topic) -> dict:
        return KnowledgeTopicSerializer(self.get_queryset().get(pk=topic.pk)).data

    @extend_schema(request=KnowledgeTopicWriteSerializer, responses={201: KnowledgeTopicSerializer})
    def create(self, request, company_id):
        data = KnowledgeTopicWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        topic = topics.create_topic(self.company, by=self.membership, **data.validated_data)
        return Response(self._one(topic), status=status.HTTP_201_CREATED)

    @extend_schema(request=KnowledgeTopicWriteSerializer, responses=KnowledgeTopicSerializer)
    def partial_update(self, request, company_id, pk):
        data = KnowledgeTopicWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        topic = topics.update_topic(self.get_object(), by=self.membership, **data.validated_data)
        return Response(self._one(topic))

    @extend_schema(request=None, responses=KnowledgeTopicSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, company_id, pk):
        return Response(self._one(topics.archive_topic(self.get_object(), by=self.membership)))

    @extend_schema(request=None, responses=KnowledgeTopicSerializer)
    @action(detail=True, methods=["post"])
    def restore(self, request, company_id, pk):
        return Response(self._one(topics.restore_topic(self.get_object(), by=self.membership)))

    @extend_schema(request=KnowledgeTopicOrderSerializer, responses={204: None})
    @action(detail=False, methods=["post"])
    def reorder(self, request, company_id):
        data = KnowledgeTopicOrderSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        topics.reorder_topics(self.company, data.validated_data["ids"], by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses={201: KnowledgeTopicSerializer(many=True)})
    @action(detail=False, methods=["post"])
    def pharmacy(self, request, company_id):
        """Add the usual pharmacy topics the company doesn't have yet."""
        made = topics.add_pharmacy_topics(self.company, by=self.membership)
        rows = self.get_queryset().filter(pk__in=[topic.pk for topic in made])
        return Response(
            KnowledgeTopicSerializer(rows, many=True).data, status=status.HTTP_201_CREATED
        )
