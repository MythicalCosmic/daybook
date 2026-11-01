"""Registrations with the shared registries and signal receivers of the AI features.

Imported by `AppConfig.ready()`; register a function only once it exists.
"""

from apps.ai.audit_actions import AIAction
from apps.audit import registry as audit_registry
from apps.console import registry
from apps.core.files import register_file_check

audit_registry.register(AIAction)
# Open dashboards refetch the AI status and settings when they change.
registry.register_pulse("ai.settings", perm=None, count=None)


def _draft_audio_check(user, company_id: int, draft_id: int) -> bool:
    """A voice note's recording: its author, and whoever may see the company's voice notes in
    the dashboard (ai.configure or tasks.view_all, within their branches)."""
    from apps.ai.models import AIDraft
    from apps.console.base import owner_membership
    from apps.members import scope
    from apps.members.permissions import Perm

    draft = AIDraft.objects.filter(company_id=company_id, pk=draft_id).first()
    if draft is None:
        return False
    if draft.created_by.user_id == user.pk:
        return True
    member = owner_membership(user, company_id)
    if member is None or not (
        member.has_perm(Perm.AI_CONFIGURE) or member.has_perm(Perm.TASKS_VIEW_ALL)
    ):
        return False
    branches = scope.branch_ids(member)
    if branches is None:
        return True
    return draft.created_by.branches.filter(pk__in=branches).exists()


register_file_check("ai.draft", _draft_audio_check)
