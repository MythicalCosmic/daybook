"""drf-spectacular enum names of projects, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string, e.g.
`{"ProjectsThingStatusEnum": "apps.projects.models.Thing.Status"}`. Names start with the
app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "ProjectsProjectStatusEnum": "apps.projects.models.Project.Status",
    "ProjectsProjectVisibilityEnum": "apps.projects.models.Project.Visibility",
    "ProjectsHealthEnum": "apps.projects.models.Health",
    "ProjectsMemberRoleEnum": "apps.projects.models.ProjectMember.Role",
    "ProjectsMilestoneStatusEnum": "apps.projects.models.Milestone.Status",
    "ProjectsTimeSourceEnum": "apps.projects.models.TimeEntry.Source",
}
