<script setup lang="ts">
/** Debt aging: open debts of one direction by how late they are, per party, with the totals. */
import { ArrowDownLeft, ArrowUpRight } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import MoneyText from "@/components/MoneyText.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useAging } from "../../api";
import { AGING_BUCKETS, AGING_COLORS, dayStyle, isZeroMoney } from "../../lib";
import AgingBar from "../AgingBar.vue";

const props = defineProps<{ branch: number[] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const direction = useRouteState("direction", rs.enum(["receivable", "payable"] as const, "receivable"));
const params = computed(() => ({ direction: direction.value, ...(props.branch.length ? { branch: props.branch } : {}) }));
const query = useAging(params);
const data = computed(() => query.data.value);

function partyLink(party: { type: string; id: number | null }) {
  if (party.type === "counterparty" && party.id) return `/c/${company.currentId}/finance/counterparties/${party.id}`;
  return { path: `/c/${company.currentId}/finance/debts`, query: { direction: direction.value } };
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <SegmentedControl
        v-model="direction"
        size="sm"
        :options="[
          { value: 'receivable', label: t('finance.debts.side.receivable'), icon: ArrowDownLeft },
          { value: 'payable', label: t('finance.debts.side.payable'), icon: ArrowUpRight },
        ]"
      />
      <span class="flex-1" />
      <ExportButton kind="finance.debts" :params="{ direction }" size="sm" sensitive />
    </div>
    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else>
      <section class="ui-card p-4 md:p-5">
        <div class="mb-3 flex items-baseline justify-between gap-3">
          <h3 class="text-sm font-semibold text-fg">{{ t("finance.aging.title") }}</h3>
          <p v-if="data" class="text-xl font-semibold tabular-nums text-fg"><MoneyText :value="data.totals.total" decimals="never" /></p>
        </div>
        <SkeletonBlock v-if="query.isPending.value" height="60px" />
        <AgingBar v-else :totals="data?.totals" />
      </section>
      <div class="ui-card overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full min-w-[720px] border-separate border-spacing-0 text-base">
            <thead>
              <tr class="bg-surface-2 text-xs font-semibold text-muted">
                <th scope="col" class="sticky left-0 bg-surface-2 px-4 py-2.5 text-left">{{ direction === "receivable" ? t("finance.debts.whoOwes") : t("finance.debts.whomWeOwe") }}</th>
                <th v-for="bucket in AGING_BUCKETS" :key="bucket" scope="col" class="whitespace-nowrap px-3 py-2.5 text-right">
                  <span class="inline-flex items-center gap-1.5"><span class="size-2 rounded-full" :style="{ background: AGING_COLORS[bucket] }" />{{ t(`finance.aging.${bucket}`) }}</span>
                </th>
                <th scope="col" class="px-3 py-2.5 text-right text-fg">{{ t("finance.reports.total") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="query.isPending.value"><td :colspan="7" class="p-4"><SkeletonBlock height="180px" /></td></tr>
              <tr v-else-if="!data?.parties.length"><td :colspan="7" class="px-4 py-10 text-center text-muted">{{ t("finance.reports.agingEmpty") }}</td></tr>
              <tr v-for="party in data?.parties ?? []" :key="`${party.type}-${party.id}`" class="group">
                <th scope="row" class="sticky left-0 border-t border-line bg-surface px-4 py-2.5 text-left font-medium group-hover:bg-surface-2/60">
                  <RouterLink :to="partyLink(party)" class="block min-w-0 hover:text-accent-fg">
                    <span class="block truncate text-fg">{{ party.name }}</span>
                    <span class="block truncate text-xs font-normal text-muted">
                      {{ t("finance.overview.debtCount", { n: party.count }, party.count) }}<template v-if="party.oldest_due"> · {{ t("finance.reports.oldestDue", { date: fmt.day(party.oldest_due, dayStyle(party.oldest_due)) }) }}</template>
                    </span>
                  </RouterLink>
                </th>
                <td v-for="bucket in AGING_BUCKETS" :key="bucket" :class="['border-t border-line px-3 py-2.5 text-right tabular-nums group-hover:bg-surface-2/60', isZeroMoney(party[bucket]) ? 'text-subtle' : bucket === 'd90' ? 'font-semibold text-danger' : 'text-fg']">
                  <template v-if="isZeroMoney(party[bucket])">—</template>
                  <MoneyText v-else :value="party[bucket]" decimals="never" />
                </td>
                <td class="border-t border-line px-3 py-2.5 text-right font-semibold tabular-nums text-fg group-hover:bg-surface-2/60"><MoneyText :value="party.total" decimals="never" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
