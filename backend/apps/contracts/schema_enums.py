"""drf-spectacular enum names of business contracts, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: name choices with an import string. Names start with
the app label in PascalCase and must be unique (duplicates stop the settings).
"""

ENUM_NAME_OVERRIDES = {
    "ContractsKindEnum": "apps.contracts.models.BusinessContract.Kind",
    "ContractsPeriodEnum": "apps.contracts.models.BusinessContract.Period",
    "ContractsStatusEnum": "apps.contracts.models.BusinessContract.Status",
    "ContractsFileKindEnum": "apps.contracts.models.ContractFile.Kind",
}
