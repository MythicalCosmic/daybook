import factory
from factory.django import DjangoModelFactory

from apps.tasks.models import Task, TaskTemplate


class TaskFactory(DjangoModelFactory):
    """A personal task unless `created_by` names someone other than the assignee."""

    class Meta:
        model = Task

    company = factory.SelfAttribute("assignee.company")
    kind = factory.LazyAttribute(
        lambda task: (
            Task.Kind.PERSONAL
            if task.created_by is None or task.created_by == task.assignee
            else Task.Kind.ASSIGNED
        )
    )
    title = factory.Sequence(lambda n: f"Task {n}")
    created_by = factory.SelfAttribute("assignee")


class TaskTemplateFactory(DjangoModelFactory):
    class Meta:
        model = TaskTemplate
        skip_postgeneration_save = True

    title = factory.Sequence(lambda n: f"Daily {n}")
    due_time = "18:00"

    @factory.post_generation
    def assignees(self, create, members, **kwargs):
        if create and members:
            self.assignees.set(members)

    @factory.post_generation
    def positions(self, create, positions, **kwargs):
        if create and positions:
            self.positions.set(positions)
