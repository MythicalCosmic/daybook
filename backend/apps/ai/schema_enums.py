"""drf-spectacular enum names of the AI features, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string, e.g.
`{"AiThingStatusEnum": "apps.ai.models.Thing.Status"}`. Names start with the
app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "AiDraftStatusEnum": "apps.ai.models.AIDraft.Status",
    "AiDraftSourceEnum": "apps.ai.models.AIDraft.Source",
    "AiDraftPriorityEnum": ["normal", "urgent"],
    "AiDraftProofEnum": ["none", "photo"],
    "AiDraftProblemEnum": [
        "no_assignee_match",
        "ambiguous_assignee",
        "no_due",
        "past_due",
        "not_allowed",
    ],
    "AiEngineEnum": ["claude", "rules"],
    "AiClaudeStateEnum": [
        "connected",
        "not_configured",
        "fake",
        "blocked",
        "budget_reached",
        "unavailable",
    ],
    "AiSpeechStateEnum": ["ready", "not_configured", "fake"],
    "AiCustomAgentColorEnum": "apps.ai.models.CustomAgent.Color",
    "AiCustomAgentFrequencyEnum": "apps.ai.models.CustomAgent.Frequency",
    "AiCustomAgentRecipientsEnum": "apps.ai.models.CustomAgent.Recipients",
}
