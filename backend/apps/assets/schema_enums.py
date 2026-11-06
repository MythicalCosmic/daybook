"""drf-spectacular enum names of fixed assets, merged into `ENUM_NAME_OVERRIDES`.

Read by file path when the settings load: import strings only.
"""

ENUM_NAME_OVERRIDES = {
    "AssetsStatusEnum": "apps.assets.models.Asset.Status",
    "AssetsConditionEnum": "apps.assets.models.Asset.Condition",
    "AssetsDisposalEnum": "apps.assets.models.Asset.Disposal",
    "AssetsMethodEnum": "apps.assets.models.Method",
    "AssetsStartRuleEnum": "apps.assets.models.StartRule",
    "AssetsCategoryKindEnum": "apps.assets.models.AssetCategory.Kind",
    "AssetsEventKindEnum": "apps.assets.models.AssetEvent.Kind",
    "AssetsFileKindEnum": "apps.assets.models.AssetFile.Kind",
    "AssetsCountStatusEnum": "apps.assets.models.AssetCount.Status",
    "AssetsCountResultEnum": "apps.assets.models.AssetCountLine.Result",
    "AssetsUpkeepEnum": "apps.assets.serializers.UPKEEP_KINDS",
    "AssetsMonthStateEnum": "apps.assets.serializers.MONTH_STATES",
    "AssetsReportGroupEnum": "apps.assets.serializers.REPORT_GROUPS",
    "AssetsWritableStatusEnum": "apps.assets.serializers.WRITABLE_STATUSES",
}
