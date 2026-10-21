<script setup lang="ts">
/** Balances on a date: cash per account and in total, what was owed both ways, the net position. */
import { HandCoins, Scale, Wallet } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import DatePicker from "@/components/DatePicker.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { todayIn } from "@/lib/dates";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useBalances } from "../../api";
import { ACCOUNT_GROUPS, ACCOUNT_ICONS, isNegative } from "../../lib";

const props = defineProps<{ branch: number[] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));
const on = useRouteState("on", rs.day());
const day = computed({ get: () => on.value ?? today.value, set: (value: string | null) => (on.value = value === today.value ? null : value) });
const params = computed(() => ({ on: day.value, ...(props.branch.length ? { branch: props.branch } : {}) }));
const query = useBalances(params);
const data = computed(() => query.data.value);

const kpis = computed(() => {
  const d = data.value;
  return [
    { id: "cash", label: t("finance.reports.cashOn"), value: d?.total ?? null, format: "money" as const, compact: true, icon: Wallet },
    { id: "receivable", label: t("finance.debts.side.receivable"), value: d?.receivable.total ?? null, format: "money" as const, compact: true, icon: HandCoins, hint: d ? t("finance.overview.debtCount", { n: d.receivable.count }, d.receivable.count) : undefined },
    { id: "payable", label: t("finance.debts.side.payable"), value: d?.payable.total ?? null, format: "money" as const, compact: true, icon: HandCoins, hint: d ? t("finance.overview.debtCount", { n: d.payable.count }, d.payable.count) : undefined },
    { id: "net", label: t("finance.reports.netPosition"), value: d?.net ?? null, format: "money" as const, compact: true, icon: Scale, hint: t("finance.reports.netHint") },
  ];
});
const groups = computed(() =>
  ACCOUNT_GROUPS.map((group) => ({ ...group, rows: (data.value?.accounts ?? []).filter((row) => group.kinds.includes(row.kind)) })).filter((group) => group.rows.length),
);
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <DatePicker v-model="day" :max="today" class="w-56" />
      <span class="text-sm text-muted">{{ t("finance.reports.endOfDay") }}</span>
      <span class="flex-1" />
      <ExportButton kind="finance.balances" :params="params" size="sm" />
    </div>
    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else>
      <KpiStrip :items="kpis" :loading="query.isPending.value" :columns="4" />
      <SkeletonBlock v-if="query.isPending.value" height="320px" radius="12px" />
      <div v-else-if="data" class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section v-for="group in groups" :key="group.id" class="ui-card p-4">
          <h3 class="mb-2 text-sm font-semibold text-fg">{{ t(`finance.accounts.group.${group.id}`) }}</h3>
          <ul class="flex flex-col divide-y divide-line">
            <li v-for="row in group.rows" :key="row.id">
              <RouterLink :to="`/c/${company.currentId}/finance/accounts/${row.id}`" class="flex items-center gap-3 py-2 hover:bg-highlight">
                <component :is="ACCOUNT_ICONS[row.kind]" :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-base text-fg">{{ row.name }}</span>
                  <span class="block truncate text-xs text-muted">{{ row.kind_label }}<template v-if="row.branch"> · {{ row.branch.name }}</template></span>
                </span>
                <span class="text-right">
                  <span :class="['block text-base font-semibold tabular-nums', isNegative(row.balance) ? 'text-danger' : 'text-fg']"><MoneyText :value="row.balance" :currency="row.currency" /></span>
                  <span v-if="row.currency !== company.currency && row.base" class="block text-xs text-muted">≈ <MoneyText :value="row.base" compact /></span>
                </span>
              </RouterLink>
            </li>
          </ul>
        </section>
      </div>
      <p v-if="data?.rate.rate" class="text-xs text-muted">{{ t("finance.reports.valuedAt", { rate: fmt.number(data.rate.rate, 2), date: fmt.day(data.on, "short") }) }}</p>
    </template>
  </div>
</template>
