"""Demo data of time off: the year's public holidays, leave around today across both branches
(approved, waiting, recorded sick leave, a revoked day, a refusal) so the month calendar and
"Needs you" look like a real shop's."""

from datetime import date, timedelta

from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.members.models import Membership
from apps.timeoff.audit_actions import TimeOffAuditAction
from apps.timeoff.models import Holiday, TimeOff
from apps.timeoff.services import PUBLIC_HOLIDAYS

# Holiday names in the shop's own words (the demo company writes in Uzbek).
UZ_NAMES = {
    (1, 1): "Yangi yil",
    (3, 8): "Xalqaro xotin-qizlar kuni",
    (3, 21): "Navro‘z bayrami",
    (5, 9): "Xotira va qadrlash kuni",
    (9, 1): "Mustaqillik kuni",
    (10, 1): "O‘qituvchi va murabbiylar kuni",
    (12, 8): "Konstitutsiya kuni",
}
LUNAR = {2026: ((3, 20, "Ramazon hayiti"), (5, 27, "Qurbon hayiti"))}


def seed(company, people, now) -> None:
    owner, manager = people["owner"], people["manager"]
    today = timezone.localdate()
    for year in (today.year, today.year + 1):
        for month, day, _name in PUBLIC_HOLIDAYS:
            Holiday.objects.get_or_create(
                company=company,
                date=date(year, month, day),
                defaults={"name": UZ_NAMES[(month, day)]},
            )
        for month, day, name in LUNAR.get(year, ()):
            Holiday.objects.get_or_create(
                company=company, date=date(year, month, day), defaults={"name": name}
            )

    staff = {
        f"{m.first_name} {m.last_name}": m
        for m in Membership.objects.filter(
            company=company, status=Membership.Status.APPROVED, onboarded_at__isnull=False
        )
    }

    def who(name, fallback):
        return staff.get(name) or people[fallback]

    def leave(
        member,
        start,
        end,
        *,
        status=TimeOff.Status.APPROVED,
        reason="",
        decided_by=None,
        recorded_by=None,
        created_days_ago=3,
    ):
        if member is None:
            return None
        clash = TimeOff.objects.filter(
            membership=member,
            status__in=(TimeOff.Status.PENDING, TimeOff.Status.APPROVED),
            first_day__lte=end,
            last_day__gte=start,
        )
        if clash.exists():
            return None
        row = TimeOff.objects.create(
            company=company,
            membership=member,
            first_day=start,
            last_day=end,
            status=status,
            reason=reason,
            decided_by=decided_by.user if decided_by else None,
            decided_at=now - timedelta(days=max(created_days_ago - 1, 0))
            if status != TimeOff.Status.PENDING
            else None,
            recorded_by=recorded_by,
        )
        TimeOff.objects.filter(pk=row.pk).update(created_at=now - timedelta(days=created_days_ago))
        if status == TimeOff.Status.APPROVED and decided_by is not None:
            action = (
                TimeOffAuditAction.RECORDED if recorded_by else AuditLog.Action.TIME_OFF_APPROVED
            )
            entry = audit.record(
                action,
                company_id=company.pk,
                actor=decided_by.user,
                target=row,
                first_day=start.isoformat(),
                last_day=end.isoformat(),
            )
            AuditLog.objects.filter(pk=entry.pk).update(
                created_at=now - timedelta(days=created_days_ago)
            )
        return row

    d = lambda offset: today + timedelta(days=offset)  # noqa: E731

    # Approved leave around today.
    leave(
        who("Dilshod Karimov", "jasur"),
        d(-3),
        d(1),
        reason="Oilaviy to‘y, Samarqand",
        decided_by=manager,
        created_days_ago=9,
    )
    leave(
        who("Shahzoda Yusupova", "worker"),
        d(4),
        d(6),
        reason="Ta’til",
        decided_by=owner,
        created_days_ago=6,
    )
    leave(
        who("Aziza Rasulova", "owner"),
        d(10),
        d(16),
        reason="Yillik ta’til",
        decided_by=owner,
        created_days_ago=12,
    )
    leave(
        who("Malika Tosheva", "madina"),
        d(-12),
        d(-8),
        reason="Ta’til",
        decided_by=manager,
        created_days_ago=20,
    )
    leave(
        who("Sherzod Umarov", "nigora"),
        d(13),
        d(14),
        reason="Universitet imtihoni",
        decided_by=manager,
        created_days_ago=2,
    )
    # Sick leave recorded after the fact, with the doctor's note on paper.
    leave(
        who("Otabek Nazarov", "jasur"),
        d(-6),
        d(-4),
        reason="Kasallik varaqasi (shamollash)",
        decided_by=manager,
        recorded_by=manager,
        created_days_ago=3,
    )
    leave(
        who("Ulug‘bek Qodirov", "nigora"),
        d(-1),
        d(0),
        reason="Isitma, shifokor ko‘rigi",
        decided_by=manager,
        recorded_by=manager,
        created_days_ago=1,
    )

    # Requests waiting for a decision.
    leave(
        who("Gulnora Ismoilova", "worker"),
        d(8),
        d(10),
        status=TimeOff.Status.PENDING,
        reason="Singlimning to‘yi",
        created_days_ago=1,
    )
    leave(
        who("Kamola Ergasheva", "madina"),
        d(3),
        d(3),
        status=TimeOff.Status.PENDING,
        reason="Shifokor qabuli",
        created_days_ago=0,
    )
    leave(
        who("Zarina Abdullayeva", "jasur"),
        d(18),
        d(21),
        status=TimeOff.Status.PENDING,
        reason="Toshkentdan tashqariga safar",
        created_days_ago=0,
    )

    # A refusal and a revoked day, for the history.
    leave(
        who("Sardor Rahimov", "madina"),
        d(2),
        d(4),
        status=TimeOff.Status.REJECTED,
        reason="Dam olish",
        decided_by=manager,
        created_days_ago=5,
    )
    revoked = leave(
        who("Farrux Aliyev", "manager"),
        d(5),
        d(7),
        reason="Ta’til",
        decided_by=owner,
        created_days_ago=8,
    )
    if revoked is not None:
        TimeOff.objects.filter(pk=revoked.pk).update(
            last_day=d(6),
            revoked_at=now - timedelta(days=1),
            revoked_by=owner.user,
            revoke_reason="Shanba kuni inventarizatsiya, Farrux kerak",
        )
        entry = audit.record(
            TimeOffAuditAction.REVOKED,
            company_id=company.pk,
            actor=owner.user,
            target=revoked,
            cancelled_from=d(7).isoformat(),
            cancelled_to=d(7).isoformat(),
            reason="Shanba kuni inventarizatsiya, Farrux kerak",
        )
        AuditLog.objects.filter(pk=entry.pk).update(created_at=now - timedelta(days=1))
