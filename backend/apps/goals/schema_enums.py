"""drf-spectacular enum names of business goals, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string. Names start with
the app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "GoalsMetricEnum": "apps.goals.models.Metric",
    "GoalsStatusEnum": "apps.goals.models.Goal.Status",
    "GoalsStateEnum": "apps.goals.models.Goal.State",
}
