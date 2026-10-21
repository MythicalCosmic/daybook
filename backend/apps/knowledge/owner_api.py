"""Owner dashboard endpoints of the knowledge base; routed in `owner_urls.py`.

Reading needs only dashboard access (each person sees the spaces and pages they read; people
with `knowledge.manage` see everything, drafts included). Every change needs `knowledge.manage`.
"""

from datetime import timedelta

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.console.base import OwnerAPIView, OwnerViewSet
from apps.core.files import signed_url
from apps.knowledge import queries, services, targets
from apps.knowledge.conf import get_settings
from apps.knowledge.models import Page, PageLink, PageVersion, Space
from apps.knowledge.serializers import (
    IMAGE_TTL,
    KnowledgeImageSerializer,
    KnowledgeImageUploadSerializer,
    KnowledgeLinkCreateSerializer,
    KnowledgeLinkSerializer,
    KnowledgeMoveSerializer,
    KnowledgePageCreateSerializer,
    KnowledgePageDetailSerializer,
    KnowledgePageRowSerializer,
    KnowledgePageSaveSerializer,
    KnowledgePublishSerializer,
    KnowledgeReaderSerializer,
    KnowledgeRefSerializer,
    KnowledgeReorderSerializer,
    KnowledgeSettingsSerializer,
    KnowledgeSpaceSerializer,
    KnowledgeSpaceUpdateSerializer,
    KnowledgeSpaceWriteSerializer,
    KnowledgeTargetSerializer,
    KnowledgeTreeNodeSerializer,
    KnowledgeVersionDetailSerializer,
    KnowledgeVersionSerializer,
    tree_json,
)
from apps.members.models import Position
from apps.members.permissions import Perm

MANAGE = Perm.KNOWLEDGE_MANAGE
PULSE = services.PULSE_KEY


def _int(value, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        raise ValidationError({name: [_("Must be a whole number.")]}) from None


class SpaceViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    OwnerViewSet,
):
    """Knowledge base spaces the caller reads (all of them with `knowledge.manage`;
    `?archived=true` adds archived ones for managers)."""

    serializer_class = KnowledgeSpaceSerializer
    pagination_class = None
    lookup_value_regex = r"\d+"
    perm = None
    perms_by_action = {
        "create": MANAGE,
        "update": MANAGE,
        "partial_update": MANAGE,
        "archive": MANAGE,
        "restore": MANAGE,
        "reorder": MANAGE,
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Space.objects.none()
        archived = self.request.query_params.get("archived") == "true"
        return queries.visible_spaces(
            self.membership, include_archived=archived or self.action != "list"
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False):
            return context
        if queries.can_manage(self.membership):
            context["counts"] = queries.space_counts(self.company.pk)
        else:
            ids = list(queries.visible_spaces(self.membership).values_list("pk", flat=True))
            readable = queries.readable_counts(self.membership, ids)
            context["counts"] = {
                pk: {"pages": n, "published": n, "drafts": 0} for pk, n in readable.items()
            }
        return context

    @extend_schema(parameters=[OpenApiParameter("archived", bool)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=KnowledgeSpaceWriteSerializer, responses={201: KnowledgeSpaceSerializer})
    def create(self, request, company_id):
        data = KnowledgeSpaceWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        space = services.create_space(self.company, by=self.membership, **data.validated_data)
        self.bump(PULSE)
        return Response(
            KnowledgeSpaceSerializer(space, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=KnowledgeSpaceUpdateSerializer, responses=KnowledgeSpaceSerializer)
    def partial_update(self, request, company_id, pk):
        data = KnowledgeSpaceUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        space = services.update_space(self.get_object(), by=self.membership, **data.validated_data)
        return Response(KnowledgeSpaceSerializer(space, context=self.get_serializer_context()).data)

    @extend_schema(request=KnowledgeSpaceUpdateSerializer, responses=KnowledgeSpaceSerializer)
    def update(self, request, company_id, pk):
        return self.partial_update(request, company_id, pk)

    @extend_schema(request=None, responses=KnowledgeSpaceSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, company_id, pk):
        space = services.archive_space(self.get_object(), by=self.membership)
        return Response(KnowledgeSpaceSerializer(space, context=self.get_serializer_context()).data)

    @extend_schema(request=None, responses=KnowledgeSpaceSerializer)
    @action(detail=True, methods=["post"])
    def restore(self, request, company_id, pk):
        space = services.restore_space(self.get_object(), by=self.membership)
        return Response(KnowledgeSpaceSerializer(space, context=self.get_serializer_context()).data)

    @extend_schema(request=KnowledgeReorderSerializer, responses={204: None})
    @action(detail=False, methods=["post"])
    def reorder(self, request, company_id):
        data = KnowledgeReorderSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.reorder_spaces(self.company, data.validated_data["ids"], by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses=KnowledgeTreeNodeSerializer(many=True))
    @action(detail=True)
    def tree(self, request, company_id, pk):
        """The space's pages as a tree (drafts too for managers)."""
        space = self.get_object()
        if space.archived_at is not None and not queries.can_manage(self.membership):
            raise NotFound
        return Response(tree_json(queries.tree(self.membership, space)))


class PageViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, OwnerViewSet):
    """Pages. The list filters by `q`, `space`, `status` (published|draft|archived) and
    `require_ack`; the detail carries the body with signed picture links."""

    serializer_class = KnowledgePageRowSerializer
    lookup_value_regex = r"\d+"
    perm = None
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "publish": MANAGE,
        "unpublish": MANAGE,
        "move": MANAGE,
        "archive": MANAGE,
        "restore": MANAGE,
        "versions": MANAGE,
        "version": MANAGE,
        "restore_version": MANAGE,
        "readers": MANAGE,
        "remind": MANAGE,
        "links": None,  # GET for readers; POST checked below
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Page.objects.none()
        member = self.membership
        params = self.request.query_params
        if queries.can_manage(member):
            pages = Page.objects.for_company(self.company.pk).filter(
                space__in=queries.visible_spaces(member, include_archived=True)
            )
            state = params.get("status")
            if state == "archived":
                pages = pages.filter(archived_at__isnull=False)
            elif self.action == "list":
                pages = pages.filter(archived_at__isnull=True)
                if state == "published":
                    pages = pages.filter(published=True)
                elif state == "draft":
                    pages = pages.filter(published=False)
        else:
            pages = queries.readable_pages(member)
        if space := _int(params.get("space"), "space"):
            pages = pages.filter(space_id=space)
        if params.get("require_ack") in ("true", "1"):
            pages = pages.filter(require_ack=True)
        if q := (params.get("q") or "").strip():
            pages = pages.filter(Q(title__icontains=q) | Q(body_text__icontains=q))
        ordering = params.get("ordering") or "-updated_at"
        if ordering.lstrip("-") not in ("updated_at", "title", "published_at", "created_at"):
            ordering = "-updated_at"
        return pages.select_related("space", "updated_by__user").order_by(ordering, "-pk")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["read_counts"] = getattr(self, "_read_counts", None)
        return context

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str),
            OpenApiParameter("space", int),
            OpenApiParameter("status", str, enum=["published", "draft", "archived"]),
            OpenApiParameter("require_ack", bool),
            OpenApiParameter("ordering", str),
        ]
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = list(page if page is not None else queryset)
        if queries.can_manage(self.membership):
            self._read_counts = queries.read_counts([row for row in rows if row.published])
        data = self.get_serializer(rows, many=True).data
        return self.get_paginated_response(data) if page is not None else Response(data)

    def _page(self, pk) -> Page:
        page = queries.get_page(self.membership, int(pk))
        if page is None:
            raise NotFound
        return page

    def _detail(self, page: Page) -> Response:
        context = self.get_serializer_context()
        if queries.can_manage(self.membership) and page.published:
            context["read_counts"] = queries.read_counts([page])
        page = Page.objects.select_related("space", "updated_by__user", "created_by__user").get(
            pk=page.pk
        )
        return Response(KnowledgePageDetailSerializer(page, context=context).data)

    @extend_schema(responses=KnowledgePageDetailSerializer)
    def retrieve(self, request, company_id, pk):
        return self._detail(self._page(pk))

    @extend_schema(
        request=KnowledgePageCreateSerializer, responses={201: KnowledgePageDetailSerializer}
    )
    def create(self, request, company_id):
        data = KnowledgePageCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        space = get_object_or_404(Space.objects.for_company(self.company.pk), pk=values["space"])
        parent = None
        if values["parent"]:
            parent = get_object_or_404(
                Page.objects.for_company(self.company.pk), pk=values["parent"]
            )
        page = services.create_page(
            space,
            by=self.membership,
            title=values["title"],
            emoji=values["emoji"],
            body=values["body"],
            parent=parent,
            require_ack=values["require_ack"],
            publish=values["publish"],
            notify_readers=values["notify"],
        )
        response = self._detail(page)
        response.status_code = status.HTTP_201_CREATED
        return response

    @extend_schema(request=KnowledgePageSaveSerializer, responses=KnowledgePageDetailSerializer)
    def partial_update(self, request, company_id, pk):
        data = KnowledgePageSaveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        notify = values.pop("notify")
        page = services.save_page(
            self._page(pk), by=self.membership, notify_readers=notify, **values
        )
        return self._detail(page)

    @extend_schema(request=KnowledgePublishSerializer, responses=KnowledgePageDetailSerializer)
    @action(detail=True, methods=["post"])
    def publish(self, request, company_id, pk):
        data = KnowledgePublishSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        page = services.publish_page(
            self._page(pk), by=self.membership, notify_readers=data.validated_data["notify"]
        )
        return self._detail(page)

    @extend_schema(request=None, responses=KnowledgePageDetailSerializer)
    @action(detail=True, methods=["post"])
    def unpublish(self, request, company_id, pk):
        return self._detail(services.unpublish_page(self._page(pk), by=self.membership))

    @extend_schema(request=KnowledgeMoveSerializer, responses=KnowledgePageDetailSerializer)
    @action(detail=True, methods=["post"])
    def move(self, request, company_id, pk):
        data = KnowledgeMoveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        space = None
        if values["space"]:
            space = get_object_or_404(
                Space.objects.for_company(self.company.pk), pk=values["space"]
            )
        parent = None
        if values["parent"]:
            parent = get_object_or_404(
                Page.objects.for_company(self.company.pk).filter(archived_at__isnull=True),
                pk=values["parent"],
            )
        page = services.move_page(
            self._page(pk), by=self.membership, parent=parent, index=values["index"], space=space
        )
        return self._detail(page)

    @extend_schema(request=None, responses=KnowledgePageDetailSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, company_id, pk):
        return self._detail(services.archive_page(self._page(pk), by=self.membership))

    @extend_schema(request=None, responses=KnowledgePageDetailSerializer)
    @action(detail=True, methods=["post"])
    def restore(self, request, company_id, pk):
        return self._detail(services.restore_page(self._page(pk), by=self.membership))

    @extend_schema(
        request=None,
        responses=inline_serializer(
            "KnowledgeAckResult",
            {"version": serializers.IntegerField(), "at": serializers.DateTimeField()},
        ),
    )
    @action(detail=True, methods=["post"])
    def ack(self, request, company_id, pk):
        """The caller confirms reading the current version."""
        ack = services.acknowledge(self._page(pk), by=self.membership)
        return Response({"version": ack.version, "at": ack.at})

    @extend_schema(responses=KnowledgeVersionSerializer(many=True))
    @action(detail=True)
    def versions(self, request, company_id, pk):
        page = self._page(pk)
        versions = PageVersion.objects.filter(page=page).select_related("created_by__user")
        return Response(
            KnowledgeVersionSerializer(
                versions, many=True, context={"current_version": page.version}
            ).data
        )

    @extend_schema(responses=KnowledgeVersionDetailSerializer)
    @action(detail=True, url_path=r"versions/(?P<version>\d+)")
    def version(self, request, company_id, pk, version):
        page = self._page(pk)
        row = get_object_or_404(
            PageVersion.objects.select_related("created_by__user"), page=page, version=version
        )
        context = self.get_serializer_context() | {"current_version": page.version}
        return Response(KnowledgeVersionDetailSerializer(row, context=context).data)

    @extend_schema(request=None, responses=KnowledgePageDetailSerializer)
    @action(detail=True, methods=["post"], url_path=r"versions/(?P<version>\d+)/restore")
    def restore_version(self, request, company_id, pk, version):
        page = services.restore_version(self._page(pk), int(version), by=self.membership)
        return self._detail(page)

    @extend_schema(
        parameters=[OpenApiParameter("status", str, enum=["read", "outdated", "unread"])],
        responses=inline_serializer(
            "KnowledgeReaders",
            {
                "counts": serializers.DictField(child=serializers.IntegerField()),
                "results": KnowledgeReaderSerializer(many=True),
            },
        ),
    )
    @action(detail=True)
    def readers(self, request, company_id, pk):
        """Who the page is for (in the caller's branch scope) and what they have read."""
        page = self._page(pk)
        rows = queries.readers(page, viewer=self.membership)
        counts = {"read": 0, "outdated": 0, "unread": 0}
        for row in rows:
            counts[row.status] += 1
        wanted = request.query_params.get("status")
        if wanted in counts:
            rows = [row for row in rows if row.status == wanted]
        return Response(
            {"counts": counts, "results": KnowledgeReaderSerializer(rows, many=True).data}
        )

    @extend_schema(
        request=None,
        responses=inline_serializer("KnowledgeReminded", {"reminded": serializers.IntegerField()}),
    )
    @action(detail=True, methods=["post"])
    def remind(self, request, company_id, pk):
        """Ask everyone who hasn't confirmed the current version to read it."""
        count = services.remind_unread(self._page(pk), by=self.membership)
        return Response({"reminded": count})

    @extend_schema(
        methods=["GET"],
        responses=KnowledgeLinkSerializer(many=True),
    )
    @extend_schema(
        methods=["POST"],
        request=KnowledgeLinkCreateSerializer,
        responses={201: KnowledgeLinkSerializer},
    )
    @action(detail=True, methods=["get", "post"])
    def links(self, request, company_id, pk):
        """Tasks and routines this page is linked to ("How to do this")."""
        page = self._page(pk)
        if request.method == "POST":
            data = KnowledgeLinkCreateSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            link = services.link_page(page, by=self.membership, **data.validated_data)
            return Response(KnowledgeLinkSerializer(link).data, status=status.HTTP_201_CREATED)
        links = targets.visible_links(self.membership, page.links.select_related("page__space"))
        return Response(KnowledgeLinkSerializer(links, many=True).data)

    def check_permissions(self, request):
        super().check_permissions(request)
        if (
            getattr(self, "action", None) == "links"
            and request.method == "POST"
            and not queries.can_manage(self.membership)
        ):
            self.permission_denied(request, message=_("You don't have permission to do this."))

    @extend_schema(
        parameters=[
            OpenApiParameter("target_type", str, enum=PageLink.Target.values, required=True),
            OpenApiParameter("target_id", int, required=True),
        ],
        responses=KnowledgeLinkSerializer(many=True),
    )
    @action(detail=False, url_path="linked")
    def linked(self, request, company_id):
        """Pages linked to one task or routine (the tasks drawer's "How to do this")."""
        target_type = request.query_params.get("target_type")
        target_id = _int(request.query_params.get("target_id"), "target_id")
        if target_type not in PageLink.Target.values or target_id is None:
            raise ValidationError({"target_type": [_("Give a task or routine and its id.")]})
        links = queries.links_for(self.membership, target_type, target_id)
        return Response(KnowledgeLinkSerializer(links, many=True).data)


class LinkDeleteView(OwnerAPIView):
    perm = MANAGE

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, pk):
        link = get_object_or_404(PageLink.objects.for_company(self.company.pk), pk=pk)
        services.unlink(link, by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LinkTargetsView(OwnerAPIView):
    """Routines and tasks to link a page to, by title."""

    perm = MANAGE

    @extend_schema(
        parameters=[OpenApiParameter("q", str)], responses=KnowledgeTargetSerializer(many=True)
    )
    def get(self, request, company_id):
        found = targets.search(self.membership, request.query_params.get("q", ""), limit=10)
        return Response(KnowledgeTargetSerializer(found, many=True).data)


class ImageUploadView(OwnerAPIView):
    """Upload a picture for a page (re-encoded, private); answers its id and a signed link."""

    perm = MANAGE
    parser_classes = (MultiPartParser, FormParser)

    @extend_schema(
        request={"multipart/form-data": KnowledgeImageUploadSerializer},
        responses={201: KnowledgeImageSerializer},
    )
    def post(self, request, company_id):
        data = KnowledgeImageUploadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        page = None
        if data.validated_data["page"]:
            page = get_object_or_404(
                Page.objects.for_company(self.company.pk), pk=data.validated_data["page"]
            )
        image = services.upload_image(
            self.company, data.validated_data["file"], by=self.membership, page=page
        )
        url = signed_url(
            image.file,
            user=request.user,
            company_id=self.company.pk,
            check=f"knowledge.image:{image.pk}",
            ttl=IMAGE_TTL,
        )
        return Response(
            {"id": image.pk, "url": url, "width": image.width, "height": image.height},
            status=status.HTTP_201_CREATED,
        )


class OverviewView(OwnerAPIView):
    """The knowledge base home: counts, pages waiting for readers, recent changes."""

    perm = None

    @extend_schema(
        responses=inline_serializer(
            "KnowledgeOverview",
            {
                "counts": serializers.DictField(child=serializers.IntegerField()),
                "attention": KnowledgePageRowSerializer(many=True),
                "recent": KnowledgePageRowSerializer(many=True),
                "to_read": KnowledgePageRowSerializer(many=True),
            },
        )
    )
    def get(self, request, company_id):
        member = self.membership
        manage = queries.can_manage(member)
        spaces = queries.visible_spaces(member)
        pages = queries.readable_pages(member)
        mine = queries.to_read(member)
        counts = {
            "spaces": spaces.count(),
            "spaces_everyone": spaces.filter(audience_all=True).count(),
            "pages": pages.count(),
            "published": pages.filter(published=True).count(),
            "changed_week": pages.filter(
                published=True, updated_at__gte=timezone.now() - timedelta(days=7)
            ).count(),
            "drafts": pages.filter(published=False).count() if manage else 0,
            "require_ack": pages.filter(published=True, require_ack=True).count(),
            "to_read": len(mine),
            # Managers: must-read pages not everyone confirmed, and the confirmations missing.
            "attention": 0,
            "awaiting": 0,
        }
        recent = queries.recent(member, limit=6)
        attention = []
        context = self.get_serializer_context()
        if manage:
            needing = list(
                pages.filter(published=True, require_ack=True).select_related("space")[:200]
            )
            read = queries.read_counts(needing + [page for page in recent if page.published])
            context["read_counts"] = read
            attention = sorted(
                (page for page in needing if read.get(page.pk, (0, 0))[1]),
                key=lambda page: read[page.pk][0] / read[page.pk][1],
            )
            attention = [page for page in attention if read[page.pk][0] < read[page.pk][1]]
            counts["attention"] = len(attention)
            counts["awaiting"] = sum(read[page.pk][1] - read[page.pk][0] for page in attention)
            attention = attention[:5]
        to_read = mine[:5]
        return Response(
            {
                "counts": counts,
                "attention": KnowledgePageRowSerializer(attention, many=True, context=context).data,
                "recent": KnowledgePageRowSerializer(recent, many=True, context=context).data,
                "to_read": KnowledgePageRowSerializer(to_read, many=True, context=context).data,
            }
        )


class PositionsView(OwnerAPIView):
    """Positions a space can be read by."""

    perm = MANAGE

    @extend_schema(responses=KnowledgeRefSerializer(many=True))
    def get(self, request, company_id):
        positions = Position.objects.filter(company=self.company, is_active=True).order_by(
            "order", "name"
        )
        return Response([{"id": p.pk, "name": p.name} for p in positions])


class SettingsView(OwnerAPIView):
    perm = None
    perms_by_action = {"patch": MANAGE, "put": MANAGE}

    @extend_schema(responses=KnowledgeSettingsSerializer)
    def get(self, request, company_id):
        row = get_settings(self.company)
        return Response(KnowledgeSettingsSerializer(row).data)

    @extend_schema(request=KnowledgeSettingsSerializer, responses=KnowledgeSettingsSerializer)
    def patch(self, request, company_id):
        data = KnowledgeSettingsSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        row = services.update_settings(self.company, by=self.membership, **data.validated_data)
        return Response(KnowledgeSettingsSerializer(row).data)


__all__ = [
    "ImageUploadView",
    "LinkDeleteView",
    "LinkTargetsView",
    "OverviewView",
    "PageViewSet",
    "PositionsView",
    "SettingsView",
    "SpaceViewSet",
]
