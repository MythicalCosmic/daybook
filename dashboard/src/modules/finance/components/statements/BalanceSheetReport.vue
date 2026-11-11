<script setup lang="ts">
/**
 * The balance sheet on a day (v12, `reports/balance-sheet/`): what the business owns on the left,
 * what it owes and the owners' part on the right, always in balance; then what the business is
 * worth, how retained earnings are made from the books and, plainly, what the books leave out.
 * "Prepare a report" makes the PDF for a bank, a partner or a buyer.
 */
import { CircleCheck, Landmark, Scale, TriangleAlert, Wallet } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DatePicker from "@/components/DatePicker.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { compare } from "@/lib/decimal";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useBalanceSheet, type BalanceSheet, type SheetGap } from "../../statements";
import PrepareReportButton from "./PrepareReportButton.vue";
import ValuationCard from "./ValuationCard.vue";

const props = defineProps<{ branch: number[] }>();

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const fmt = useFormat();
function dropPrepare(): void {
  const rest = { ...route.query };
  delete rest.prepare;
  void router.replace({ query: rest });
}
const company = useCompanyStore();
const today = useCompanyToday();
const on = useRouteState("on", rs.day());
const day = computed({ get: () => on.value ?? today.value, set: (value: string | null) => (on.value = value === today.value ? null : value) });
const params = computed(() => ({ on: day.value, ...(props.branch.length ? { branch: props.branch } : {}) }));
const query = useBalanceSheet(params);
const data = computed<BalanceSheet | undefined>(() => query.data.value);

const ratio = computed(() => {
  const d = data.value;
  if (!d || compare(d.current_liabilities, 0) <= 0) return null;
  return Number(d.current_assets) / Number(d.current_liabilities);
});
const kpis = computed(() => {
  const d = data.value;
  return [
    { id: "assets", label: t("finance.sheet.totalAssets"), value: d?.assets.total ?? null, format: "money" as const, compact: true, icon: Wallet },
    { id: "liabilities", label: t("finance.sheet.totalLiabilities"), value: d?.liabilities.total ?? null, format: "money" as const, compact: true, icon: Landmark },
    {
      id: "equity",
      label: d && !d.whole_company ? t("finance.sheet.branchNetAssets") : t("finance.sheet.equity"),
      value: d?.equity.total ?? null,
      format: "money" as const,
      compact: true,
      icon: Scale,
    },
    {
      id: "ratio",
      label: t("finance.sheet.currentRatio"),
      value: ratio.value,
      format: (value: number) => `${fmt.number(value, 1)}×`,
      hint: t("finance.sheet.currentRatioHint"),
    },
  ];
});

function gapText(gap: SheetGap): string {
  const p = gap.params;
  switch (gap.key) {
    case "no_opening":
      return t("finance.sheet.gap.no_opening", { day: fmt.day(String(p.day), "medium") });
    case "no_rate":
      return t("finance.sheet.gap.no_rate", { currencies: (p.currencies as string[]).join(", ") });
    case "negative_account":
      return t("finance.sheet.gap.negative_account", { account: String(p.account) });
    case "pending":
      return t("finance.sheet.gap.pending", { n: Number(p.count), amount: fmt.money(String(p.amount)) }, Number(p.count));
    case "unexplained":
      return t("finance.sheet.gap.unexplained", { amount: fmt.money(String(p.amount)) });
    case "no_assets_module":
      return compare(String(p.equipment ?? "0"), 0) > 0 ? t("finance.sheet.gap.no_assets_equipment", { amount: fmt.money(String(p.equipment)) }) : t("finance.sheet.gap.no_assets_module");
    default:
      return t(`finance.sheet.gap.${gap.key}`);
  }
}
const lineName = (key: string) => t(`finance.sheet.line.${key}`);
const sectionName = (key: string) => t(`finance.sheet.section.${key}`);
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <DatePicker v-model="day" :max="today" class="w-56" />
      <span class="text-sm text-muted">{{ t("finance.reports.endOfDay") }}</span>
      <span class="flex-1" />
      <ExportButton kind="finance.balance_sheet" :params="params" size="sm" />
      <PrepareReportButton size="sm" :auto-open="route.query.prepare === '1'" @opened="dropPrepare" />
    </div>
    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else>
      <KpiStrip :items="kpis" :loading="query.isPending.value" :columns="4" phone="grid" />
      <SkeletonBlock v-if="query.isPending.value" height="420px" radius="12px" />
      <template v-else-if="data">
        <div class="grid grid-cols-1 gap-4 lg:grid-cols-2" data-balance-sheet>
          <section class="ui-card flex flex-col p-4" :aria-label="t('finance.sheet.assets')">
            <h3 class="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">{{ t("finance.sheet.assets") }}</h3>
            <div v-for="section in data.assets.sections" :key="section.key" class="mb-3" :data-section="section.key">
              <div class="flex items-baseline justify-between gap-3 border-b border-line pb-1.5">
                <span class="text-base font-semibold text-fg">{{ sectionName(section.key) }}</span>
                <span class="text-base font-semibold tabular-nums text-fg"><MoneyText :value="section.total" decimals="never" /></span>
              </div>
              <ul class="flex flex-col">
                <li v-for="line in section.lines" :key="line.key" class="flex items-baseline justify-between gap-3 py-1.5 pl-3 text-sm">
                  <span class="min-w-0 truncate text-muted">{{ lineName(line.key) }}<template v-if="line.count && line.count > 1"> · {{ line.count }}</template></span>
                  <span class="shrink-0 tabular-nums text-fg"><MoneyText :value="line.amount" decimals="never" /></span>
                </li>
              </ul>
            </div>
            <span class="flex-1" />
            <div class="flex items-baseline justify-between gap-3 rounded-[8px] bg-surface-2 px-3 py-2.5">
              <span class="font-semibold text-fg">{{ t("finance.sheet.totalAssets") }}</span>
              <span class="text-md font-semibold tabular-nums text-fg" data-total-assets><MoneyText :value="data.assets.total" decimals="never" /></span>
            </div>
          </section>

          <section class="ui-card flex flex-col p-4" :aria-label="t('finance.sheet.liabilitiesAndEquity')">
            <h3 class="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">{{ t("finance.sheet.liabilities") }}</h3>
            <p v-if="!data.liabilities.sections.length" class="mb-3 text-sm text-muted">{{ t("finance.sheet.nothingOwed") }}</p>
            <div v-for="section in data.liabilities.sections" :key="section.key" class="mb-3" :data-section="section.key">
              <div class="flex items-baseline justify-between gap-3 border-b border-line pb-1.5">
                <span class="text-base font-semibold text-fg">{{ sectionName(section.key) }}</span>
                <span class="text-base font-semibold tabular-nums text-fg"><MoneyText :value="section.total" decimals="never" /></span>
              </div>
              <ul class="flex flex-col">
                <li v-for="line in section.lines" :key="line.key" class="flex items-baseline justify-between gap-3 py-1.5 pl-3 text-sm">
                  <span class="min-w-0 truncate text-muted">{{ lineName(line.key) }}</span>
                  <span class="shrink-0 tabular-nums text-fg"><MoneyText :value="line.amount" decimals="never" /></span>
                </li>
              </ul>
            </div>
            <h3 class="mb-2 mt-2 text-sm font-semibold uppercase tracking-wide text-muted">{{ data.whole_company ? t("finance.sheet.equity") : t("finance.sheet.branchNetAssets") }}</h3>
            <ul class="mb-3 flex flex-col">
              <li v-for="line in data.equity.lines" :key="line.key" class="flex items-baseline justify-between gap-3 py-1.5 pl-3 text-sm" :data-equity="line.key">
                <span class="min-w-0 truncate text-muted">{{ lineName(line.key) }}</span>
                <span :class="['shrink-0 tabular-nums', compare(line.amount, 0) < 0 ? 'text-danger' : 'text-fg']"><MoneyText :value="line.amount" decimals="never" /></span>
              </li>
            </ul>
            <span class="flex-1" />
            <div class="flex items-baseline justify-between gap-3 rounded-[8px] bg-surface-2 px-3 py-2.5">
              <span class="font-semibold text-fg">{{ t("finance.sheet.liabilitiesAndEquity") }}</span>
              <span class="text-md font-semibold tabular-nums text-fg"><MoneyText :value="data.check.liabilities_and_equity" decimals="never" /></span>
            </div>
          </section>
        </div>
        <p class="-mt-1 flex items-center gap-1.5 text-xs text-muted" data-balanced>
          <component :is="data.check.balanced ? CircleCheck : TriangleAlert" :size="14" :class="data.check.balanced ? 'text-success' : 'text-warning'" aria-hidden="true" />
          {{ data.whole_company ? t("finance.sheet.balancedNote") : t("finance.sheet.branchNote") }}
        </p>

        <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <ValuationCard v-if="data.whole_company && company.can('finance.view')" />
          <section v-if="data.reconciliation" class="ui-card p-4" data-reconciliation>
            <h3 class="mb-1 text-sm font-semibold text-fg">{{ t("finance.sheet.howRetained") }}</h3>
            <p class="mb-3 text-xs text-muted">{{ t("finance.sheet.howRetainedHint") }}</p>
            <ul class="flex flex-col divide-y divide-line text-sm">
              <li v-for="line in data.reconciliation.lines" :key="line.key" class="flex items-baseline justify-between gap-3 py-2">
                <span class="min-w-0 text-muted">{{ lineName(line.key) }}</span>
                <span class="shrink-0 tabular-nums text-fg"><MoneyText :value="line.amount" sign="always" decimals="never" /></span>
              </li>
              <li class="flex items-baseline justify-between gap-3 py-2 font-semibold">
                <span class="text-fg">{{ lineName("retained") }}</span>
                <span class="tabular-nums text-fg"><MoneyText :value="data.reconciliation.retained" decimals="never" /></span>
              </li>
            </ul>
          </section>
          <section class="ui-card p-4" data-gaps>
            <h3 class="mb-2 text-sm font-semibold text-fg">{{ t("finance.sheet.gapsTitle") }}</h3>
            <ul v-if="data.gaps.length" class="flex flex-col gap-2 text-sm">
              <li v-for="gap in data.gaps" :key="gap.key + JSON.stringify(gap.params)" class="flex gap-2">
                <TriangleAlert :size="15" class="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
                <span class="text-fg">{{ gapText(gap) }}</span>
              </li>
            </ul>
            <p v-else class="flex items-center gap-2 text-sm text-muted"><CircleCheck :size="15" class="text-success" aria-hidden="true" />{{ t("finance.sheet.noGaps") }}</p>
          </section>
        </div>
      </template>
    </template>
  </div>
</template>
