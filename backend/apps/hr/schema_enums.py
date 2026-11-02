"""drf-spectacular enum names of HR records, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string, e.g.
`{"HrThingStatusEnum": "apps.hr.models.Thing.Status"}`. Names start with the
app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "HrDocumentKindEnum": "apps.hr.models.DocumentKind",
    "HrDocumentLevelEnum": "apps.hr.models.DocumentLevel",
    "HrGenderEnum": "apps.hr.models.EmployeeProfile.Gender",
    "HrEmploymentTypeEnum": "apps.hr.models.EmployeeProfile.EmploymentType",
    "HrPayoutMethodEnum": "apps.hr.models.EmployeeProfile.PayoutMethod",
    "HrTerminationReasonEnum": "apps.hr.models.EmployeeProfile.TerminationReason",
    "HrDocumentStateEnum": "apps.hr.queries.DOCUMENT_STATES",
    "HrCheckStateEnum": "apps.hr.queries.CHECK_STATES",
}
