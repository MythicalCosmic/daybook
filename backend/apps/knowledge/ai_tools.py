"""Read-only AI tools of the knowledge base.

Each wraps a function of `queries.py` and registers with `apps.ai.tools.registry.ai_tool`.
"""

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolNotFound, ToolResult, ai_tool
from apps.knowledge import queries, sanitize
from apps.members.permissions import Perm


class SearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=100, description="Words to look for.")


@ai_tool(
    "knowledge_search",
    domain="knowledge",
    perm=Perm.DASHBOARD_ACCESS,
    label=_("Search the company's knowledge base pages (how-tos, rules) the asker may read"),
    input=SearchInput,
)
def knowledge_search(ctx: ToolContext, args: SearchInput) -> ToolResult:
    pages = queries.search(ctx.membership, args.query, limit=10)
    return ToolResult(
        rows=[
            {
                "id": page.pk,
                "title": page.title,
                "space": page.space.name,
                "published": page.published,
                "excerpt": sanitize.excerpt(page.body_text, 300),
            }
            for page in pages
        ]
    )


class PageInput(BaseModel):
    page_id: int = Field(description="The id of a page from knowledge_search.")


@ai_tool(
    "knowledge_page",
    domain="knowledge",
    perm=Perm.DASHBOARD_ACCESS,
    label=_("Read one knowledge base page as text"),
    input=PageInput,
)
def knowledge_page(ctx: ToolContext, args: PageInput) -> ToolResult:
    page = queries.get_page(ctx.membership, args.page_id)
    if page is None or page.archived_at is not None:
        raise ToolNotFound
    return ToolResult(
        data={
            "id": page.pk,
            "title": page.title,
            "space": page.space.name,
            "published": page.published,
            "require_ack": page.require_ack,
            "text": page.body_text[:8000],
        }
    )
