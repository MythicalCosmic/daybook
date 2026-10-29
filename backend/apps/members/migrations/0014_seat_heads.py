"""Heads made before a head was placed in their department automatically (29.10.2026): one who
works in no department now works in the highest one they head. Everyone else stays where
they are."""

from django.db import migrations


def seat_heads(apps, schema_editor):
    Department = apps.get_model("members", "Department")
    Membership = apps.get_model("members", "Membership")
    parents = dict(Department.objects.values_list("pk", "parent_id"))

    def depth(pk):
        steps, seen = 0, set()
        while pk is not None and pk not in seen:
            seen.add(pk)
            pk = parents.get(pk)
            steps += 1
        return steps

    headed: dict[int, list[int]] = {}
    for pk, head_id in Department.objects.filter(head__isnull=False).values_list("pk", "head_id"):
        headed.setdefault(head_id, []).append(pk)
    for head_id, departments in headed.items():
        highest = min(departments, key=lambda pk: (depth(pk), pk))
        Membership.objects.filter(pk=head_id, department__isnull=True).update(department_id=highest)


class Migration(migrations.Migration):
    dependencies = [("members", "0013_departments")]

    operations = [migrations.RunPython(seat_heads, migrations.RunPython.noop)]
