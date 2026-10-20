<script setup lang="ts">
/**
 * Monthly targets with daily pacing (plan §1.7, Should): the company's goal as a headline with its
 * pace marker, net so far against the target line day by day, then every branch and person target
 * with how much is needed per remaining day. Months switch with the arrows; the month is in the URL.
 */
import { ChevronLeft, ChevronRight, Pencil, Plus, Target, Trash2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import BulletBar from "@/components/BulletBar.vue";
import ChartCard from "@/components/ChartCard.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import LineChart from "@/components/LineChart.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { addMonths, formatDay, todayIn } from "@/lib/dates";
import { divide, multiply } from "@/lib/decimal";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { salesApi, useSalesMutation, useTargets } from "../api";
import TargetDialog from "../components/TargetDialog.vue";
import type { Target as SalesTarget } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();

const thisMonth = computed(() => todayIn(company.timezone).slice(0, 7));
const month = useRouteState<string>("month", rs.string(""));
const shown = computed(() => (/^\d{4}-\d{2}$/.test(month.value) ? month.value : thisMonth.value));
const query = useTargets(shown);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const data = computed(() => query.data.value);
const companyTarget = computed(() => data.value?.targets.find((row) => row.scope === "company") ?? null);
const others = computed(() => (data.value?.targets ?? []).filter((row) => row.scope !== "company"));
const canManage = computed(() => company.can("sales.manage"));

function go(step: number): void {
  const next = addMonths(`${shown.value}-01`, step).slice(0, 7);
  month.value = next === thisMonth.value ? "" : next;
}
const monthLabel = computed(() => formatDay(`${shown.value}-01`, fmt.lang.value, "monthYear"));

const chart = computed(() => {
  const series = data.value?.series ?? [];
  const target = companyTarget.value;
  const days = series.length || 1;
  return {
    categories: series.map((row) => row.date),
    series: [
      { name: t("sales.targets.actual"), data: series.map((row, index) => (data.value && row.date > data.value.today ? null : series[index]!.cumulative)) },
      ...(target ? [{ name: t("sales.targets.line"), data: series.map((_, index) => multiply(divide(target.amount, days) ?? "0", index + 1)), dashed: true }] : []),
    ],
  };
});

const dialog = ref(route.query.new === "target");
const editing = ref<SalesTarget | null>(null);
watch(dialog, (value) => {
  if (!value) {
    editing.value = null;
    if (route.query.new) void router.replace({ query: { ...route.query, new: undefined } });
  }
});
function edit(target: SalesTarget): void {
  editing.value = target;
  dialog.value = true;
}
const remove = useSalesMutation((cid, id: number) => salesApi.deleteTarget(cid, id));
async function askRemove(target: SalesTarget): Promise<void> {
  const answer = await confirm({ title: t("sales.targets.removeTitle"), message: t("sales.targets.removeBody"), confirmLabel: t("common.delete"), tone: "danger" });
  if (!answer) return;
  await remove.mutateAsync(target.id);
  toast.success(t("sales.targets.removed"));
}
function label(target: SalesTarget): string {
  return target.scope === "branch" ? (target.branch?.name ?? "") : (target.member?.name ?? "");
}
const expected = (target: SalesTarget) => (target.days ? target.elapsed / target.days : null);
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader :title="t('sales.targets.title')" :description="t('sales.targets.description')" class="!mb-0">
      <template #actions>
        <div class="flex items-center gap-1 rounded-button border border-line bg-surface p-0.5">
          <IconButton :icon="ChevronLeft" :label="t('sales.targets.prev')" size="sm" @click="go(-1)" />
          <span class="min-w-[120px] px-2 text-center text-sm font-semibold capitalize text-fg">{{ monthLabel }}</span>
          <IconButton :icon="ChevronRight" :label="t('sales.targets.next')" size="sm" @click="go(1)" />
        </div>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="dialog = true">{{ t("sales.targets.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="skeleton" class="flex flex-col gap-3"><SkeletonBlock height="130px" radius="12px" /><SkeletonBlock height="280px" radius="12px" /></div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="data">
      <div v-if="!data.targets.length" class="ui-card">
        <EmptyState :icon="Target" :title="t('sales.targets.emptyTitle')" :description="t('sales.targets.emptyBody')">
          <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="dialog = true">{{ t("sales.targets.new") }}</UiButton>
        </EmptyState>
      </div>
      <template v-else>
        <section v-if="companyTarget" class="ui-card grid gap-5 p-5 md:grid-cols-[minmax(0,1fr)_auto]">
          <div class="flex min-w-0 flex-col gap-3">
            <div class="flex flex-wrap items-center gap-2">
              <h2 class="text-sm font-semibold text-fg">{{ t("sales.targets.company") }}</h2>
              <StatusPill size="sm" :tone="companyTarget.ahead ? 'success' : 'warning'" :label="companyTarget.ahead ? t('sales.targets.ahead') : t('sales.targets.behind')" />
            </div>
            <p class="text-2xl font-semibold tabular-nums text-fg"><MoneyText :value="companyTarget.actual" compact /> <span class="text-lg font-normal text-subtle">/ <MoneyText :value="companyTarget.amount" compact /></span></p>
            <BulletBar :value="companyTarget.actual" :target="companyTarget.amount" :expected="expected(companyTarget)" value-format="compact" />
          </div>
          <dl class="grid grid-cols-3 gap-4 self-center md:grid-cols-1 md:gap-2 md:text-right">
            <div>
              <dt class="text-xs text-muted">{{ t("sales.targets.done") }}</dt>
              <dd class="text-md font-semibold tabular-nums text-fg">{{ fmt.percent(Number(companyTarget.percent), 1) }}</dd>
            </div>
            <div>
              <dt class="text-xs text-muted">{{ t("sales.targets.projected") }}</dt>
              <dd class="text-md font-semibold tabular-nums text-fg"><MoneyText :value="companyTarget.projected" compact /></dd>
            </div>
            <div v-if="companyTarget.per_day_needed">
              <dt class="text-xs text-muted">{{ t("sales.targets.perDay") }}</dt>
              <dd class="text-md font-semibold tabular-nums text-fg"><MoneyText :value="companyTarget.per_day_needed" compact /></dd>
            </div>
          </dl>
        </section>

        <ChartCard :title="t('sales.targets.chart')" :subtitle="t('sales.targets.chartSub')" height="260px">
          <LineChart :categories="chart.categories" :series="chart.series" value-format="money" x-format="day" height="260px" />
        </ChartCard>

        <section v-if="others.length" class="ui-card">
          <h2 class="px-5 pb-2 pt-4 text-sm font-semibold text-fg">{{ t("sales.targets.list") }}</h2>
          <ul class="divide-y divide-line border-t border-line">
            <li v-for="target in others" :key="target.id" class="grid items-center gap-3 px-5 py-3 md:grid-cols-[220px_minmax(0,1fr)_auto]">
              <div class="flex min-w-0 items-center gap-2.5">
                <UserAvatar v-if="target.scope === 'person'" :name="label(target)" :size="30" />
                <span v-else class="grid size-[30px] place-items-center rounded-[9px] bg-accent-soft text-xs font-bold text-accent-fg">{{ label(target).slice(0, 2).toUpperCase() }}</span>
                <div class="min-w-0">
                  <p class="truncate text-sm font-semibold text-fg">{{ label(target) }}</p>
                  <p class="text-xs text-muted">{{ t(`sales.targets.scope.${target.scope}`) }}</p>
                </div>
              </div>
              <BulletBar :value="target.actual" :target="target.amount" :expected="expected(target)" value-format="compact" size="sm" />
              <div class="flex items-center gap-2 md:justify-end">
                <span class="text-xs text-muted">{{ target.per_day_needed ? t("sales.targets.perDayShort", { amount: fmt.money(target.per_day_needed, undefined, { compact: true }) }) : t("sales.targets.closed") }}</span>
                <template v-if="canManage">
                  <IconButton :icon="Pencil" :label="t('common.edit')" size="sm" @click="edit(target)" />
                  <IconButton :icon="Trash2" :label="t('common.delete')" size="sm" @click="askRemove(target)" />
                </template>
              </div>
            </li>
          </ul>
        </section>
      </template>
    </template>
    <TargetDialog v-model:open="dialog" :month="`${shown}-01`" :target="editing" />
  </div>
</template>
