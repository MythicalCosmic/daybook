"""Signal receivers of projects (connected in `hooks.py`).

`tasks.Task` is saved by the task app (completion from the bot, the mini app, the owner API,
a confirmation, a reassignment). Whatever path a project's task takes, its card follows:

- a task put on a project gets its board place and number;
- a task that reaches DONE moves to the done list;
- a task given to someone outside the project adds them as a member.
"""

from apps.members.models import Membership
from apps.projects import queries, services
from apps.projects.models import Card, Project, ProjectMember
from apps.tasks.models import Task

WATCHED_FIELDS = {"status", "assignee", "project", "project_list"}


def task_saved(sender, instance: Task, created: bool = False, raw: bool = False, **kwargs) -> None:
    if raw or instance.project_id is None:
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not (set(update_fields) & WATCHED_FIELDS):
        return
    project = Project.objects.filter(pk=instance.project_id).select_related("company").first()
    if project is None:
        return
    if not Card.objects.filter(task_id=instance.pk).exists():
        services.place_card(instance, project, project_list=instance.project_list)
    if instance.status == Task.Status.DONE:
        done = queries.done_list(project)
        current = (
            Task.objects.filter(pk=instance.pk).values_list("project_list_id", flat=True).first()
        )
        if done is not None and current != done.pk:
            position = queries.end_position(done)
            Task.objects.filter(pk=instance.pk).update(project_list=done, list_position=position)
            instance.project_list = done
            instance.list_position = position
    assignee_id = instance.assignee_id
    if (
        assignee_id is not None
        and assignee_id != project.lead_id
        and instance.assignee.status == Membership.Status.APPROVED
        and not ProjectMember.objects.filter(project=project, membership_id=assignee_id).exists()
    ):
        services.add_member(project, instance.assignee, by=None)
