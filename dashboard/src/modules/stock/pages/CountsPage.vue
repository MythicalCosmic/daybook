<script setup lang="ts">
/**
 * Stock counts (Inventarizatsiya): open counts, counted ones waiting to be applied, and applied
 * ones with their difference at cost. `?new=1` starts one: a full count, part of the catalogue (a
 * category), or the handover count when a head of pharmacy leaves.
 */
import { ClipboardList, Plus } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import BranchPicker from "@/components/BranchPicker.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { stockApi, useCategories, useCounts, useRefresh } from "../api";
import { COUNT_TONES } from "../lib";
import type { Count, CountKind } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const router = useRouter();
const refresh = useRefresh();

const creating = useRouteState("new", rs.boolean(false));
const branch = computed(() => (company.branchFilter.length === 1 ? company.branchFilter[0] : undefined));
const counts = useCounts(computed(() => ({ branch: branch.value })));
const categories = useCategories(creating);
const table = useDataTable({ id: "stock.counts", pageSize: 200 });
const canStart = computed(() => company.can(["stock.manage", "stock.operate"]));

const hasCost = computed(() => (counts.data.value ?? []).some((row) => row.value_difference !== undefined));
const columns = computed<TableColumn<Count>[]>(() => [
  { id: "created_at", header: t("stock.count.started"), width: 150, sticky: true },
  { id: "kind", header: t("stock.count.kind"), minWidth: 160 },
  { id: "branch", header: t("stock.col.branch"), width: 140, value: (row) => row.branch.name },
  { id: "progress", header: t("stock.count.progress"), width: 140 },
  ...(hasCost.value ? [{ id: "value_difference", header: t("stock.count.difference"), numeric: true, width: 150 } as TableColumn<Count>] : []),
  { id: "status", header: t("stock.col.status"), width: 140 },
]);

const form = reactive({ branch: null as number | null, kind: "full" as CountKind, category: null as number | null });
const saving = ref(false);
watch(creating, (value) => {
  if (value && form.branch === null && company.branchFilter.length === 1) form.branch = company.branchFilter[0] ?? null;
});
const kindOptions = computed(() => (["full", "partial", "handover"] as const).map((value) => ({ value, label: t(`stock.countKind.${value}`) })));
const categoryOptions = computed(() => (categories.data.value ?? []).map((row) => ({ value: row.id, label: row.name })));

async function start(): Promise<void> {
  if (!form.branch) return;
  saving.value = true;
  try {
    const detail = await stockApi.startCount(company.currentId ?? 0, { branch: form.branch, kind: form.kind, category: form.kind === "partial" ? form.category : null });
    toast.success(t("stock.count.startedToast", { n: detail.lines.length }, detail.lines.length));
    refresh();
    creating.value = false;
    void router.push(`/c/${company.currentId}/stock/counts/${detail.count.id}`);
  } catch (error) {
    toast.error(isApiError(error) ? error.message : t("common.error.generic"));
  } finally {
    saving.value = false;
  }
}

function open(row: Count): void {
  void router.push(`/c/${company.currentId}/stock/counts/${row.id}`);
}
</script>

<template>
  <div>
    <PageHeader :title="t('stock.nav.counts')" :description="t('stock.counts.description')">
      <template #actions>
        <UiButton v-if="canStart" variant="primary" :icon="Plus" @click="creating = true">{{ t("stock.counts.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="counts.data.value && !counts.data.value.length" class="ui-card">
      <EmptyState :icon="ClipboardList" :title="t('stock.counts.emptyTitle')" :description="t('stock.counts.emptyBody')">
        <UiButton v-if="canStart" variant="primary" :icon="Plus" @click="creating = true">{{ t("stock.counts.new") }}</UiButton>
      </EmptyState>
    </div>
    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="counts.data.value"
      row-key="id"
      :loading="counts.isPending.value"
      :error="counts.error.value"
      :retry="() => counts.refetch()"
      clickable
      hide-pagination
      csv-name="counts"
      @row-click="open"
    >
      <template #cell-created_at="{ row }">{{ fmt.instant(row.created_at, "short") }}</template>
      <template #cell-kind="{ row }">{{ t(`stock.countKind.${row.kind}`) }}<template v-if="row.category"> · {{ row.category.name }}</template></template>
      <template #cell-progress="{ row }">{{ t("stock.count.progressValue", { counted: row.counted_count, total: row.lines_count }) }}</template>
      <template #cell-value_difference="{ row }">
        <MoneyText v-if="row.value_difference !== null && row.value_difference !== undefined" :value="row.value_difference" sign="always" colored decimals="never" />
        <span v-else class="text-subtle">—</span>
      </template>
      <template #cell-status="{ row }"><StatusPill :tone="COUNT_TONES[row.status]" size="sm" :label="t(`stock.countStatus.${row.status}`)" /></template>
    </DataTable>

    <UiDialog v-model:open="creating" :title="t('stock.counts.newTitle')" :description="t('stock.counts.newDescription')" size="sm">
      <div class="flex flex-col gap-3">
        <FormField :label="t('stock.field.branch')" required>
          <BranchPicker v-model="form.branch" :clearable="false" />
        </FormField>
        <FormField :label="t('stock.count.kind')">
          <SegmentedControl v-model="form.kind" :options="kindOptions" size="sm" block />
        </FormField>
        <FormField v-if="form.kind === 'partial'" :label="t('stock.field.category')" :hint="t('stock.counts.categoryHint')" optional>
          <SelectBox v-model="form.category" :options="categoryOptions" clearable :placeholder="t('stock.counts.everything')" />
        </FormField>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="creating = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :disabled="!form.branch" :loading="saving" @click="start">{{ t("stock.counts.start") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
