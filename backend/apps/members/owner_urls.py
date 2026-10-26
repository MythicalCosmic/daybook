"""Owner endpoints of people, join requests, team links, roles and positions, mounted at
`/api/v1/owner/companies/<int:company_id>/` (docs/PLAN-OWNER.md §4.6)."""

from rest_framework.routers import SimpleRouter

from apps.members.link_api import JoinLinkViewSet
from apps.members.owner_api import JoinRequestViewSet, PeopleViewSet, PositionViewSet, RoleViewSet

router = SimpleRouter()
router.register("people", PeopleViewSet, basename="members-people")
router.register("join-requests", JoinRequestViewSet, basename="members-join-request")
router.register("join-links", JoinLinkViewSet, basename="members-join-link")
router.register("roles", RoleViewSet, basename="members-role")
router.register("positions", PositionViewSet, basename="members-position")

urlpatterns = router.urls
