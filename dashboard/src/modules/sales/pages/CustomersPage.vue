<script setup lang="ts">
/**
 * Customers (plan §11.4): regulars who take nasiya, clinics, other pharmacies and companies,
 * with what each owes, the receivables by age across all of them (not due yet, 0–30, 31–60, more
 * than 60 days) and, per customer, their receivables, nasiya at the tills and receipts.
 */
import { Plus, UsersRound } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import DataTable from "@/components/DataTable.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import FormField from "@/components/FormField.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { salesApi, useAging, useCustomer, useCustomers, useSalesMutation } from "../api";
import type { AgingKey, Customer, CustomerKind } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const canManage = computed(() => company.can("sales.manage"));
const aging = useAging();
const KINDS: CustomerKind[] = ["person", "clinic", "pharmacy", "company"];
const BUCKETS: AgingKey[] = ["not_due", "d0_30", "d31_60", "d60_plus"];

const defs = computed<FilterDef[]>(() => [
  { key: "kind", label: t("sales.customers.kind"), type: "select", options: KINDS.map((kind) => ({ value: kind, label: t(`sales.customers.kinds.${kind}`) })) },
  { key: "owing", label: t("sales.customers.owing"), type: "boolean" },
]);
const filters = useUrlFilters(defs);
const search = useRouteState<string>("q", rs.string(""));
const opened = useRouteState<number | null>("customer", rs.optionalNumber());
const table = useDataTable({ id: "sales.customers", url: true });
table.resetPageOn(() => [filters.params.value, search.value]);
const query = useCustomers(computed(() => ({ ...filters.params.value, ...(search.value ? { q: search.value } : {}), ...table.params.value })));
const detail = useCustomer(opened);

const kpis = computed(() => {
  const data = aging.data.value;
  if (!data) return [];
  return [
    { id: "total", label: t("sales.customers.owedTotal"), value: data.total, format: "money" as const },
    ...BUCKETS.map((key) => ({ id: key, label: t(`sales.customers.aging.${key}`), value: data.totals[key], format: "money" as const })),
  ];
});

const columns = computed<TableColumn<Customer>[]>(() => [
  { id: "name", header: t("sales.customers.name"), minWidth: 220, hideable: false },
  { id: "phone", header: t("sales.customers.phone"), width: 160 },
  { id: "credit_limit", header: t("sales.customers.limit"), width: 150, numeric: true, csv: (row) => row.credit_limit ?? "" },
  { id: "owed", header: t("sales.customers.owed"), width: 150, numeric: true, csv: (row) => row.owed },
]);

const drawer = computed({ get: () => opened.value !== null, set: (value: boolean) => !value && (opened.value = null) });

// A new customer ------------------------------------------------------------------------------
const creating = ref(false);
const form = ref({ name: "", phone: "", kind: "person" as CustomerKind, credit_limit: null as string | null });
const create = useSalesMutation((cid, input: typeof form.value) => salesApi.createCustomer(cid, input));
async function submit(): Promise<void> {
  const made = await create.mutateAsync({ ...form.value, name: form.value.name.trim() });
  toast.success(t("sales.customers.created"));
  creating.value = false;
  form.value = { name: "", phone: "", kind: "person", credit_limit: null };
  opened.value = made.id;
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader :title="t('sales.customers.title')" :description="t('sales.customers.description')" class="!mb-0">
      <template v-if="canManage" #actions>
        <UiButton variant="primary" :icon="Plus" @click="creating = true">{{ t("sales.customers.new") }}</UiButton>
      </template>
    </PageHeader>
    <KpiStrip :items="kpis" :loading="aging.isPending.value" :columns="5" phone="grid" />
    <DataTable
      :state="table"
      :columns="columns"
      :rows="query.data.value?.results"
      :total="query.data.value?.count"
      row-key="id"
      clickable
      :loading="query.isPending.value"
      :fetching="query.isFetching.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      :filtered="filters.active.value > 0 || !!search"
      :empty-title="t('sales.customers.emptyTitle')"
      :empty-description="t('sales.customers.emptyBody')"
      :empty-icon="UsersRound"
      csv-name="customers"
      @row-click="(row: Customer) => (opened = row.id)"
      @clear-filters="(filters.clear(), (search = ''))"
    >
      <template #toolbar><FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable /></template>
      <template #cell-name="{ row }">
        <span class="flex min-w-0 items-center gap-2">
          <span class="truncate font-medium text-fg">{{ row.name }}</span>
          <StatusPill size="sm" tone="neutral" :dot="false" :label="t(`sales.customers.kinds.${row.kind}`)" />
          <StatusPill v-if="row.credit_blocked" size="sm" tone="danger" :label="t('sales.customers.blocked')" />
        </span>
      </template>
      <template #cell-credit_limit="{ row }">
        <MoneyText v-if="row.credit_limit" :value="row.credit_limit" class="tabular-nums text-muted" />
        <span v-else class="text-subtle">—</span>
      </template>
      <template #cell-owed="{ row }">
        <span :class="['font-semibold tabular-nums', Number(row.owed) > 0 ? 'text-fg' : 'text-subtle']"><MoneyText :value="row.owed" /></span>
      </template>
    </DataTable>

    <UiDrawer v-model:open="drawer" size="lg" :title="detail.data.value?.name ?? t('sales.customers.title')" :description="detail.data.value ? t(`sales.customers.kinds.${detail.data.value.kind}`) : undefined">
      <div v-if="detail.data.value" class="flex flex-col gap-4 p-5 max-sm:p-4">
        <div class="grid gap-3 sm:grid-cols-5">
          <div class="rounded-xl border border-line p-3">
            <p class="text-xs text-muted">{{ t("sales.customers.owed") }}</p>
            <p class="text-lg font-semibold tabular-nums text-fg"><MoneyText :value="detail.data.value.owed" /></p>
          </div>
          <div v-for="key in BUCKETS" :key="key" class="rounded-xl border border-line p-3">
            <p class="text-xs text-muted">{{ t(`sales.customers.aging.${key}`) }}</p>
            <p :class="['text-md tabular-nums', key === 'd60_plus' && Number(detail.data.value.aging[key]) > 0 ? 'font-semibold text-danger' : 'text-fg']"><MoneyText :value="detail.data.value.aging[key]" /></p>
          </div>
        </div>
        <p class="text-sm text-muted">{{ [detail.data.value.phone, detail.data.value.tin, detail.data.value.address].filter(Boolean).join(" · ") || "—" }}</p>
        <section>
          <h3 class="mb-2 text-sm font-semibold text-fg">{{ t("sales.customers.debts") }}</h3>
          <p v-if="!detail.data.value.debts.length" class="text-sm text-muted">{{ t("sales.customers.noDebts") }}</p>
          <ul v-else class="flex flex-col divide-y divide-line rounded-xl border border-line">
            <li v-for="debt in detail.data.value.debts" :key="debt.id" class="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <span class="min-w-0">
                <span class="block truncate text-fg">{{ debt.description || t(`sales.customers.source.${debt.source === "sales.invoice" ? "invoice" : "nasiya"}`) }}</span>
                <span class="block text-xs text-muted">{{ fmt.day(debt.issued_on) }}<template v-if="debt.due_on"> · {{ t("sales.customers.due", { day: fmt.day(debt.due_on) }) }}</template></span>
              </span>
              <span class="flex shrink-0 items-center gap-2">
                <StatusPill v-if="debt.overdue" size="sm" tone="danger" :label="t('sales.customers.overdue')" />
                <StatusPill v-else-if="debt.status !== 'open'" size="sm" tone="success" :label="t('sales.customers.settled')" />
                <span class="tabular-nums font-semibold text-fg"><MoneyText :value="debt.left" :currency="debt.currency" /></span>
              </span>
            </li>
          </ul>
        </section>
        <section v-if="detail.data.value.credit.length">
          <h3 class="mb-2 text-sm font-semibold text-fg">{{ t("sales.customers.nasiya") }}</h3>
          <ul class="flex flex-col divide-y divide-line rounded-xl border border-line">
            <li v-for="entry in detail.data.value.credit" :key="entry.id" :class="['flex items-center justify-between gap-3 px-3 py-2 text-sm', entry.voided_at && 'opacity-55']">
              <span class="min-w-0">
                <span class="block text-fg">{{ t(`sales.customers.entry.${entry.kind}`) }}<template v-if="entry.note"> · {{ entry.note }}</template></span>
                <span class="block text-xs text-muted">{{ fmt.day(entry.business_day) }} · {{ entry.branch.name }}<template v-if="entry.by"> · {{ entry.by.name }}</template></span>
              </span>
              <span :class="['shrink-0 tabular-nums', entry.kind === 'payment' ? 'text-success' : 'text-fg']">{{ entry.kind === "payment" ? "−" : "" }}<MoneyText :value="entry.amount" /></span>
            </li>
          </ul>
        </section>
      </div>
    </UiDrawer>

    <UiDialog v-model:open="creating" :title="t('sales.customers.newTitle')" size="md">
      <div class="flex flex-col gap-4">
        <FormField :label="t('sales.customers.name')" required><TextInput v-model="form.name" :maxlength="200" /></FormField>
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="t('sales.customers.phone')"><TextInput v-model="form.phone" :maxlength="20" placeholder="+998 90 123 45 67" /></FormField>
          <FormField :label="t('sales.customers.kind')"><SelectBox v-model="form.kind" :options="KINDS.map((kind) => ({ value: kind, label: t(`sales.customers.kinds.${kind}`) }))" /></FormField>
        </div>
        <FormField :label="t('sales.customers.limit')" :hint="t('sales.customers.limitHint')" optional><MoneyInput v-model="form.credit_limit" /></FormField>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="creating = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :disabled="!form.name.trim()" :loading="create.isPending.value" @click="submit">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
