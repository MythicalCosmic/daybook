from django.db import migrations
from django.db.models import F


def sent_when_created(apps, schema_editor):
    """Every existing announcement went out when it was written."""
    Announcement = apps.get_model("announcements", "Announcement")
    Announcement.objects.filter(sent_at__isnull=True, status="sent").update(sent_at=F("created_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("announcements", "0002_announcement_branches_scheduling"),
    ]

    operations = [
        migrations.RunPython(sent_when_created, migrations.RunPython.noop),
    ]
