<script setup lang="ts">
/**
 * One counterparty (plan §6.1 `finance/counterparties/:id`, "detail ledger"): what they owe us and
 * what we owe them, the money that passed with them, their contacts, and two tabs: their debts
 * (open first) and the ledger entries with them. Actions: edit, record a debt, record an entry.
 */
import { HandCoins, Pencil, Phone, Plus, Send } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyCell from "@/components/MoneyCell.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import { useDataTable } from "@/components/useDataTable";
import { formatPhone } from "@/lib/format";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { usePageTitle } from "@/lib/usePageTitle";
import { useCompanyStore } from "@/stores/company";

import { useCounterparty } from "../api";
import CounterpartyFormDialog from "../components/CounterpartyFormDialog.vue";
import DebtDrawer from "../components/DebtDrawer.vue";
import DebtFormDialog from "../components/DebtFormDialog.vue";
import TransactionDrawer from "../components/TransactionDrawer.vue";
import { dayStyle, DEBT_TONES, isZeroMoney, PARTY_TONES } from "../lib";
import { openQuickAdd } from "../quickAdd";
import type { Debt, Transaction } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const canRecord = computed(() => company.can("finance.record"));

const partyId = computed(() => Number(route.params.partyId));
const query = useCounterparty(partyId);
const detail = computed(() => query.data.value);
const party = computed(() => detail.value?.counterparty ?? null);
// The breadcrumb and the browser tab read the counterparty's name, not "Counterparty".
usePageTitle(() => party.value?.name);
const tab = useRouteState("tab", rs.enum(["debts", "entries"] as const, "debts"));
const editOpen = ref(false);
const debtOpen = ref(false);
const debtTable = useDataTable({ id: "finance.party.debts", pageSize: 200 });
const entryTable = useDataTable({ id: "finance.party.entries", pageSize: 200 });

const kpis = computed(() => {
  const d = detail.value;
  return [
    // Compact like the finance overview's tiles (the exact amount in the tooltip and in the debts
    // below), so they fit the two-column phone grid.
    // "… overdue" only when something is (the API may send "0" as well as "0.00").
    { id: "owes", label: t("finance.parties.owesUs"), value: d?.counterparty.owes_us ?? null, format: "money" as const, compact: true, hint: d && !isZeroMoney(d.counterparty.overdue) ? t("finance.parties.overdueSub", { amount: fmt.money(d.counterparty.overdue, undefined, { compact: true }) }) : undefined },
    { id: "we", label: t("finance.parties.weOwe"), value: d?.counterparty.we_owe ?? null, format: "money" as const, compact: true },
    { id: "income", label: t("finance.parties.incomeTotal"), value: d?.totals.income ?? null, format: "money" as const, compact: true },
    { id: "expense", label: t("finance.parties.expenseTotal"), value: d?.totals.expense ?? null, format: "money" as const, compact: true },
  ];
});

const info = computed<DescriptionItem[]>(() => {
  const p = party.value;
  if (!p) return [];
  const list: DescriptionItem[] = [];
  if (p.phone) list.push({ key: "phone", label: t("finance.parties.phone"), value: formatPhone(p.phone), copy: true });
  if (p.telegram_username) list.push({ key: "telegram", label: t("finance.parties.telegram"), value: `@${p.telegram_username}`, copy: true });
  if (p.tin) list.push({ key: "tin", label: t("finance.parties.tin"), value: p.tin, mono: true, copy: true });
  if (p.contact_person) list.push({ key: "contact", label: t("finance.parties.contact"), value: p.contact_person });
  if (p.address) list.push({ key: "address", label: t("finance.parties.address"), value: p.address, wide: true });
  if (p.default_category) list.push({ key: "category", label: t("finance.parties.defaultCategory"), value: p.default_category.name });
  if (p.credit_limit) list.push({ key: "limit", label: t("finance.parties.creditLimit"), value: fmt.money(p.credit_limit) });
  if (p.bank_details) list.push({ key: "bank", label: t("finance.parties.bankDetails"), value: p.bank_details, wide: true });
  if (p.notes) list.push({ key: "notes", label: t("finance.parties.notes"), value: p.notes, wide: true });
  return list;
});

const debtColumns = computed<TableColumn<Debt>[]>(() => [
  { id: "direction", header: t("finance.debts.direction"), width: 120, value: (row) => row.direction_label },
  { id: "kind", header: t("finance.debts.kind"), width: 130, value: (row) => t(`finance.debtKind.${row.kind}`) },
  { id: "issued_on", header: t("finance.debts.issued"), width: 96, format: (value) => fmt.day(String(value), dayStyle(String(value))) },
  { id: "due_on", header: t("finance.debts.due"), width: 130, format: (value) => (value ? fmt.day(String(value), dayStyle(String(value))) : "—") },
  { id: "outstanding", header: t("finance.debts.left"), numeric: true, minWidth: 130 },
  { id: "status", header: t("finance.filter.status"), width: 110 },
]);
const entryColumns = computed<TableColumn<Transaction>[]>(() => [
  { id: "occurred_on", header: t("finance.field.date"), width: 108, format: (value) => fmt.day(String(value), dayStyle(String(value))) },
  { id: "description", header: t("finance.tx.what"), minWidth: 220, value: (row) => row.description || row.category?.name || row.kind_label },
  { id: "category", header: t("finance.field.category"), width: 180, value: (row) => row.category?.name ?? row.kind_label },
  { id: "account", header: t("finance.field.account"), width: 170, value: (row) => row.account?.name ?? "—" },
  { id: "amount", header: t("finance.field.amount"), numeric: true, width: 160 },
]);

function openDebt(row: Debt): void {
  void router.push({ query: { ...route.query, debt: String(row.id) } });
}
function openEntry(row: Transaction): void {
  void router.push({ query: { ...route.query, txn: String(row.id) } });
}
const tabs = computed(() => [
  { id: "debts", label: t("finance.nav.debts"), count: detail.value?.debts.length },
  { id: "entries", label: t("finance.parties.entries"), count: detail.value?.transactions.length },
]);
</script>

<template>
  <div>
    <PageHeader
      v-model:tab="tab"
      :title="party?.name ?? t('finance.parties.detail')"
      :back="`/c/${company.currentId}/finance/counterparties`"
      :back-label="t('finance.nav.counterparties')"
      :tabs="tabs"
    >
      <template #actions>
        <UiButton v-if="party?.phone" :href="`tel:${party.phone}`" variant="ghost" :icon="Phone">{{ t("finance.parties.call") }}</UiButton>
        <UiButton v-if="party?.telegram_username" :href="`https://t.me/${party?.telegram_username}`" target="_blank" variant="ghost" :icon="Send">Telegram</UiButton>
        <UiButton v-if="canRecord" variant="secondary" :icon="Pencil" @click="editOpen = true">{{ t("common.edit") }}</UiButton>
        <UiButton v-if="canRecord" variant="secondary" :icon="HandCoins" @click="debtOpen = true">{{ t("finance.debts.new") }}</UiButton>
        <UiButton v-if="canRecord && party" variant="primary" :icon="Plus" @click="openQuickAdd({ mode: party.kind === 'customer' ? 'income' : 'expense', counterparty: { id: party.id, name: party.name } })">
          {{ t("finance.cmd.record") }}
        </UiButton>
      </template>
      <template v-if="party" #meta>
        <StatusPill :tone="PARTY_TONES[party.kind]" size="sm" :label="party.kind_label" />
        <StatusPill v-if="party.credit_blocked" tone="danger" size="sm" :label="t('finance.parties.blockedPill')" />
        <span v-for="tag in party.tags" :key="tag" class="rounded-full bg-surface-2 px-2 py-0.5 text-xs text-muted">{{ tag }}</span>
      </template>
    </PageHeader>

    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else class="flex flex-col gap-4">
      <KpiStrip :items="kpis" :loading="query.isPending.value" :columns="4" />
      <div class="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div class="min-w-0 xl:order-1">
          <DataTable
            v-if="tab === 'debts'"
            :state="debtTable"
            :columns="debtColumns"
            :rows="detail?.debts"
            row-key="id"
            :loading="query.isPending.value"
            clickable
            hide-pagination
            :empty-title="t('finance.parties.noDebts')"
            :empty-icon="HandCoins"
            @row-click="openDebt"
          >
            <template #cell-direction="{ row }">
              <span :class="['text-sm font-medium', row.direction === 'receivable' ? 'text-success' : 'text-danger']">{{ row.direction_label }}</span>
            </template>
            <template #cell-due_on="{ row }">
              <div v-if="row.due_on" class="flex min-w-0 flex-col">
                <span class="text-sm text-fg">{{ fmt.day(row.due_on, dayStyle(row.due_on)) }}</span>
                <span v-if="row.days_overdue" class="truncate text-xs font-semibold text-danger">{{ t("finance.debts.late", { n: row.days_overdue }, row.days_overdue) }}</span>
              </div>
              <span v-else class="text-sm text-subtle">{{ t("finance.debts.noDue") }}</span>
            </template>
            <template #cell-outstanding="{ row }"><MoneyCell :value="row.outstanding" :currency="row.currency" :colored="false" strong /></template>
            <template #cell-status="{ row }"><StatusPill :tone="DEBT_TONES[row.status]" size="sm" :label="t(`finance.debtStatus.${row.status}`)" /></template>
            <!-- Phones: one card per debt, with what is left and how late, instead of a sideways table. -->
            <template #card="{ row }">
              <div class="flex items-start justify-between gap-3" data-testid="party-debt-card">
                <div class="min-w-0">
                  <p :class="['text-sm font-semibold', row.direction === 'receivable' ? 'text-success' : 'text-danger']">{{ row.direction_label }}</p>
                  <p class="truncate text-xs text-muted">
                    {{ t(`finance.debtKind.${row.kind}`) }} · {{ fmt.day(row.issued_on, dayStyle(row.issued_on)) }}
                    <template v-if="row.due_on"> → {{ fmt.day(row.due_on, dayStyle(row.due_on)) }}</template>
                  </p>
                  <p v-if="row.days_overdue" class="mt-0.5 text-xs font-semibold text-danger">{{ t("finance.debts.late", { n: row.days_overdue }, row.days_overdue) }}</p>
                </div>
                <div class="flex shrink-0 flex-col items-end gap-1">
                  <MoneyCell :value="row.outstanding" :currency="row.currency" :colored="false" strong />
                  <StatusPill :tone="DEBT_TONES[row.status]" size="sm" :label="t(`finance.debtStatus.${row.status}`)" />
                </div>
              </div>
            </template>
          </DataTable>
          <DataTable
            v-else
            :state="entryTable"
            :columns="entryColumns"
            :rows="detail?.transactions"
            row-key="id"
            :loading="query.isPending.value"
            clickable
            hide-pagination
            :empty-title="t('finance.parties.noEntries')"
            @row-click="openEntry"
          >
            <template #cell-amount="{ row }"><MoneyCell :value="row.amount" :currency="row.currency" sign="always" /></template>
            <template #card="{ row }">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <p class="truncate text-sm font-semibold text-fg">{{ row.description || row.category?.name || row.kind_label }}</p>
                  <p class="truncate text-xs text-muted">{{ fmt.day(row.occurred_on, dayStyle(row.occurred_on)) }} · {{ row.category?.name ?? row.kind_label }} · {{ row.account?.name ?? "—" }}</p>
                </div>
                <MoneyCell :value="row.amount" :currency="row.currency" sign="always" strong />
              </div>
            </template>
          </DataTable>
        </div>
        <aside class="ui-card h-fit p-4 xl:order-2">
          <h2 class="mb-3 text-sm font-semibold text-fg">{{ t("finance.parties.about") }}</h2>
          <!-- Notes, the address and bank details are read whole, on as many lines as they need. -->
          <DescriptionList v-if="info.length" :items="info" :columns="1" layout="rows">
            <template #value-notes="{ item }"><span class="min-w-0 whitespace-pre-line break-words text-left" data-testid="party-notes">{{ item.value }}</span></template>
            <template #value-address="{ item }"><span class="min-w-0 break-words text-left">{{ item.value }}</span></template>
            <template #value-bank="{ item }"><span class="min-w-0 whitespace-pre-line break-words text-left">{{ item.value }}</span></template>
          </DescriptionList>
          <p v-else class="text-sm text-muted">{{ t("finance.parties.noDetails") }}</p>
        </aside>
      </div>
    </div>

    <CounterpartyFormDialog v-model:open="editOpen" :party="party" />
    <DebtFormDialog v-model:open="debtOpen" :direction="party?.kind === 'supplier' ? 'payable' : 'receivable'" :counterparty="party ? { id: party.id, name: party.name } : null" />
    <DebtDrawer />
    <TransactionDrawer />
  </div>
</template>
