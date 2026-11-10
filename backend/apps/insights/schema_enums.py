"""drf-spectacular enum names of insights, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string, e.g.
`{"InsightsThingStatusEnum": "apps.insights.models.Thing.Status"}`. Names start with the
app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "InsightsKindEnum": "apps.insights.models.Insight.Kind",
    "InsightsDomainEnum": "apps.insights.models.Insight.Domain",
    "InsightsSeverityEnum": "apps.insights.models.Insight.Severity",
    "InsightsStatusEnum": "apps.insights.models.Insight.Status",
    "InsightsSensitivityEnum": "apps.insights.models.InsightSettings.Sensitivity",
}
