<script setup lang="ts">
/**
 * Mening pulim (v11): the owner's money. How much is safe to take out today without hurting the
 * business, and why (the cash on the business's accounts less the payments due, the cash buffer
 * and planned purchases); take money out or put it in; this month's draws, six months of profit
 * against what was taken, a monthly amount the cash forecast carries, planned purchases; and the
 * partners with their shares, their part of the profit and the dividend rounds. Business and
 * personal money stay apart: the owner's own-money accounts never count as the business's cash.
 */
import { ArrowDownLeft, ArrowUpRight, ChartColumn, Coins, Crown } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import BarChart from "@/components/BarChart.vue";
import ChartCard from "@/components/ChartCard.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiBadge from "@/components/UiBadge.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import BufferDialog from "../components/owner/BufferDialog.vue";
import MoveMoneyDialog from "../components/owner/MoveMoneyDialog.vue";
import PartnersTab from "../components/owner/PartnersTab.vue";
import PurchasesCard from "../components/owner/PurchasesCard.vue";
import ReasonList from "../components/owner/ReasonList.vue";
import SafeHero from "../components/owner/SafeHero.vue";
import { useCssColor } from "../colors";
import { useOwnerMoney } from "../ownerMoney";

const { t } = useI18n();
const fmt = useFormat();
const css = useCssColor();
const company = useCompanyStore();
const summary = useOwnerMoney();
const data = computed(() => summary.data.value);
const skeleton = useDelayedPending(computed(() => summary.isPending.value));
const tab = useRouteState("tab", rs.enum(["overview", "partners"] as const, "overview"));
const tabModel = computed({
  get: () => tab.value as string,
  set: (value: string) => (tab.value = value === "partners" ? "partners" : "overview"),
});
const canWrite = computed(() => company.can("finance.manage"));
const mine = computed(() => data.value?.is_owner ?? company.isOwner);

const moving = ref<"take" | "put" | null>(null);
const moveOpen = computed({
  get: () => moving.value !== null,
  set: (value: boolean) => {
    if (!value) moving.value = null;
  },
});
const settingsOpen = ref(false);

const history = computed(() => data.value?.history ?? []);
const historySeries = computed(() => [
  { name: t("finance.myMoney.profit"), data: history.value.map((row) => row.profit), color: css("var(--c-success)") },
  { name: t("finance.myMoney.drawn"), data: history.value.map((row) => row.drawn), color: css("var(--c-chart-1)") },
]);
const historyEmpty = computed(() => history.value.every((row) => !Number(row.profit) && !Number(row.drawn)));
const tabs = computed(() => [
  { id: "overview", label: t("finance.myMoney.tabMoney") },
  { id: "partners", label: t("finance.myMoney.tabPartners"), count: data.value?.partners || undefined },
]);
</script>

<template>
  <div>
    <PageHeader
      v-model:tab="tabModel"
      :title="mine ? t('finance.myMoney.title') : t('finance.myMoney.titleOthers')"
      :description="t('finance.myMoney.description')"
      :tabs="tabs"
    />

    <ErrorState v-if="summary.isError.value" :error="summary.error.value" :retry="() => summary.refetch()" />

    <div v-else-if="skeleton || !data" class="flex flex-col gap-4" aria-busy="true">
      <SkeletonBlock height="260px" radius="16px" />
      <div class="grid gap-4 lg:grid-cols-3"><SkeletonBlock class="lg:col-span-2" height="360px" /><SkeletonBlock height="360px" /></div>
    </div>

    <div v-else-if="tab === 'overview'" class="flex flex-col gap-4">
      <SafeHero :data="data" :can-write="canWrite" @take="moving = 'take'" @put="moving = 'put'" @settings="settingsOpen = true" />

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <ReasonList class="lg:col-span-2" :data="data" @settings="settingsOpen = true" />

        <div class="flex flex-col gap-4">
          <section class="ui-card flex flex-col p-4 sm:p-5" :aria-label="t('finance.myMoney.monthTitle')" data-month>
            <header class="mb-2 flex items-center gap-2">
              <Coins :size="16" class="text-subtle" aria-hidden="true" />
              <h3 class="flex-1 text-sm font-semibold text-fg">{{ t("finance.myMoney.monthTitle") }}</h3>
              <UiBadge v-if="data.month.count" :count="data.month.count" tone="neutral" />
            </header>
            <EmptyState v-if="!data.month.rows.length" size="sm" tone="neutral" :icon="Coins" :title="t('finance.myMoney.monthEmpty')" :description="t('finance.myMoney.monthEmptyBody')" />
            <ul v-else class="-mx-2 flex flex-col">
              <li v-for="row in data.month.rows" :key="row.id" class="flex items-center gap-3 rounded-[10px] px-2 py-2" :data-flow="row.direction">
                <span :class="['grid size-8 shrink-0 place-items-center rounded-[9px]', row.direction === 'out' ? 'bg-accent-soft text-accent-fg' : 'bg-success-soft text-success']" aria-hidden="true">
                  <ArrowUpRight v-if="row.direction === 'out'" :size="16" />
                  <ArrowDownLeft v-else :size="16" />
                </span>
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-semibold text-fg" :title="row.description">{{ row.dividend ? t("finance.myMoney.dividendRow") : row.description }}</p>
                  <p class="truncate text-xs text-muted">{{ fmt.day(row.occurred_on, "short") }} · {{ row.account.name }}</p>
                </div>
                <span class="shrink-0 text-sm font-semibold tabular-nums" :class="row.direction === 'out' ? 'text-fg' : 'text-success'">
                  {{ row.direction === "out" ? "−" : "+" }}<MoneyText :value="row.base_amount" compact />
                </span>
              </li>
            </ul>
            <p v-if="Number(data.personal) > 0" class="mt-2 flex items-start gap-1.5 border-t border-line pt-2.5 text-xs text-muted" data-personal>
              <Crown :size="13" class="mt-px shrink-0 text-subtle" aria-hidden="true" />
              {{ t("finance.myMoney.personal", { amount: fmt.money(data.personal, undefined, { compact: true }) }) }}
            </p>
          </section>

          <PurchasesCard :data="data" :can-write="canWrite" />
        </div>
      </div>

      <ChartCard
        :title="t('finance.myMoney.historyTitle')"
        :subtitle="t('finance.myMoney.historySubtitle')"
        :empty="historyEmpty"
        :empty-text="t('finance.myMoney.historyEmpty')"
        height="240px"
        data-history
      >
        <template #actions><ChartColumn :size="16" class="text-subtle" aria-hidden="true" /></template>
        <BarChart :categories="history.map((row) => row.month)" :series="historySeries" value-format="money" x-format="month" height="240px" legend />
      </ChartCard>
    </div>

    <PartnersTab v-else :data="data" :can-write="canWrite" />

    <template v-if="data">
      <MoveMoneyDialog v-if="moving" v-model:open="moveOpen" :mode="moving" :data="data" />
      <BufferDialog v-model:open="settingsOpen" :data="data" />
    </template>
  </div>
</template>
