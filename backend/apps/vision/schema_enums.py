"""drf-spectacular enum names of Ko‘z, merged into `ENUM_NAME_OVERRIDES`. Read by file path when
the settings load: name choices with an import string."""

ENUM_NAME_OVERRIDES = {
    "VisionCameraRoleEnum": "apps.vision.models.Camera.Role",
    "VisionCameraSourceEnum": "apps.vision.models.Camera.Source",
    "VisionAlertKindEnum": "apps.vision.models.Alert.Kind",
    "VisionAlertStateEnum": "apps.vision.models.Alert.State",
    "VisionClipStateEnum": "apps.vision.models.Clip.State",
    "VisionClipReasonEnum": "apps.vision.models.Clip.Reason",
    "VisionClipFailureEnum": "apps.vision.models.Clip.Failure",
    "VisionInsightKindEnum": "apps.vision.insights.Kind",
    "VisionInsightSeverityEnum": "apps.vision.insights.Severity",
    "VisionReviewKindEnum": ["void", "payout"],
}
