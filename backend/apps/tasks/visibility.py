"""Extra rules for which tasks a member may see, registered by other apps.

`tasks.queries.visible_tasks` applies its own rules first (personal tasks, branch scope,
tasks.view_all, tasks.confirm) and then every registered filter, in key order, so a filter can
only narrow what a member sees, never widen it:

    register_task_visibility_filter("projects.members", hide_private_project_tasks)

A filter is `(tasks: QuerySet[Task], member: Membership) -> QuerySet[Task]`. Keys start with
the registering app's label; registering a key twice raises.
"""

from collections.abc import Callable

from django.db.models import QuerySet

TaskFilter = Callable[[QuerySet, object], QuerySet]

_filters: dict[str, TaskFilter] = {}


class DuplicateTaskFilter(ValueError):
    pass


def register_task_visibility_filter(key: str, fn: TaskFilter) -> None:
    app_label, dot, rest = key.partition(".")
    if not dot or not app_label or not rest:
        raise ValueError(f"Filter keys look like '<app>.<name>', not {key!r}.")
    if key in _filters:
        raise DuplicateTaskFilter(f"A task visibility filter {key!r} is already registered.")
    _filters[key] = fn


def apply_filters(tasks: QuerySet, member) -> QuerySet:
    for key in sorted(_filters):
        tasks = _filters[key](tasks, member)
    return tasks


def registered_keys() -> list[str]:
    return sorted(_filters)
