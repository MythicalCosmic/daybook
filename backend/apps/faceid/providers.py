"""What Face ID hands to the shared registries (wired in `hooks.py`): the snapshot file check
and the count behind the "not in Daybook" badge."""

from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm


def photo_check(user, company_id, object_id) -> bool:
    """A scan's snapshot opens for its person, or for `attendance.view` holders who see the
    terminal's branch."""
    from apps.faceid.models import FaceEvent

    event = (
        FaceEvent.objects.for_company(company_id)
        .filter(pk=object_id)
        .select_related("membership", "device")
        .first()
    )
    if event is None:
        return False
    if event.membership_id and event.membership.user_id == user.pk:
        return True
    viewer = (
        Membership.objects.filter(
            company_id=company_id, user=user, status=Membership.Status.APPROVED
        )
        .select_related("role", "company")
        .first()
    )
    return (
        viewer is not None
        and viewer.has_perm(Perm.ATTENDANCE_VIEW)
        and scope.allows(scope.branch_ids(viewer), event.device.branch_id)
    )


def unlinked_count(member: Membership) -> int:
    """Numbers the terminals of the caller's branches saw that nobody is linked to."""
    from apps.faceid import services
    from apps.faceid.models import FaceDevice

    devices = scope.restrict(
        FaceDevice.objects.filter(company=member.company), scope.branch_ids(member)
    )
    rows = services.unlinked_numbers(
        member.company, device_ids=list(devices.values_list("pk", flat=True))
    )
    return rows.values("number_key").distinct().count()
