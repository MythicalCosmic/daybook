"""drf-spectacular enum names of Telegram groups, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: import strings only.
"""

ENUM_NAME_OVERRIDES = {
    "GroupsEventEnum": "apps.groups.models.GroupEvent",
}
