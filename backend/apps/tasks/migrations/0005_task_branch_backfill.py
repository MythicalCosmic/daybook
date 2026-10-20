from django.db import migrations
from django.db.models import OuterRef, Subquery


def take_the_assignees_branch(apps, schema_editor):
    """Existing tasks belong to their assignee's home branch, as new ones do from creation."""
    Task = apps.get_model("tasks", "Task")
    Membership = apps.get_model("members", "Membership")
    home = Membership.objects.filter(pk=OuterRef("assignee_id")).values("home_branch_id")[:1]
    Task.objects.filter(branch__isnull=True).update(branch_id=Subquery(home))


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0006_membership_branches"),
        ("tasks", "0004_task_reward_branch_project"),
    ]

    operations = [
        migrations.RunPython(take_the_assignees_branch, migrations.RunPython.noop),
    ]
