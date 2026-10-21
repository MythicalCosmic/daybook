<script setup lang="ts">
/**
 * One account's statement (plan §6.2 "account statement"): the balance now, money in and out over
 * the period, the opening and closing balance, every posted row with the running balance, and the
 * entries still waiting for approval. Rows open the entry drawer.
 */
import { ArrowLeftRight, Plus, Wallet } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import DateRangePicker from "@/components/DateRangePicker.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyCell from "@/components/MoneyCell.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import { useDataTable } from "@/components/useDataTable";
import { useRangeState } from "@/lib/useRangeState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useStatement } from "../api";
import TransactionDrawer from "../components/TransactionDrawer.vue";
import { ACCOUNT_ICONS, colorFor } from "../lib";
import { openQuickAdd } from "../quickAdd";
import type { StatementLine, Transaction } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();

const accountId = computed(() => Number(route.params.accountId));
const period = useRangeState({ preset: "last_30" });
const statement = useStatement(accountId, computed(() => ({ from: period.value.range.from, to: period.value.range.to })));
const data = computed(() => statement.data.value);
const account = computed(() => data.value?.account ?? null);
const table = useDataTable({ id: "finance.statement", pageSize: 200 });

const kpis = computed(() => {
  const d = data.value;
  const currency = d?.account.currency;
  // The period reads left to right: what was there, what came in, what went out, what was left.
  // The balance now shows under the closing one when the period ends before today.
  const endsEarlier = !!d && d.to < d.today;
  return [
    { id: "opening", label: t("finance.accounts.startOf", { date: d ? fmt.day(d.from, "short") : "" }), value: d?.opening ?? null, format: "money" as const, currency, icon: Wallet },
    { id: "in", label: t("finance.tx.moneyIn"), value: d?.money_in ?? null, format: "money" as const, currency },
    { id: "out", label: t("finance.tx.moneyOut"), value: d?.money_out ?? null, format: "money" as const, currency },
    {
      id: "closing",
      label: t("finance.accounts.closing", { date: d ? fmt.day(d.to, "short") : "" }),
      value: d?.closing ?? null,
      format: "money" as const,
      currency,
      hint: d && endsEarlier ? t("finance.accounts.nowHint", { amount: fmt.money(d.account.balance, currency) }) : undefined,
    },
  ];
});

const columns = computed<TableColumn<StatementLine>[]>(() => [
  { id: "occurred_on", header: t("finance.field.date"), width: 108, format: (value) => fmt.day(String(value), "short") },
  { id: "description", header: t("finance.tx.what"), minWidth: 240, sticky: true, value: (row) => row.description || row.category?.name || row.kind_label },
  { id: "category", header: t("finance.field.category"), width: 180, value: (row) => row.category?.name ?? row.kind_label },
  { id: "amount", header: t("finance.field.amount"), numeric: true, width: 160, value: (row) => row.amount },
  { id: "running_balance", header: t("finance.accounts.running"), numeric: true, width: 170, value: (row) => row.running_balance },
]);

function open(row: Transaction): void {
  void router.push({ query: { ...route.query, txn: String(row.id) } });
}
</script>

<template>
  <div>
    <PageHeader :title="account?.name ?? t('finance.accounts.statement')" :back="`/c/${company.currentId}/finance/accounts`" :back-label="t('finance.nav.accounts')" :description="account ? [account.kind_label, account.branch?.name, account.bank_name].filter(Boolean).join(' · ') : undefined">
      <template #actions>
        <UiButton v-if="account?.can_record && account.is_active" variant="secondary" :icon="ArrowLeftRight" @click="openQuickAdd({ mode: 'transfer', account: account.id })">{{ t("finance.cmd.transferShort") }}</UiButton>
        <UiButton v-if="account?.can_record && account.is_active" variant="primary" :icon="Plus" @click="openQuickAdd({ mode: 'expense', account: account.id })">{{ t("finance.cmd.record") }}</UiButton>
      </template>
      <template v-if="account" #meta>
        <span class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold" :style="{ background: `color-mix(in srgb, ${colorFor(account.id, account.color)} 14%, transparent)`, color: colorFor(account.id, account.color) }">
          <component :is="ACCOUNT_ICONS[account.kind]" :size="13" />{{ account.currency }}
        </span>
        <StatusPill v-if="!account.is_active" tone="neutral" size="sm" :label="t('finance.accounts.archivedPill')" />
        <span v-if="account.operators.length" class="text-xs text-muted">{{ t("finance.accounts.operatedBy", { names: account.operators.map((o) => o.name).join(", ") }) }}</span>
      </template>
    </PageHeader>

    <ErrorState v-if="statement.isError.value" :error="statement.error.value" :retry="() => statement.refetch()" />
    <div v-else class="flex flex-col gap-4">
      <div class="flex flex-wrap items-center gap-2">
        <DateRangePicker v-model="period" :compare="false" />
      </div>
      <KpiStrip :items="kpis" :loading="statement.isPending.value" :columns="4" />

      <PageSection v-if="data?.pending.length" :title="t('finance.accounts.pending')" :count="data.pending.length" variant="card">
        <ul class="flex flex-col divide-y divide-line">
          <li v-for="row in data.pending" :key="row.id">
            <button type="button" class="flex w-full items-center gap-3 px-1 py-2.5 text-left hover:bg-highlight" @click="open(row)">
              <StatusPill tone="warning" size="sm" :label="row.status_label" />
              <span class="min-w-0 flex-1 truncate text-base text-fg">{{ row.description || row.category?.name }}</span>
              <span class="text-xs text-muted">{{ row.created_by }} · {{ fmt.day(row.occurred_on, "short") }}</span>
              <MoneyCell :value="row.amount" :currency="row.currency" sign="always" />
            </button>
          </li>
        </ul>
      </PageSection>

      <DataTable
        :state="table"
        :columns="columns"
        :rows="data ? [...data.lines].reverse() : undefined"
        row-key="id"
        :loading="statement.isPending.value"
        :fetching="statement.isFetching.value"
        :error="statement.error.value"
        :retry="() => statement.refetch()"
        clickable
        hide-pagination
        csv-name="statement"
        :empty-title="t('finance.accounts.noRows')"
        :empty-description="t('finance.accounts.noRowsBody')"
        @row-click="open"
      >
        <template #cell-description="{ row }">
          <div class="min-w-0">
            <p class="truncate text-base font-medium text-fg">{{ row.masked ? row.category?.name : row.description || row.category?.name || row.kind_label }}</p>
            <p class="truncate text-xs text-muted">{{ row.counterparty?.name ?? row.membership?.name ?? row.kind_label }}</p>
          </div>
        </template>
        <template #cell-amount="{ row }"><MoneyCell :value="row.amount" :currency="row.currency" sign="always" strong /></template>
        <template #cell-running_balance="{ row }"><MoneyCell :value="row.running_balance" :currency="row.currency" :colored="false" /></template>
        <template #card="{ row }">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="truncate text-base font-semibold text-fg">{{ row.description || row.category?.name || row.kind_label }}</p>
              <p class="text-xs text-muted">{{ fmt.day(row.occurred_on, "short") }} · {{ t("finance.accounts.runningShort") }} {{ fmt.money(row.running_balance, row.currency) }}</p>
            </div>
            <MoneyCell :value="row.amount" :currency="row.currency" sign="always" strong />
          </div>
        </template>
      </DataTable>
    </div>
    <TransactionDrawer />
  </div>
</template>
