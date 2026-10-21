<script setup lang="ts">
/**
 * Finance reports (plan §6.2 "Reports: P&L, cash flow, balances on a date, debt aging, category
 * trends; each with export"), one tab each at `finance/reports/:report`, with a branch filter when
 * the company has several branches. The period stays in the URL across tabs.
 */
import { computed, defineAsyncComponent } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import BranchPicker from "@/components/BranchPicker.vue";
import PageHeader from "@/components/PageHeader.vue";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { REPORTS, type ReportId } from "../routes";

const views: Record<ReportId, ReturnType<typeof defineAsyncComponent>> = {
  pnl: defineAsyncComponent(() => import("../components/reports/PnlReport.vue")),
  "cash-flow": defineAsyncComponent(() => import("../components/reports/CashFlowReport.vue")),
  balances: defineAsyncComponent(() => import("../components/reports/BalancesReport.vue")),
  "debts-aging": defineAsyncComponent(() => import("../components/reports/AgingReport.vue")),
  "category-trend": defineAsyncComponent(() => import("../components/reports/CategoryTrendReport.vue")),
};

const { t } = useI18n();
const route = useRoute();
const company = useCompanyStore();

const report = computed<ReportId>(() => (REPORTS as readonly string[]).includes(String(route.params.report)) ? (route.params.report as ReportId) : "pnl");
const branch = useRouteState("branch", rs.numberList());
const multiBranch = computed(() => (company.current?.branches.length ?? 0) > 1);

const tabs = computed(() =>
  REPORTS.map((id) => ({
    id,
    label: t(`finance.reports.tab.${id}`),
    to: { path: `/c/${company.currentId}/finance/reports/${id}`, query: carry.value },
  })),
);
/** The period and branches travel between tabs; report-only parameters stay behind. */
const carry = computed(() => {
  const keep = ["preset", "from", "to", "compare", "branch"];
  return Object.fromEntries(Object.entries(route.query).filter(([key]) => keep.includes(key)));
});
const description = computed(() => t(`finance.reports.about.${report.value}`));
</script>

<template>
  <div>
    <PageHeader :title="t('finance.nav.reports')" :description="description" :tabs="tabs">
      <template v-if="multiBranch" #actions>
        <BranchPicker v-model="branch" multiple class="w-60" :placeholder="t('finance.reports.allBranches')" />
      </template>
    </PageHeader>
    <component :is="views[report]" :key="report" :branch="branch" />
  </div>
</template>
