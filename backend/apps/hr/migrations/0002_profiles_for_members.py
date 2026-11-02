"""Everyone working in a company when HR records arrived gets a profile, hired on the day they
were approved: their latest approval in the audit log, else the approval on the membership
(else when they registered or were added), in the company's own calendar. Profiles made since
come from `member_approved`; running this again adds nothing."""

from zoneinfo import ZoneInfo

from django.db import migrations
from django.utils import timezone

CURRENT = ("approved", "suspended")
BATCH = 500


def create_profiles(apps, schema_editor):
    Membership = apps.get_model("members", "Membership")
    AuditLog = apps.get_model("audit", "AuditLog")
    EmployeeProfile = apps.get_model("hr", "EmployeeProfile")
    have = set(EmployeeProfile.objects.values_list("membership_id", flat=True))
    members = (
        Membership.objects.filter(status__in=CURRENT)
        .exclude(pk__in=have)
        .select_related("company")
        .order_by("pk")
    )
    approved = {}
    rows = AuditLog.objects.filter(action="member.approved", target_type="membership").order_by(
        "target_id", "-created_at", "-pk"
    )
    for target_id, created_at in rows.values_list("target_id", "created_at"):
        approved.setdefault(target_id, created_at)
    batch = []
    for member in members.iterator(chunk_size=BATCH):
        moment = (
            approved.get(member.pk) or member.decided_at or member.onboarded_at or member.created_at
        )
        hired = timezone.localtime(moment, ZoneInfo(member.company.timezone)).date()
        batch.append(
            EmployeeProfile(company_id=member.company_id, membership_id=member.pk, hire_date=hired)
        )
        if len(batch) >= BATCH:
            EmployeeProfile.objects.bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        EmployeeProfile.objects.bulk_create(batch, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("hr", "0001_profiles_documents"),
        ("members", "0015_position_role"),
        ("audit", "0005_auditlog_free_action_required_perm"),
    ]

    operations = [migrations.RunPython(create_profiles, migrations.RunPython.noop)]
