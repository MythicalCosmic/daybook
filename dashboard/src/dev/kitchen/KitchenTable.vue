<script setup lang="ts">
/**
 * Kitchen: a transactions list as a module would build it: saved views, filter chips, a DataTable
 * of 200 rows with server-style paging, sorting and selection, a bulk bar and a phone card layout.
 * The "server" here is a computed that filters, sorts and pages the demo rows.
 */
import { Building2, CircleDot, Tags, UserRound, Wallet } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DataTable from "@/components/DataTable.vue";
import FilterBar from "@/components/FilterBar.vue";
import { isEmptyValue, type FilterDef, type FilterValues } from "@/components/filters";
import MoneyCell from "@/components/MoneyCell.vue";
import PersonCell from "@/components/PersonCell.vue";
import SavedViewsTabs, { type ViewTab } from "@/components/SavedViewsTabs.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { moneySign } from "@/lib/money";
import { useCompanyStore } from "@/stores/company";

import KitchenSection from "./KitchenSection.vue";
import KitchenSpecimen from "./KitchenSpecimen.vue";
import { BRANCHES, PEOPLE, transactions, type DemoTransaction } from "./kitchenData";

const { t } = useI18n();
const k = (key: string, params?: Record<string, unknown>) => t(`dev.kitchen.${key}`, params ?? {});
const fmt = useFormat();
const company = useCompanyStore();

const all = transactions(200, todayIn(company.timezone));
const table = useDataTable({ id: "kitchen.transactions", ordering: "-date", pageSize: 200, pageSizes: [25, 50, 100, 200] });

const defs = computed<FilterDef[]>(() => [
  {
    key: "status",
    label: k("statusLabel"),
    type: "multi",
    icon: CircleDot,
    options: [
      { value: "posted", label: k("txn.posted"), color: "var(--c-success)" },
      { value: "pending", label: k("txn.pending"), color: "var(--c-warning)" },
      { value: "void", label: k("txn.void"), color: "var(--c-subtle)" },
    ],
  },
  { key: "category", label: k("category"), type: "multi", icon: Tags, options: [...new Set(all.map((row) => row.category))].map((c) => ({ value: c, label: c })) },
  { key: "branch", label: k("branch"), type: "select", icon: Building2, options: BRANCHES.map((b) => ({ value: b.name, label: b.name, description: b.code })) },
  { key: "person", label: k("recordedBy"), type: "select", icon: UserRound, options: PEOPLE.map((p) => ({ value: String(p.id), label: p.name, avatar: { name: p.name } })) },
  { key: "income", label: k("direction"), type: "boolean", icon: Wallet, trueLabel: k("income"), falseLabel: k("expenses") },
  { key: "date", label: k("date"), type: "date-range" },
]);
const filters = ref<FilterValues>({ status: ["posted", "pending"] });
const search = ref("");

const BUILTIN: ViewTab[] = [
  { id: "all", name: k("view.all"), builtin: true },
  { id: "pending", name: k("view.pending"), builtin: true },
  { id: "big", name: k("view.big"), builtin: true },
];
const custom = ref<ViewTab[]>([{ id: 101, name: k("view.supplies"), mine: true, shared: true }]);
const view = ref<ViewTab["id"]>("all");
const views = computed(() => [...BUILTIN, ...custom.value].map((v) => ({ ...v, count: v.id === "pending" ? all.filter((r) => r.status === "pending").length : undefined })));

watch(view, (id) => {
  if (id === "pending") filters.value = { status: ["pending"] };
  else if (id === "all") filters.value = { status: ["posted", "pending"] };
  else if (id === 101) filters.value = { category: ["Supplies"] };
  else filters.value = {};
});
watch([filters, search], () => table.resetPage(), { deep: true });

const filtered = computed(() => {
  const f = filters.value;
  const q = search.value.trim().toLowerCase();
  return all.filter((row) => {
    if (q && !`${row.description} ${row.person.name}`.toLowerCase().includes(q)) return false;
    if (Array.isArray(f.status) && f.status.length && !f.status.includes(row.status)) return false;
    if (Array.isArray(f.category) && f.category.length && !f.category.includes(row.category)) return false;
    if (typeof f.branch === "string" && f.branch && row.branch !== f.branch) return false;
    if (typeof f.person === "string" && f.person && String(row.person.id) !== f.person) return false;
    if (typeof f.income === "boolean" && f.income !== moneySign(row.amount) > 0) return false;
    const range = f.date;
    if (range && typeof range === "object" && !Array.isArray(range)) {
      if (range.from && row.date < range.from) return false;
      if (range.to && row.date > range.to) return false;
    }
    if (view.value === "big") return Math.abs(Number(row.amount)) >= 2_000_000;
    return true;
  });
});

const page = computed(() => {
  const ordering = table.ordering.value || "-date";
  const desc = ordering.startsWith("-");
  const field = ordering.replace(/^-/, "") as keyof DemoTransaction | "amount";
  const sorted = [...filtered.value].sort((a, b) => {
    const left = field === "amount" ? Number(a.amount) : String(a[field as keyof DemoTransaction]);
    const right = field === "amount" ? Number(b.amount) : String(b[field as keyof DemoTransaction]);
    return (left < right ? -1 : left > right ? 1 : 0) * (desc ? -1 : 1);
  });
  const start = (table.page.value - 1) * table.pageSize.value;
  return sorted.slice(start, start + table.pageSize.value);
});

const tones = { posted: "success", pending: "warning", void: "neutral" } as const;
const columns = computed<TableColumn<DemoTransaction>[]>(() => [
  { id: "date", header: k("date"), sortable: true, width: 116, format: (v) => fmt.day(String(v), "short") },
  { id: "description", header: k("description"), sortable: true, minWidth: 220, hideable: false, sticky: true },
  { id: "person", header: k("recordedBy"), width: 210, value: (row) => row.person.name },
  { id: "category", header: k("category"), sortable: true, width: 130 },
  { id: "branch", header: k("branch"), width: 120 },
  { id: "status", header: k("statusLabel"), width: 120 },
  { id: "amount", header: k("amount"), sortable: true, numeric: true, width: 160, csv: (row) => row.amount },
]);
const active = computed(() => Object.values(filters.value).some((v) => !isEmptyValue(v ?? null)) || !!search.value);
const activeRow = ref<number | null>(null);

function open(row: DemoTransaction): void {
  activeRow.value = row.id;
  toast.info(row.description, { description: fmt.money(row.amount) });
}
</script>

<template>
  <KitchenSection id="table" :title="k('section.table')" :description="k('section.tableHint')">
    <KitchenSpecimen name="SavedViewsTabs.vue · FilterBar.vue · DataTable.vue · BulkActionBar.vue" :note="k('tableNote')" wide>
      <div class="flex flex-col gap-3">
        <SavedViewsTabs
          v-model="view"
          :views="views"
          :dirty="view === 'all' && JSON.stringify(filters.status) !== JSON.stringify(['posted', 'pending'])"
          @save="(input) => (custom = [...custom, { id: Date.now(), name: input.name, shared: input.shared, mine: true }])"
          @rename="(target, name) => (custom = custom.map((v) => (v.id === target.id ? { ...v, name } : v)))"
          @share="(target, shared) => (custom = custom.map((v) => (v.id === target.id ? { ...v, shared } : v)))"
          @delete="(target) => ((custom = custom.filter((v) => v.id !== target.id)), (view = 'all'))"
        />
        <DataTable
          :state="table"
          :columns="columns"
          :rows="page"
          :total="filtered.length"
          row-key="id"
          selectable
          clickable
          :active-key="activeRow"
          :filtered="active"
          max-height="560px"
          export-kind="finance.transactions"
          :export-params="filters"
          csv-name="Transactions"
          :row-class="(row) => (row.status === 'void' ? 'opacity-55' : undefined)"
          @row-click="open"
          @clear-filters="
            filters = {};
            search = '';
          "
        >
          <template #toolbar>
            <FilterBar v-model="filters" v-model:search="search" :defs="defs" searchable />
          </template>
          <template #cell-person="{ row }">
            <PersonCell :person="row.person" size="sm" />
          </template>
          <template #cell-status="{ row }">
            <StatusPill :tone="tones[row.status]" size="sm" :label="k(`txn.${row.status}`)" />
          </template>
          <template #cell-amount="{ row }">
            <MoneyCell :value="row.amount" sign="always" />
          </template>
          <template #bulk="{ selected, clear }">
            <UiButton size="sm" @click="toast.success(k('bulkDone', { n: selected.length }))">{{ k("categorize") }}</UiButton>
            <UiButton size="sm" variant="primary" @click="clear">{{ k("approveAll") }}</UiButton>
          </template>
          <template #card="{ row }">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="truncate text-base font-semibold text-fg">{{ row.description }}</p>
                <p class="truncate text-xs text-muted">{{ fmt.day(row.date, "short") }} · {{ row.category }} · {{ row.branch }}</p>
              </div>
              <MoneyCell :value="row.amount" sign="always" />
            </div>
          </template>
        </DataTable>
      </div>
    </KitchenSpecimen>
  </KitchenSection>
</template>
