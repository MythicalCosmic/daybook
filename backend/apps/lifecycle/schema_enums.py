"""drf-spectacular enum names of the people lifecycle, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string, e.g.
`{"LifecycleThingStatusEnum": "apps.lifecycle.models.Thing.Status"}`. Names start with the
app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "LifecycleRecordKindEnum": "apps.lifecycle.models.DisciplinaryRecord.Kind",
    "LifecycleRecordCategoryEnum": "apps.lifecycle.models.DisciplinaryRecord.Category",
    "LifecycleRecordStatusEnum": "apps.lifecycle.models.DisciplinaryRecord.Status",
    "LifecycleLeavingKindEnum": "apps.lifecycle.models.Termination.Kind",
    "LifecycleLeavingStatusEnum": "apps.lifecycle.models.Termination.Status",
    "LifecycleRehireEnum": "apps.lifecycle.models.Termination.Rehire",
    "LifecycleHandoverKindEnum": "apps.lifecycle.models.HandoverItem.Kind",
    "LifecycleHandoverAddKindEnum": "apps.lifecycle.terminations.ADDABLE",
    "LifecycleExitReasonEnum": "apps.lifecycle.terminations.EXIT_REASONS",
    "LifecycleRecommendEnum": "apps.lifecycle.terminations.RECOMMEND",
    "LifecycleJobChangeStatusEnum": "apps.lifecycle.models.JobChange.Status",
}
