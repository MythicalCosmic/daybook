"""drf-spectacular enum names of exports, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string, e.g.
`{"ExportsThingStatusEnum": "apps.exports.models.Thing.Status"}`. Names start with the
app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "ExportsStatusEnum": "apps.exports.models.Export.Status",
    "ExportsFormatEnum": "apps.exports.models.Export.Format",
    "ExportsColumnKindEnum": "apps.exports.registry.COLUMN_KINDS",
}
