"""What Ko‘z hands to the shared registries (wired in `hooks.py`): who may open its files through
a signed link (`apps.core.files`). Each check runs again whenever a link is opened, so a link
stops working once the person loses the right or the branch, or the module goes off.

    vision.snapshot   a camera's snapshot: vision.video or vision.manage
    vision.photo      an alert's photo: vision.view (or vision.manage)
    vision.clip       a clip's video and poster: vision.video
"""

from apps.console.perms import AnyOf, PermSpec, holds
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

SNAPSHOT = AnyOf(Perm.VISION_VIDEO, Perm.VISION_MANAGE)
PHOTO = AnyOf(Perm.VISION_VIEW, Perm.VISION_MANAGE)
CLIP = Perm.VISION_VIDEO


def _viewer(user, company_id: int) -> Membership | None:
    return (
        Membership.objects.filter(
            company_id=company_id, user=user, status=Membership.Status.APPROVED
        )
        .select_related("role", "company")
        .first()
    )


def _may(user, company_id: int, branch_id: int | None, spec: PermSpec) -> bool:
    from apps.vision import conf

    viewer = _viewer(user, company_id)
    return (
        viewer is not None
        and conf.is_on(viewer.company)
        and holds(viewer, spec)
        and scope.allows(scope.branch_ids(viewer), branch_id)
    )


def snapshot_check(user, company_id, object_id) -> bool:
    from apps.vision.models import Camera

    camera = Camera.objects.for_company(company_id).filter(pk=object_id).first()
    return camera is not None and _may(user, company_id, camera.branch_id, SNAPSHOT)


def photo_check(user, company_id, object_id) -> bool:
    from apps.vision.models import Alert

    alert = Alert.objects.for_company(company_id).filter(pk=object_id).first()
    return alert is not None and _may(user, company_id, alert.branch_id, PHOTO)


def clip_check(user, company_id, object_id) -> bool:
    from apps.vision.models import Clip

    clip = (
        Clip.objects.for_company(company_id).filter(pk=object_id).select_related("camera").first()
    )
    return clip is not None and _may(user, company_id, clip.camera.branch_id, CLIP)
