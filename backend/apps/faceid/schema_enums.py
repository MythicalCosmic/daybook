"""drf-spectacular enum names of Face ID, merged into `ENUM_NAME_OVERRIDES`. Read by file path
when the settings load."""

ENUM_NAME_OVERRIDES = {
    "FaceidDirectionEnum": "apps.faceid.models.FaceDevice.Direction",
    "FaceidEventKindEnum": "apps.faceid.models.FaceEvent.Kind",
    "FaceidEventActionEnum": "apps.faceid.models.FaceEvent.Action",
    "FaceidEventFlagEnum": "apps.faceid.models.FaceEvent.Flag",
    "FaceidTelegramEnum": "apps.faceid.models.FaceIdSettings.Telegram",
    "FaceidScanModeEnum": "apps.faceid.models.FaceIdSettings.ScanMode",
    "FaceidDeviceStatusEnum": "apps.faceid.serializers.DeviceStatus",
}
