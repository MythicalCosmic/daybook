"""drf-spectacular enum names of memberships, merged into `ENUM_NAME_OVERRIDES` (see
apps/agenda/schema_enums.py). Membership.Status is named in the settings themselves."""

ENUM_NAME_OVERRIDES = {
    "MembersJoinLinkStatusEnum": "apps.members.models.JoinLink.Status",
    "MembersBulkDecisionEnum": ["approve", "reject"],
}
