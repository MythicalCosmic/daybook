<script setup lang="ts">
/**
 * Nasiya and qarz (plan §6.2 "Debts tabs (owed to us / we owe) with aging bar and record-payment
 * modal"): the total each way with the overdue part, how old it is, and every debt with what is
 * left and how late; filters in the URL; the debt drawer on `?debt=`; `?new=1` opens the form.
 */
import { ArrowDownLeft, ArrowUpRight, CircleDot, HandCoins, Plus, Rows3 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import MoneyCell from "@/components/MoneyCell.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDataTable } from "@/components/useDataTable";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useDebtSummary, useDebts } from "../api";
import AgingBar from "../components/AgingBar.vue";
import DebtDrawer from "../components/DebtDrawer.vue";
import DebtFormDialog from "../components/DebtFormDialog.vue";
import { dayStyle, DEBT_TONES, isZeroMoney, share } from "../lib";
import type { Debt, DebtDirection } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const canRecord = computed(() => company.can("finance.record"));

const direction = useRouteState<DebtDirection>("direction", rs.enum(["receivable", "payable"] as const, "receivable"));
const search = useRouteState("q", rs.string(""));
const defs = computed<FilterDef[]>(() => [
  {
    key: "status",
    label: t("finance.filter.status"),
    type: "multi",
    icon: CircleDot,
    options: (["open", "paid", "written_off", "cancelled"] as const).map((status) => ({ value: status, label: t(`finance.debtStatus.${status}`) })),
  },
  { key: "overdue", label: t("finance.debts.overdueOnly"), type: "boolean", trueLabel: t("finance.debts.overdueYes"), falseLabel: t("finance.debts.overdueNo") },
  {
    key: "kind",
    label: t("finance.debts.kind"),
    type: "multi",
    icon: Rows3,
    options: (["trade", "loan", "advance", "bill", "tax", "salary", "reimbursement", "other"] as const).map((kind) => ({ value: kind, label: t(`finance.debtKind.${kind}`) })),
  },
]);
const filters = useUrlFilters(defs);
const table = useDataTable({ id: "finance.debts", url: true });
watch([() => filters.params.value, search, direction], () => table.resetPage(), { deep: true });

const params = computed(() => ({ direction: direction.value, ...filters.params.value, ...(search.value ? { q: search.value } : {}), ...table.params.value }));
const debts = useDebts(params);
const summary = useDebtSummary();
const side = computed(() => summary.data.value?.[direction.value] ?? null);
const filtered = computed(() => filters.active.value > 0 || !!search.value);

const tabs = computed(() => [
  { id: "receivable", label: t("finance.debts.side.receivable"), icon: ArrowDownLeft, count: summary.data.value?.receivable.count },
  { id: "payable", label: t("finance.debts.side.payable"), icon: ArrowUpRight, count: summary.data.value?.payable.count },
]);

const columns = computed<TableColumn<Debt>[]>(() => [
  { id: "party", header: direction.value === "receivable" ? t("finance.debts.whoOwes") : t("finance.debts.whomWeOwe"), minWidth: 200, sticky: true, hideable: false, value: (row) => row.party?.name ?? "" },
  { id: "kind", header: t("finance.debts.kind"), width: 124, value: (row) => t(`finance.debtKind.${row.kind}`) },
  { id: "issued_on", header: t("finance.debts.issued"), width: 82, format: (value) => fmt.day(String(value), dayStyle(String(value))) },
  { id: "due_on", header: t("finance.debts.due"), width: 136, value: (row) => row.due_on ?? "" },
  { id: "amount", header: t("finance.debts.amount"), numeric: true, width: 136, value: (row) => row.amount },
  { id: "progress", header: t("finance.debts.paid"), width: 112, value: (row) => row.paid },
  { id: "outstanding", header: t("finance.debts.left"), numeric: true, width: 136, value: (row) => row.outstanding },
  { id: "branch", header: t("finance.field.branch"), width: 76, value: (row) => row.branch?.name ?? "" },
  { id: "status", header: t("finance.filter.status"), width: 104, value: (row) => row.status },
]);

function open(row: Debt): void {
  void router.push({ query: { ...route.query, debt: String(row.id) } });
}

const activeKey = computed(() => (typeof route.query.debt === "string" ? route.query.debt : null));
const formOpen = ref(route.query.new === "1");
watch(formOpen, (isOpen) => {
  if (!isOpen && route.query.new) void router.replace({ query: { ...route.query, new: undefined } });
});
const exportParams = computed(() => ({ direction: direction.value, ...filters.params.value }));
</script>

<template>
  <div>
    <PageHeader v-model:tab="direction" :title="t('finance.nav.debts')" :description="t('finance.debts.description')" :tabs="tabs">
      <template #actions>
        <UiButton v-if="canRecord" variant="primary" :icon="Plus" @click="formOpen = true">{{ t("finance.debts.new") }}</UiButton>
      </template>
    </PageHeader>

    <section class="ui-card mb-4 grid grid-cols-1 gap-5 p-4 md:grid-cols-[minmax(0,260px)_1fr] md:p-5" :aria-label="t('finance.debts.summary')">
      <div class="flex flex-col gap-1">
        <p class="text-sm font-medium text-muted">{{ direction === "receivable" ? t("finance.debts.totalIn") : t("finance.debts.totalOut") }}</p>
        <SkeletonBlock v-if="summary.isPending.value" width="180px" height="32px" />
        <p v-else-if="side" class="text-2xl font-semibold tabular-nums text-fg"><MoneyText :value="side.total" decimals="never" /></p>
        <p v-if="side" :class="['text-sm', isZeroMoney(side.overdue) ? 'text-subtle' : direction === 'payable' ? 'text-danger' : 'text-warning']">
          <template v-if="isZeroMoney(side.overdue)">{{ t("finance.overview.nothingOverdue") }}</template>
          <template v-else>{{ t("finance.debts.overdueLine", { amount: fmt.money(side.overdue), n: side.overdue_count }, side.overdue_count) }}</template>
        </p>
      </div>
      <div class="min-w-0">
        <p class="mb-2 text-sm font-medium text-muted">{{ t("finance.aging.title") }}</p>
        <SkeletonBlock v-if="summary.isPending.value" height="56px" />
        <AgingBar v-else :totals="summary.data.value?.aging[direction]" compact />
      </div>
    </section>

    <DataTable
      :state="table"
      :columns="columns"
      :rows="debts.data.value?.results"
      :total="debts.data.value?.count"
      row-key="id"
      :loading="debts.isPending.value"
      :fetching="debts.isFetching.value"
      :error="debts.error.value"
      :retry="() => debts.refetch()"
      clickable
      :active-key="activeKey"
      :filtered="filtered"
      csv-name="debts"
      export-kind="finance.debts"
      :export-params="exportParams"
      export-sensitive
      @row-click="open"
      @clear-filters="
        filters.clear();
        search = '';
      "
    >
      <template #toolbar>
        <FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable :search-placeholder="t('finance.debts.searchPlaceholder')" />
      </template>
      <template #empty>
        <EmptyState :icon="HandCoins" :title="filtered ? t('finance.tx.noMatch') : direction === 'receivable' ? t('finance.debts.emptyIn') : t('finance.debts.emptyOut')" :description="filtered ? t('finance.tx.noMatchBody') : t('finance.debts.emptyBody')">
          <UiButton v-if="!filtered && canRecord" variant="primary" :icon="Plus" @click="formOpen = true">{{ t("finance.debts.new") }}</UiButton>
        </EmptyState>
      </template>
      <template #cell-party="{ row }">
        <div class="flex min-w-0 items-center gap-2.5">
          <UserAvatar :name="row.party?.name ?? '?'" :size="28" shape="rounded" />
          <div class="min-w-0">
            <p class="truncate text-base font-medium text-fg">{{ row.party?.name ?? t("finance.debts.hidden") }}</p>
            <p v-if="row.description" class="truncate text-xs text-muted">{{ row.description }}</p>
          </div>
        </div>
      </template>
      <template #cell-due_on="{ row }">
        <div v-if="row.due_on" class="flex min-w-0 flex-col">
          <span class="text-sm text-fg">{{ fmt.day(row.due_on, dayStyle(row.due_on)) }}</span>
          <span v-if="row.days_overdue" class="truncate text-xs font-semibold text-danger">{{ t("finance.debts.late", { n: row.days_overdue }, row.days_overdue) }}</span>
        </div>
        <span v-else class="text-sm text-subtle">{{ t("finance.debts.noDue") }}</span>
      </template>
      <template #cell-amount="{ row }"><MoneyCell :value="row.amount" :currency="row.currency" :colored="false" /></template>
      <template #cell-progress="{ row }">
        <div class="flex w-full items-center gap-2">
          <ProgressBar :value="share(row.paid, row.amount)" :max="100" size="xs" tone="success" class="min-w-0 flex-1" />
          <span class="w-9 shrink-0 text-right text-xs tabular-nums text-muted">{{ Math.round(share(row.paid, row.amount)) }}%</span>
        </div>
      </template>
      <template #cell-outstanding="{ row }"><MoneyCell :value="row.outstanding" :currency="row.currency" :colored="false" strong /></template>
      <template #cell-branch="{ row }">
        <span v-if="row.branch" class="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-muted">{{ row.branch.code || row.branch.name }}</span>
      </template>
      <template #cell-status="{ row }"><StatusPill :tone="DEBT_TONES[row.status]" size="sm" :label="t(`finance.debtStatus.${row.status}`)" /></template>
      <template #card="{ row }">
        <div class="flex items-start gap-3">
          <UserAvatar :name="row.party?.name ?? '?'" :size="34" shape="rounded" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-base font-semibold text-fg">{{ row.party?.name ?? t("finance.debts.hidden") }}</p>
            <p class="truncate text-xs text-muted">{{ t(`finance.debtKind.${row.kind}`) }} · {{ row.due_on ? fmt.day(row.due_on, dayStyle(row.due_on)) : t("finance.debts.noDue") }}</p>
            <p v-if="row.days_overdue" class="text-xs font-semibold text-danger">{{ t("finance.debts.late", { n: row.days_overdue }, row.days_overdue) }}</p>
          </div>
          <MoneyCell :value="row.outstanding" :currency="row.currency" :colored="false" strong />
        </div>
      </template>
    </DataTable>

    <DebtDrawer />
    <DebtFormDialog v-model:open="formOpen" :direction="direction" />
  </div>
</template>
