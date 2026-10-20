"""Employee (mini app) endpoints of the knowledge base; routed in `urls.py`.

Everyone reads the spaces meant for them: all approved members for an "everyone" space, the
holders of its positions otherwise (`queries.reader_spaces`). Drafts never show here, not even
to managers, who edit pages in the dashboard.
"""

from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.knowledge import queries, services
from apps.knowledge.models import Page, PageLink
from apps.knowledge.serializers import (
    KnowledgeLinkSerializer,
    KnowledgePageDetailSerializer,
    KnowledgePageRowSerializer,
    KnowledgeSpaceSerializer,
    KnowledgeTreeNodeSerializer,
    tree_json,
)
from apps.members.api import IsCompanyMember


def _context(view, **extra) -> dict:
    return {"request": view.request, "membership": view.membership, "view": view, "reader": True}


def _counts(pages) -> dict[int, dict[str, int]]:
    counts: dict[int, int] = {}
    for space_id in pages.values_list("space_id", flat=True):
        counts[space_id] = counts.get(space_id, 0) + 1
    return {pk: {"pages": n, "published": n, "drafts": 0} for pk, n in counts.items()}


class HomeView(APIView):
    """The knowledge base in the app: my spaces, what I still have to read, recent pages."""

    permission_classes = (IsAuthenticated, IsCompanyMember)

    @extend_schema(
        responses=inline_serializer(
            "KnowledgeHome",
            {
                "spaces": KnowledgeSpaceSerializer(many=True),
                "to_read": KnowledgePageRowSerializer(many=True),
                "recent": KnowledgePageRowSerializer(many=True),
            },
        )
    )
    def get(self, request, company_id):
        member = self.membership
        pages = queries.reader_pages(member).select_related("space", "updated_by__user")
        context = _context(self) | {"counts": _counts(pages)}
        return Response(
            {
                "spaces": KnowledgeSpaceSerializer(
                    queries.reader_spaces(member), many=True, context=context
                ).data,
                "to_read": KnowledgePageRowSerializer(
                    queries.to_read(member), many=True, context=context
                ).data,
                "recent": KnowledgePageRowSerializer(
                    pages.order_by("-updated_at")[:6], many=True, context=context
                ).data,
            }
        )


class SpaceView(APIView):
    """One space and its published pages as a tree."""

    permission_classes = (IsAuthenticated, IsCompanyMember)

    @extend_schema(
        responses=inline_serializer(
            "KnowledgeSpaceTree",
            {"space": KnowledgeSpaceSerializer(), "pages": KnowledgeTreeNodeSerializer(many=True)},
        )
    )
    def get(self, request, company_id, pk):
        member = self.membership
        space = queries.reader_spaces(member).filter(pk=pk).first()
        if space is None:
            raise NotFound
        pages = queries.reader_pages(member).filter(space=space)
        context = _context(self) | {"counts": _counts(pages)}
        return Response(
            {
                "space": KnowledgeSpaceSerializer(space, context=context).data,
                "pages": tree_json(queries.tree(member, space, reader=True)),
            }
        )


class PageView(APIView):
    """A page to read, with my acknowledgement."""

    permission_classes = (IsAuthenticated, IsCompanyMember)

    def _page(self, pk) -> Page:
        page = (
            queries.reader_pages(self.membership)
            .select_related("space", "updated_by__user", "created_by__user")
            .filter(pk=pk)
            .first()
        )
        if page is None:
            raise NotFound
        return page

    @extend_schema(responses=KnowledgePageDetailSerializer)
    def get(self, request, company_id, pk):
        return Response(KnowledgePageDetailSerializer(self._page(pk), context=_context(self)).data)


class AckView(PageView):
    http_method_names = ["post", "options"]

    @extend_schema(
        request=None,
        responses=inline_serializer(
            "KnowledgeEmployeeAck",
            {"version": serializers.IntegerField(), "at": serializers.DateTimeField()},
        ),
    )
    def post(self, request, company_id, pk):
        """I've read it: confirms the current version."""
        ack = services.acknowledge(self._page(pk), by=self.membership)
        return Response({"version": ack.version, "at": ack.at})


class SearchView(APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember)

    @extend_schema(
        parameters=[OpenApiParameter("q", str)], responses=KnowledgePageRowSerializer(many=True)
    )
    def get(self, request, company_id):
        found = queries.search(
            self.membership, request.query_params.get("q", ""), limit=20, reader=True
        )
        return Response(KnowledgePageRowSerializer(found, many=True, context=_context(self)).data)


class LinkedView(APIView):
    """Pages linked to a task or routine ("How to do this")."""

    permission_classes = (IsAuthenticated, IsCompanyMember)

    @extend_schema(
        parameters=[
            OpenApiParameter("target_type", str, enum=PageLink.Target.values, required=True),
            OpenApiParameter("target_id", int, required=True),
        ],
        responses=KnowledgeLinkSerializer(many=True),
    )
    def get(self, request, company_id):
        target_type = request.query_params.get("target_type")
        try:
            target_id = int(request.query_params.get("target_id", ""))
        except ValueError:
            target_id = None
        if target_type not in PageLink.Target.values or target_id is None:
            raise ValidationError({"target_type": [_("Give a task or routine and its id.")]})
        links = (
            PageLink.objects.for_company(self.membership.company_id)
            .filter(
                target_type=target_type,
                target_id=target_id,
                page__in=queries.reader_pages(self.membership),
            )
            .select_related("page__space")
        )
        return Response(KnowledgeLinkSerializer(links, many=True).data)
