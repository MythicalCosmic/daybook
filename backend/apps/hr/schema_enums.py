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
    "HrContractKindEnum": "apps.hr.models.ContractKind",
    "HrContractStatusEnum": "apps.hr.models.Contract.Status",
    # Hiring (apps.hr.hiring).
    "HrVacancyStatusEnum": "apps.hr.models.Vacancy.Status",
    "HrQuestionKindEnum": "apps.hr.models.QuestionKind",
    "HrApplicantStageEnum": "apps.hr.models.Applicant.Stage",
    "HrApplicantPipelineStageEnum": "apps.hr.hiring.queries.OPEN_STAGES",
    "HrApplicantSourceEnum": "apps.hr.models.Applicant.Source",
    "HrApplicantEventKindEnum": "apps.hr.models.ApplicantEvent.Kind",
    "HrPharmacistRoleEnum": "apps.hr.services.PHARMACIST_ROLES",
    "HrCoverageStateEnum": "apps.hr.coverage.STATES",
    "HrCoverageReasonEnum": "apps.hr.queries.REASONS",
    "HrCoverageClosedEnum": "apps.hr.coverage.CLOSED",
    # Policies (apps/hr/policies).
    "HrPolicyCategoryEnum": "apps.hr.models.PolicyCategory",
    "HrPolicyStateEnum": "apps.hr.policies.queries.STATES",
    "HrMyPolicyStateEnum": "apps.hr.policies.queries.MY_STATES",
    "HrPolicyFileTypeEnum": "apps.hr.policies.serializers.FILE_TYPES",
}
