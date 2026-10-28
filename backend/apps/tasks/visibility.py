"""Extra rules for which tasks a member may see, registered by other apps.

`tasks.queries.visible_tasks` applies its own rules first (personal tasks, branch scope,
tasks.view_all, tasks.confirm) and then every registered filter, in key order, so a filter can
only narrow what a member sees, never widen it:

    register_task_visibility_filter("projects.members", hide_private_project_tasks)

A filter is `(tasks: QuerySet[Task], member: Membership) -> QuerySet[Task]`. Keys start with
the registering app's label; registering a key twice raises.
"""

from collections.abc import Callable

from django.apps import apps as django_apps
from django.db.models import QuerySet

TaskFilter = Callable[[QuerySet, object], QuerySet]

_filters: dict[str, TaskFilter] = {}


class DuplicateTaskFilter(ValueError):
    pass


def register_task_visibility_filter(key: str, fn: TaskFilter) -> None:
    app_label, dot, rest = key.partition(".")
    if not dot or not app_label or not rest:
        raise ValueError(f"Filter keys look like '<app>.<name>', not {key!r}.")
    if django_apps.ready and not any(
        config.label == app_label for config in django_apps.get_app_configs()
    ):
        raise ValueError(f"Filter key {key!r} must start with an installed app's label.")
    if key in _filters:
        raise DuplicateTaskFilter(f"A task visibility filter {key!r} is already registered.")
    _filters[key] = fn


def apply_filters(tasks: QuerySet, member) -> QuerySet:
    for key in sorted(_filters):
        tasks = _filters[key](tasks, member)
    return tasks


def registered_keys() -> list[str]:
    return sorted(_filters)


def head_sees(task, member) -> bool:
    """Whether `member` heads the task's assignee (apps.members.departments) and the registered
    filters let them see it (a card of a members-only project stays hidden from a head who
    isn't on it). Someone's personal tasks are never their head's."""
    from apps.members.departments import manages
    from apps.tasks.models import Task

    if task.kind == Task.Kind.PERSONAL or not manages(member, task.assignee):
        return False
    return apply_filters(Task.objects.filter(pk=task.pk), member).exists()
