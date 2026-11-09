"""drf-spectacular enum names of recognition, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string, e.g.
`{"RecognitionThingStatusEnum": "apps.recognition.models.Thing.Status"}`. Names start with the
app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "RecognitionReasonEnum": "apps.recognition.models.PointsEntry.Reason",
    "RecognitionKudosBadgeEnum": "apps.recognition.models.Kudos.Badge",
    "RecognitionScopeEnum": "apps.recognition.models.RecognitionSettings.Scope",
    "RecognitionTierEnum": "apps.recognition.serializers.TIER_CHOICES",
    "RecognitionUnseenTypeEnum": "apps.recognition.serializers.UNSEEN_TYPES",
    "RecognitionPeriodEnum": "apps.recognition.serializers.PERIOD_CHOICES",
    "RecognitionBoardKindEnum": "apps.recognition.serializers.KINDS",
}
