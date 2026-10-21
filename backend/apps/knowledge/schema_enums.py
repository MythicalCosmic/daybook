"""drf-spectacular enum names of the knowledge base, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string, e.g.
`{"KnowledgeThingStatusEnum": "apps.knowledge.models.Thing.Status"}`. Names start with the
app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "KnowledgeLinkTargetEnum": "apps.knowledge.models.PageLink.Target",
}
