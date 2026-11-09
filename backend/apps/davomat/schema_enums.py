"""drf-spectacular enum names of Davomat, merged into `ENUM_NAME_OVERRIDES`. Read by file path
when the settings load (see apps/agenda/schema_enums.py). The import rows' actions are
inventory's choices already (InventoryImportActionEnum)."""

ENUM_NAME_OVERRIDES = {
    "DavomatRoleKindEnum": ["owner", "admin", "manager", "viewer"],
    "DavomatEditionEnum": ["davomat", "daybook"],
    "DavomatEmployeeStatusEnum": ["active", "left"],
    "DavomatTodayStateEnum": ["in", "out", "not_in", "off", "leave"],
    "DavomatEmployeeSourceEnum": ["manual", "import", "terminal"],
    "DavomatBotStatusEnum": "apps.davomat.models.DavomatSettings.BotStatus",
}
