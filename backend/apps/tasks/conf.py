"""The company's rules for finished work (PLAN-OWNER §15.3): the lazy settings row
(`apps.core.settings_rows.get_or_create_for`) and what a new task or routine starts with."""

from apps.core.settings_rows import get_or_create_for
from apps.tasks.models import OnFinish, TasksSettings

# The `needs_confirmation` of the create and routine forms (API help text).
REVIEW_RULE_HELP = (
    "Empty: the company's rule for finished work decides (tasks settings); true always asks "
    "for a check, false never does."
)


def get_settings(company) -> TasksSettings:
    return get_or_create_for(TasksSettings, company)


def review_rule(company, needs_confirmation: bool | None) -> tuple[bool, bool]:
    """`(needs_confirmation, accept_with_proof)` of a new task or routine. An explicit choice
    wins: True always asks, False never does. Without one the company's "When someone finishes
    a task" decides: accept automatically, accept automatically only with a photo or text
    proof (otherwise ask), or always ask."""
    if needs_confirmation is not None:
        return bool(needs_confirmation), False
    rule = get_settings(company).on_finish
    if rule == OnFinish.ASK:
        return True, False
    if rule == OnFinish.PROOF:
        return True, True
    return False, False
