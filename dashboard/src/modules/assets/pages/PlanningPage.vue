<script setup lang="ts">
/**
 * What an owner should plan for and rarely sees in one place: the replacements coming as assets
 * reach the end of their life (by quarter, with the price grown by inflation, so the money is
 * set aside in time), assets whose repairs approach the price of a new one, money sleeping in
 * idle or mothballed assets, old ones that still work for free, upkeep coming up or overdue, and
 * things given to people that nobody confirmed receiving.
 */
import { CalendarClock, CircleCheck, CircleDollarSign, Moon, PiggyBank, UserX, Wrench } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { usePlanning } from "../api";
import { categoryIcon, daysUntil, UPKEEP_ICONS, upkeepTone } from "../lib";
import type { AssetRow } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const branch = computed(() => (company.branchFilter.length === 1 ? company.branchFilter[0] : undefined));
const planning = usePlanning(computed(() => ({ branch: branch.value })));
const data = computed(() => planning.data.value);
const today = useCompanyToday();

const kpis = computed(() => [
  { id: "replace", label: t("assets.planning.kpiReplace"), value: data.value?.replacement_total ?? null, format: "money" as const, compact: true, hint: t("assets.planning.kpiReplaceHint", { rate: data.value?.inflation ?? "10" }) },
  { id: "repairs", label: t("assets.planning.kpiRepairs"), value: data.value?.repairs.length ?? null, format: "number" as const },
  { id: "idle", label: t("assets.planning.kpiIdle"), value: data.value?.idle_value ?? null, format: "money" as const, compact: true },
  { id: "upkeep", label: t("assets.planning.kpiUpkeep"), value: data.value?.upkeep.filter((row) => row.overdue).length ?? null, format: "number" as const, hint: t("assets.planning.kpiUpkeepHint") },
]);

function open(asset: Pick<AssetRow, "id">): void {
  void router.push(`/c/${company.currentId}/assets/items/${asset.id}`);
}

const quarterMax = computed(() => Math.max(1, ...(data.value?.quarters ?? []).map((row) => Number(row.amount))));
function quarterLabel(key: string): string {
  const [year, quarter] = key.split("-Q");
  return t("assets.planning.quarter", { quarter, year });
}
</script>

<template>
  <div>
    <PageHeader :title="t('assets.nav.planning')" :description="t('assets.planning.description')" />
    <KpiStrip class="mb-4" :items="kpis" :loading="planning.isPending.value" :columns="4" phone="grid" />

    <ErrorState v-if="planning.isError.value" :error="planning.error.value" :retry="() => planning.refetch()" />
    <div v-else-if="planning.isPending.value" class="grid gap-4"><SkeletonBlock v-for="n in 3" :key="n" height="160px" radius="12px" /></div>
    <div v-else-if="data" class="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <PageSection variant="card" :title="t('assets.planning.replaceTitle')" :description="t('assets.planning.replaceBody')">
        <EmptyState v-if="!data.replacements.length" size="sm" :icon="PiggyBank" :title="t('assets.planning.replaceEmpty')" />
        <template v-else>
          <ul class="mb-4 flex flex-col gap-2">
            <li v-for="row in data.quarters" :key="row.quarter" class="flex items-center gap-3 text-sm">
              <span class="w-28 shrink-0 text-muted">{{ quarterLabel(row.quarter) }}</span>
              <ProgressBar class="flex-1" :value="Number(row.amount)" :max="quarterMax" />
              <span class="w-32 shrink-0 text-right font-semibold tabular-nums"><MoneyText :value="row.amount" compact /></span>
            </li>
          </ul>
          <ul class="divide-y divide-line">
            <li v-for="row in data.replacements" :key="row.asset.id">
              <button type="button" class="flex w-full items-center gap-3 py-2 text-left hover:bg-surface-2/50" @click="open(row.asset)">
                <component :is="categoryIcon(row.asset.icon)" :size="16" class="shrink-0 text-muted" aria-hidden="true" />
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-sm font-medium text-fg">{{ row.asset.number }} · {{ row.asset.name }}</span>
                  <span class="block text-xs text-muted">{{ t("assets.planning.endsIn", { month: row.end_month ? fmt.day(row.end_month, "monthYear") : "—" }) }}</span>
                </span>
                <span class="text-right text-sm tabular-nums">
                  <MoneyText :value="row.estimate ?? null" decimals="never" />
                  <span class="block text-xs text-muted">{{ t("assets.planning.wasCost", { amount: fmt.money(row.asset.cost, undefined, { decimals: "never" }) }) }}</span>
                </span>
              </button>
            </li>
          </ul>
        </template>
      </PageSection>

      <PageSection variant="card" :title="t('assets.planning.repairsTitle')" :description="t('assets.planning.repairsBody')">
        <EmptyState v-if="!data.repairs.length" size="sm" tone="success" :icon="CircleCheck" :title="t('assets.planning.repairsEmpty')" />
        <ul v-else class="divide-y divide-line">
          <li v-for="row in data.repairs" :key="row.asset.id">
            <button type="button" class="flex w-full flex-col gap-1.5 py-2.5 text-left hover:bg-surface-2/50" @click="open(row.asset)">
              <span class="flex items-center gap-2">
                <Wrench :size="15" class="shrink-0 text-warning" aria-hidden="true" />
                <span class="min-w-0 flex-1 truncate text-sm font-medium text-fg">{{ row.asset.number }} · {{ row.asset.name }}</span>
                <StatusPill size="sm" tone="warning" :label="t('assets.planning.share', { share: fmt.number(row.share ?? 0) })" />
              </span>
              <span class="text-xs text-muted">{{ t("assets.planning.repairsLine", { repairs: fmt.money(row.repairs ?? "0", undefined, { decimals: "never" }), price: fmt.money(row.replacement ?? "0", undefined, { decimals: "never" }), book: fmt.money(row.asset.book_value, undefined, { decimals: "never" }) }) }}</span>
            </button>
          </li>
        </ul>
      </PageSection>

      <PageSection variant="card" :title="t('assets.planning.upkeepTitle')" :description="t('assets.planning.upkeepBody')">
        <EmptyState v-if="!data.upkeep.length" size="sm" tone="success" :icon="CalendarClock" :title="t('assets.planning.upkeepEmpty')" />
        <ul v-else class="divide-y divide-line">
          <li v-for="row in data.upkeep" :key="`${row.asset.id}-${row.what}`">
            <button type="button" class="flex w-full items-center gap-3 py-2 text-left hover:bg-surface-2/50" @click="open(row.asset)">
              <component :is="UPKEEP_ICONS[row.what]" :size="16" class="shrink-0 text-muted" aria-hidden="true" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-medium text-fg">{{ t(`assets.upkeep.${row.what}`) }} · {{ row.asset.name }}</span>
                <span class="block text-xs text-muted">{{ row.asset.number }}{{ row.asset.branch ? ` · ${row.asset.branch.name}` : "" }}</span>
              </span>
              <StatusPill size="sm" :tone="upkeepTone(row.day, today)" :label="row.overdue ? t('assets.item.overdue', { day: fmt.day(row.day, 'medium') }) : `${fmt.day(row.day, 'medium')} · ${t('assets.item.inDays', { n: daysUntil(row.day, today) })}`" />
            </button>
          </li>
        </ul>
      </PageSection>

      <PageSection variant="card" :title="t('assets.planning.idleTitle')" :description="t('assets.planning.idleBody')">
        <EmptyState v-if="!data.idle.length && !data.free.length" size="sm" tone="success" :icon="CircleDollarSign" :title="t('assets.planning.idleEmpty')" />
        <ul v-if="data.idle.length" class="mb-3 divide-y divide-line">
          <li v-for="asset in data.idle" :key="asset.id">
            <button type="button" class="flex w-full items-center gap-3 py-2 text-left hover:bg-surface-2/50" @click="open(asset)">
              <Moon :size="15" class="shrink-0 text-info" aria-hidden="true" />
              <span class="min-w-0 flex-1 truncate text-sm font-medium text-fg">{{ asset.number }} · {{ asset.name }}</span>
              <span class="text-sm tabular-nums"><MoneyText :value="asset.book_value" decimals="never" /></span>
            </button>
          </li>
        </ul>
        <template v-if="data.free.length">
          <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{{ t("assets.planning.freeTitle") }}</h3>
          <p class="mb-2 text-xs text-muted">{{ t("assets.planning.freeBody") }}</p>
          <ul class="divide-y divide-line">
            <li v-for="asset in data.free" :key="asset.id">
              <button type="button" class="flex w-full items-center gap-3 py-2 text-left hover:bg-surface-2/50" @click="open(asset)">
                <CircleCheck :size="15" class="shrink-0 text-success" aria-hidden="true" />
                <span class="min-w-0 flex-1 truncate text-sm font-medium text-fg">{{ asset.number }} · {{ asset.name }}</span>
              </button>
            </li>
          </ul>
        </template>
      </PageSection>

      <PageSection v-if="data.unconfirmed.length" variant="card" :title="t('assets.planning.unconfirmedTitle')" :description="t('assets.planning.unconfirmedBody')">
        <ul class="divide-y divide-line">
          <li v-for="row in data.unconfirmed" :key="row.asset.id">
            <button type="button" class="flex w-full items-center gap-3 py-2 text-left hover:bg-surface-2/50" @click="open(row.asset)">
              <UserX :size="15" class="shrink-0 text-warning" aria-hidden="true" />
              <span class="min-w-0 flex-1 truncate text-sm text-fg">{{ row.asset.name }} → {{ row.person.name }}</span>
              <span class="text-xs text-muted">{{ fmt.day(row.issued_on, "medium") }}</span>
            </button>
          </li>
        </ul>
      </PageSection>
    </div>
  </div>
</template>
