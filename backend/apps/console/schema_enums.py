"""drf-spectacular enum names of the owner console, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string, e.g.
`{"ConsoleThingStatusEnum": "apps.console.models.Thing.Status"}`. Names start with the
app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    # Buttons on Needs you items and on notifications share these.
    "ConsoleActionStyleEnum": "apps.console.registry.QUEUE_STYLES",
    "ConsoleActionMethodEnum": "apps.console.registry.QUEUE_METHODS",
    "ConsoleBranchStatusEnum": "apps.console.queries.BRANCH_STATUSES",
}
