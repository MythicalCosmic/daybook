<script setup lang="ts">
/**
 * The ledger (plan §6.2 "Transactions"): saved views as tabs, filter chips kept in the URL, a dense
 * table with inline category edits, receipt thumbnails, bulk categorize and void, phone cards, the
 * sums of whatever the filters match, Excel export, and the entry drawer on `?txn=`.
 */
import { ArrowLeftRight, Building2, CircleDot, FolderTree, Landmark, Paperclip, Plus, Receipt, Rows3, Tags, UserRound, Wallet } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import ComboBox from "@/components/ComboBox.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import FilterBar from "@/components/FilterBar.vue";
import { fromQuery, type FilterDef, useUrlFilters } from "@/components/filters";
import MoneyCell from "@/components/MoneyCell.vue";
import MoneyText from "@/components/MoneyText.vue";
import type { SelectOption } from "@/components/options";
import PageHeader from "@/components/PageHeader.vue";
import SavedViewsTabs, { type ViewTab } from "@/components/SavedViewsTabs.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useConfirm } from "@/components/useConfirm";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { paramsDiffer, useSavedViews } from "@/lib/useSavedViews";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { financeApi, searchCounterparties, useAccounts, useCategories, useRefresh, useTransactions } from "../api";
import CategoryCell from "../components/CategoryCell.vue";
import TransactionDrawer from "../components/TransactionDrawer.vue";
import { ACCOUNT_ICONS, categoryOptions, KIND_ICONS, KIND_TONES, STATUS_TONES } from "../lib";
import { openQuickAdd } from "../quickAdd";
import type { Transaction, TransactionKind } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();

const canRecord = computed(() => company.can("finance.record"));
const canManage = computed(() => company.can("finance.manage"));
const branches = computed(() => company.current?.branches ?? []);

// Filters ----------------------------------------------------------------------------------

const accounts = useAccounts(true);
const categories = useCategories();
const KINDS: TransactionKind[] = ["income", "expense", "transfer", "debt_payment", "debt_open", "write_off", "fx", "owner", "opening"];

async function partySource(query: string, signal: AbortSignal): Promise<SelectOption<string>[]> {
  const rows = await searchCounterparties(company.currentId ?? 0, query, signal);
  return rows.map((row) => ({ value: String(row.id), label: row.name, description: row.kind_label }));
}

const defs = computed<FilterDef[]>(() => {
  const list: FilterDef[] = [
    { key: "period", label: t("finance.filter.period"), type: "date-range", params: ["from", "to"], pinned: true },
    { key: "kind", label: t("finance.filter.kind"), type: "multi", icon: Rows3, options: KINDS.map((kind) => ({ value: kind, label: t(`finance.kind.${kind}`) })) },
    {
      key: "account",
      label: t("finance.field.account"),
      type: "multi",
      icon: Wallet,
      options: (accounts.data.value?.accounts ?? []).map((a) => ({ value: String(a.id), label: a.name, description: a.kind_label, icon: ACCOUNT_ICONS[a.kind] })),
    },
    { key: "category", label: t("finance.field.category"), type: "multi", icon: Tags, options: categoryOptions(categories.data.value, null).map((o) => ({ ...o, value: String(o.value) })) },
    { key: "counterparty", label: t("finance.field.counterparty"), type: "select", icon: UserRound, source: partySource },
    {
      key: "status",
      label: t("finance.filter.status"),
      type: "multi",
      icon: CircleDot,
      options: (["posted", "pending", "void", "rejected"] as const).map((status) => ({ value: status, label: t(`finance.status.${status}`) })),
    },
    { key: "has_receipt", label: t("finance.filter.receipt"), type: "boolean", icon: Paperclip, trueLabel: t("finance.filter.withReceipt"), falseLabel: t("finance.filter.withoutReceipt") },
    { key: "amount", label: t("finance.filter.amount"), type: "number-range", params: ["min", "max"] },
  ];
  if (branches.value.length > 1) {
    list.splice(4, 0, { key: "branch", label: t("finance.field.branch"), type: "multi", icon: Building2, options: branches.value.map((b) => ({ value: String(b.id), label: b.name, description: b.code })) });
  }
  return list;
});
const filters = useUrlFilters(defs);
const search = useRouteState("q", rs.string(""));
const table = useDataTable({ id: "finance.transactions", ordering: "-occurred_on", url: true, hidden: branches.value.length > 1 ? [] : ["branch"] });

watch([() => filters.params.value, search], () => table.resetPage(), { deep: true });

const params = computed(() => ({ ...filters.params.value, ...(search.value ? { q: search.value } : {}), ...table.params.value }));
const query = useTransactions(params);
const page = computed(() => query.data.value);
const filtered = computed(() => filters.active.value > 0 || !!search.value);

// Saved views ----------------------------------------------------------------------------------

const views = useSavedViews("finance.transactions");
const BUILTIN: Array<{ id: string; state: Record<string, unknown> }> = [
  { id: "all", state: {} },
  { id: "income", state: { kind: ["income"] } },
  { id: "expense", state: { kind: ["expense"] } },
  { id: "transfer", state: { kind: ["transfer"] } },
  { id: "pending", state: { status: ["pending"] } },
];
const viewId = useRouteState("view", rs.string("all"));
const tabs = computed<ViewTab[]>(() => [...BUILTIN.map((view) => ({ id: view.id, name: t(`finance.tx.view.${view.id}`), builtin: true })), ...views.tabs.value]);
const activeState = computed<Record<string, unknown>>(() => {
  const builtin = BUILTIN.find((view) => view.id === viewId.value);
  if (builtin) return builtin.state;
  return (views.find(Number(viewId.value))?.state as Record<string, unknown>) ?? {};
});
const currentState = computed(() => ({ ...filters.params.value, ...(search.value ? { q: search.value } : {}) }));
const dirty = computed(() => paramsDiffer(currentState.value, activeState.value));

const activeTab = computed<ViewTab["id"]>({
  get: () => (BUILTIN.some((view) => view.id === viewId.value) ? viewId.value : Number(viewId.value) || "all"),
  set: (id) => {
    viewId.value = String(id);
    const state = (BUILTIN.find((view) => view.id === id)?.state ?? views.find(Number(id))?.state ?? {}) as Record<string, string | string[]>;
    filters.values.value = fromQuery(defs.value, state);
    search.value = typeof state.q === "string" ? state.q : "";
  },
});

// A link that names a view alone (`?view=pending`, a bookmark of a saved view) opens it with its
// filters; a link that carries its own filters keeps them. Saved views arrive a moment later, so
// this waits for the view's state once.
let viewApplied = false;
watch(
  activeState,
  (state) => {
    if (viewApplied) return;
    if (!Object.keys(state).length) {
      viewApplied = BUILTIN.some((view) => view.id === viewId.value);
      return;
    }
    viewApplied = true;
    if (!Object.keys(currentState.value).length) activeTab.value = activeTab.value;
  },
  { immediate: true },
);

function saveView(input: { name: string; shared: boolean }): void {
  views.create.mutate(
    { name: input.name, is_shared: input.shared, state: currentState.value },
    { onSuccess: (view) => (viewId.value = String(view.id)) },
  );
}

// Table -----------------------------------------------------------------------------------------

const columns = computed<TableColumn<Transaction>[]>(() => [
  { id: "occurred_on", header: t("finance.field.date"), sortable: true, width: 96, format: (value) => fmt.day(String(value), "short") },
  { id: "description", header: t("finance.tx.what"), minWidth: 220, hideable: false, sticky: true, value: (row) => row.description || row.category?.name || row.kind_label },
  { id: "category", header: t("finance.field.category"), width: 190, value: (row) => row.category?.name ?? "" },
  { id: "account", header: t("finance.field.account"), width: 170, value: (row) => row.account?.name ?? "" },
  { id: "amount", header: t("finance.field.amount"), sortable: true, numeric: true, width: 168, value: (row) => row.amount, csv: (row) => row.amount },
  { id: "receipts", header: "", width: 48, hideable: false, align: "center", value: (row) => row.receipts.length || "", csv: (row) => row.receipts.length },
  { id: "branch", header: t("finance.field.branch"), width: 88, value: (row) => row.branch?.name ?? "" },
  { id: "status", header: t("finance.filter.status"), width: 136, value: (row) => row.status_label, csv: (row) => row.status_label },
]);

function open(row: Transaction): void {
  void router.push({ query: { ...route.query, txn: String(row.id) } });
}

const activeKey = computed(() => (typeof route.query.txn === "string" ? route.query.txn : null));

// Bulk ------------------------------------------------------------------------------------------

const bulkCategory = ref<number | null>(null);
const bulkOpen = ref(false);
const bulkIds = ref<number[]>([]);
const bulkKind = ref<"income" | "expense">("expense");
const bulkChoices = computed(() => categoryOptions(categories.data.value, bulkKind.value, { activeOnly: true }));

function startCategorize(selected: string[]): void {
  bulkIds.value = selected.map(Number);
  const rows = (page.value?.results ?? []).filter((row) => bulkIds.value.includes(row.id));
  bulkKind.value = rows.some((row) => row.kind === "income") && !rows.some((row) => row.kind === "expense") ? "income" : "expense";
  bulkCategory.value = null;
  bulkOpen.value = true;
}

async function applyCategorize(clear: () => void): Promise<void> {
  if (!bulkCategory.value) return;
  const { results } = await financeApi.bulk(company.currentId ?? 0, bulkIds.value, "categorize", { category: bulkCategory.value });
  reportBulk(results);
  bulkOpen.value = false;
  clear();
  refresh();
}

async function bulkVoid(selected: string[], clear: () => void): Promise<void> {
  const answer = await confirm({
    title: t("finance.tx.bulkVoidTitle", { n: selected.length }, selected.length),
    message: t("finance.tx.voidBody"),
    tone: "danger",
    reason: "required",
    reasonLabel: t("finance.tx.voidReason"),
    confirmLabel: t("finance.tx.void"),
  });
  if (!answer) return;
  const { results } = await financeApi.bulk(company.currentId ?? 0, selected.map(Number), "void", { reason: answer.reason });
  reportBulk(results);
  clear();
  refresh();
}

function reportBulk(results: Array<{ ok: boolean; error?: string }>): void {
  const done = results.filter((r) => r.ok).length;
  const skipped = results.length - done;
  if (skipped) toast.warning(t("finance.tx.bulkPartial", { done, skipped }), { description: results.find((r) => !r.ok)?.error });
  else toast.success(t("finance.tx.bulkDone", { n: done }, done));
}

const exportParams = computed(() => ({ ...filters.params.value, ...(search.value ? { q: search.value } : {}) }));
const kindIcon = (kind: TransactionKind) => KIND_ICONS[kind] ?? Receipt;
</script>

<template>
  <div>
    <PageHeader :title="t('finance.nav.transactions')" :description="t('finance.tx.description')">
      <template #actions>
        <UiButton v-if="canRecord" variant="secondary" :icon="ArrowLeftRight" @click="openQuickAdd('transfer')">{{ t("finance.cmd.transferShort") }}</UiButton>
        <UiButton v-if="canRecord" variant="primary" :icon="Plus" kbd="N" @click="openQuickAdd('expense')">{{ t("finance.cmd.record") }}</UiButton>
      </template>
    </PageHeader>

    <div class="flex flex-col gap-3">
      <SavedViewsTabs v-model="activeTab" :views="tabs" :dirty="dirty" @save="saveView" @update="(view) => views.update.mutate({ id: Number(view.id), state: currentState })" @rename="(view, name) => views.update.mutate({ id: Number(view.id), name })" @share="(view, shared) => views.update.mutate({ id: Number(view.id), is_shared: shared })" @delete="(view) => { views.remove.mutate(Number(view.id)); viewId = 'all'; }" />

      <div v-if="page?.summary" class="grid grid-cols-3 gap-2 sm:max-w-[640px]">
        <div class="ui-card px-2.5 py-2 sm:px-3">
          <p class="text-xs font-medium text-muted">{{ t("finance.tx.moneyIn") }}</p>
          <p class="truncate text-sm font-semibold tabular-nums sm:text-md text-success"><MoneyText :value="page.summary.money_in" compact /></p>
        </div>
        <div class="ui-card px-2.5 py-2 sm:px-3">
          <p class="text-xs font-medium text-muted">{{ t("finance.tx.moneyOut") }}</p>
          <p class="truncate text-sm font-semibold tabular-nums sm:text-md text-danger"><MoneyText :value="page.summary.money_out" compact /></p>
        </div>
        <div class="ui-card px-2.5 py-2 sm:px-3">
          <p class="text-xs font-medium text-muted">{{ t("finance.tx.net") }}</p>
          <p class="truncate text-sm font-semibold tabular-nums sm:text-md text-fg"><MoneyText :value="page.summary.net" compact sign="always" /></p>
        </div>
      </div>

      <DataTable
        :state="table"
        :columns="columns"
        :rows="page?.results"
        :total="page?.count"
        row-key="id"
        :loading="query.isPending.value"
        :fetching="query.isFetching.value"
        :error="query.error.value"
        :retry="() => query.refetch()"
        :selectable="canManage"
        clickable
        :active-key="activeKey"
        :filtered="filtered"
        csv-name="ledger"
        export-kind="finance.transactions"
        :export-params="exportParams"
        export-sensitive
        :empty-title="t('finance.tx.emptyTitle')"
        :empty-description="t('finance.tx.emptyBody')"
        :empty-icon="Landmark"
        :row-class="(row) => (row.status === 'void' || row.status === 'rejected' ? 'opacity-55' : undefined)"
        @row-click="open"
        @clear-filters="
          filters.clear();
          search = '';
        "
      >
        <template #toolbar>
          <FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable :search-placeholder="t('finance.tx.searchPlaceholder')" />
        </template>
        <template #actions>
          <ExtensionSlot name="finance.transactions.toolbar" as="none" :context="{ filters: exportParams }" />
        </template>
        <template #empty>
          <EmptyState :icon="Landmark" :title="filtered ? t('finance.tx.noMatch') : t('finance.tx.emptyTitle')" :description="filtered ? t('finance.tx.noMatchBody') : t('finance.tx.emptyBody')">
            <UiButton v-if="filtered" variant="secondary" @click="filters.clear(); search = '';">{{ t("common.filter.clearAll") }}</UiButton>
            <UiButton v-else-if="canRecord" variant="primary" :icon="Plus" @click="openQuickAdd('expense')">{{ t("finance.cmd.record") }}</UiButton>
          </EmptyState>
        </template>

        <template #cell-description="{ row }">
          <div class="flex min-w-0 items-center gap-2.5">
            <span
              :class="[
                'grid size-7 shrink-0 place-items-center rounded-[8px]',
                row.kind === 'income' ? 'bg-success-soft text-success' : row.kind === 'expense' ? 'bg-danger-soft text-danger' : 'bg-surface-2 text-muted',
              ]"
              aria-hidden="true"
            >
              <component :is="kindIcon(row.kind)" :size="14" />
            </span>
            <div class="min-w-0">
              <p class="truncate text-base font-medium text-fg">{{ row.masked ? row.category?.name : row.description || row.category?.name || row.kind_label }}</p>
              <p class="truncate text-xs text-muted">
                <template v-if="row.counterparty">{{ row.counterparty.name }}</template>
                <template v-else-if="row.membership">{{ row.membership.name }}</template>
                <template v-else-if="row.source">{{ row.source.label }}</template>
                <template v-else>{{ row.kind_label }}</template>
              </p>
            </div>
          </div>
        </template>
        <template #cell-category="{ row }"><CategoryCell :row="row" /></template>
        <template #cell-account="{ row }">
          <span v-if="row.account" class="inline-flex min-w-0 items-center gap-1.5 text-sm text-fg">
            <component :is="ACCOUNT_ICONS[row.account.kind]" :size="14" class="shrink-0 text-subtle" aria-hidden="true" />
            <span class="truncate">{{ row.account.name }}</span>
          </span>
          <span v-else class="text-sm text-subtle">{{ t("finance.tx.noAccount") }}</span>
        </template>
        <template #cell-branch="{ row }">
          <span v-if="row.branch" class="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-muted">{{ row.branch.code || row.branch.name }}</span>
        </template>
        <template #cell-receipts="{ row }">
          <span v-if="row.receipts.length" class="relative inline-flex">
            <img v-if="row.receipts[0]?.thumb_url" :src="row.receipts[0].thumb_url" alt="" class="size-7 rounded-[6px] border border-line object-cover" loading="lazy" />
            <Paperclip v-else :size="15" class="text-muted" />
            <span v-if="row.receipts.length > 1" class="absolute -right-1.5 -top-1.5 rounded-full bg-primary px-1 text-[10px] font-bold leading-4 text-on-primary">{{ row.receipts.length }}</span>
          </span>
          <span v-else aria-hidden="true" />
        </template>
        <template #cell-status="{ row }">
          <StatusPill v-if="row.status !== 'posted'" :tone="STATUS_TONES[row.status]" size="sm" :label="row.status_label" />
          <StatusPill v-else-if="!['income', 'expense'].includes(row.kind)" :tone="KIND_TONES[row.kind]" size="sm" variant="plain" :label="t(`finance.kind.${row.kind}`)" />
          <span v-else class="sr-only">{{ row.status_label }}</span>
        </template>
        <template #cell-amount="{ row }">
          <MoneyCell :value="row.amount" :currency="row.currency" sign="always" :approx="row.currency !== company.currency ? { value: row.base_amount, currency: company.currency } : null" :strong="row.kind === 'income' || row.kind === 'expense'" />
        </template>

        <template #bulk="{ selected, clear }">
          <UiButton size="sm" :icon="FolderTree" @click="startCategorize(selected)">{{ t("finance.tx.categorize") }}</UiButton>
          <UiButton size="sm" variant="danger" @click="bulkVoid(selected, clear)">{{ t("finance.tx.void") }}</UiButton>
          <UiDialog v-model:open="bulkOpen" :title="t('finance.tx.categorizeTitle', { n: bulkIds.length }, bulkIds.length)" size="sm">
            <ComboBox v-model="bulkCategory" :options="bulkChoices" :placeholder="t('finance.quick.categoryPlaceholder')" />
            <template #footer>
              <UiButton variant="ghost" @click="bulkOpen = false">{{ t("common.cancel") }}</UiButton>
              <UiButton variant="primary" :disabled="!bulkCategory" @click="applyCategorize(clear)">{{ t("finance.tx.apply") }}</UiButton>
            </template>
          </UiDialog>
        </template>

        <template #card="{ row }">
          <div class="flex items-start gap-3">
            <span :class="['grid size-9 shrink-0 place-items-center rounded-[10px]', row.kind === 'income' ? 'bg-success-soft text-success' : row.kind === 'expense' ? 'bg-danger-soft text-danger' : 'bg-surface-2 text-muted']" aria-hidden="true">
              <component :is="kindIcon(row.kind)" :size="16" />
            </span>
            <div class="min-w-0 flex-1">
              <p class="truncate text-base font-semibold text-fg">{{ row.masked ? row.category?.name : row.description || row.category?.name || row.kind_label }}</p>
              <p class="truncate text-xs text-muted">{{ fmt.day(row.occurred_on, "short") }} · {{ row.category?.name ?? row.kind_label }} · {{ row.account?.name ?? "—" }}</p>
              <div v-if="row.status !== 'posted' || row.receipts.length" class="mt-1 flex items-center gap-1.5">
                <StatusPill v-if="row.status !== 'posted'" :tone="STATUS_TONES[row.status]" size="sm" :label="row.status_label" />
                <span v-if="row.receipts.length" class="inline-flex items-center gap-0.5 text-xs text-muted"><Paperclip :size="12" />{{ row.receipts.length }}</span>
              </div>
            </div>
            <MoneyCell :value="row.amount" :currency="row.currency" sign="always" strong />
          </div>
        </template>
      </DataTable>
    </div>

    <TransactionDrawer />
  </div>
</template>
