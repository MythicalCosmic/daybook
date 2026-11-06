<script setup lang="ts">
/**
 * Budgets (plan §1.6 "budgets vs actual per category per month, 80 %/100 % alerts, copy last
 * month"; §6.2 "budgets month grid with pace bars"): one month at a time, every expense category
 * with its subcategories under it, the budget typed in place, what was spent, a bar coloured by the
 * server's thresholds (amber from 80 %, red from 100 %) with a tick at the month's even pace, the
 * share used and what is left, the totals at the foot. "Copy last month" fills the categories that
 * have no budget yet. Typed budgets save together from the bar at the bottom; leaving the month
 * with some unsaved asks first.
 */
import { Copy, PiggyBank, Tags } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { unshownFieldError } from "@/api/http";
import { shareText } from "@/components/chartCard";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { dec, toMoney } from "@/lib/decimal";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyId, useCompanyStore, useCompanyToday } from "@/stores/company";

import { financeApi, financeKeys, useBudgets, useRefresh } from "../api";
import MonthSwitcher from "../components/MonthSwitcher.vue";
import { BUDGET_TONES, budgetChanges, budgetLines, budgetShare, budgetStatus, colorFor, draftBudgetTotal, isMonth, monthPace, shiftMonth } from "../lib";
import type { BudgetMonth, BudgetRow, BudgetStatus } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const cid = useCompanyId();
const client = useQueryClient();
const confirm = useConfirm();
const refresh = useRefresh();
const { isPhone } = useBreakpoints();
const today = useCompanyToday();
const canManage = computed(() => company.can("finance.manage"));

const thisMonth = computed(() => today.value.slice(0, 7));
const monthParam = useRouteState("month", rs.string(""));
const month = computed({
  get: () => (isMonth(monthParam.value) ? monthParam.value : thisMonth.value),
  set: (value: string) => (monthParam.value = value === thisMonth.value ? "" : value),
});
const query = useBudgets(month);
const data = computed(() => query.data.value ?? null);
/** keepPreviousData shows the last month while the next loads: no typing into the wrong month. */
const stale = computed(() => !!data.value && data.value.month !== month.value);
const rows = computed(() => data.value?.rows ?? []);

// Drafts -----------------------------------------------------------------------------------

const drafts = reactive<Record<number, string | null>>({});
function clearDrafts(): void {
  for (const key of Object.keys(drafts)) delete drafts[Number(key)];
}
watch(month, clearDrafts);

const changes = computed(() => budgetChanges(rows.value, drafts));
const dirty = computed(() => changes.value.length > 0);

function budgetOf(row: BudgetRow): string | null {
  // `in` is what a reactive object tracks (hasOwnProperty isn't), so a first draft re-renders.
  return row.category.id in drafts ? (drafts[row.category.id] ?? null) : row.budget;
}
const edited = (row: BudgetRow) => changes.value.some((change) => change.category === row.category.id);

/** The server's answer for a saved row, the same rule worked out here for one being typed. */
function statusOf(row: BudgetRow): BudgetStatus {
  return edited(row) ? budgetStatus(budgetOf(row), row.actual) : row.status;
}
function shareOf(row: BudgetRow): number | null {
  if (!edited(row) && row.share !== null) return Number(row.share);
  return budgetShare(budgetOf(row), row.actual);
}
function leftOf(row: BudgetRow): string | null {
  const budget = budgetOf(row);
  return budget === null || budget === "" ? null : toMoney(dec(budget).minus(dec(row.actual)));
}

const lines = computed(() => budgetLines(rows.value));
const anyBudget = computed(() => rows.value.some((row) => budgetOf(row) !== null && budgetOf(row) !== ""));
/** The invitation stays until a budget is saved: it must not vanish (and move the table) mid-typing. */
const anySaved = computed(() => rows.value.some((row) => row.budget !== null));

// Totals and the month -----------------------------------------------------------------------

const totalBudget = computed(() => (data.value ? draftBudgetTotal(data.value.totals.budget, rows.value, changes.value) : null));
const totalActual = computed(() => data.value?.totals.actual ?? null);
const totalShare = computed(() => (totalBudget.value && totalActual.value ? budgetShare(totalBudget.value, totalActual.value) : null));
const totalStatus = computed(() => (totalBudget.value && totalActual.value ? budgetStatus(totalBudget.value, totalActual.value) : "none"));
const totalLeft = computed(() => (totalBudget.value && totalActual.value ? toMoney(dec(totalBudget.value).minus(dec(totalActual.value))) : null));
const overCount = computed(() => rows.value.filter((row) => statusOf(row) === "over").length);

const timing = computed<"past" | "current" | "future">(() => (month.value < thisMonth.value ? "past" : month.value > thisMonth.value ? "future" : "current"));
/** The tick on each bar: how much of the month has gone, so 40 % spent on day 6 of 30 reads as fast. */
const pace = computed(() => (data.value && timing.value === "current" ? monthPace(data.value.days_left, data.value.days_in_month) : null));
const daysLine = computed(() => {
  const d = data.value;
  if (!d) return "";
  if (timing.value === "past") return t("finance.budgets.monthOver");
  if (timing.value === "future") return t("finance.budgets.monthAhead");
  return t("finance.budgets.daysLeft", { n: d.days_left }, d.days_left);
});

const kpis = computed(() => {
  const d = data.value;
  return [
    { id: "budget", label: t("finance.budgets.kpiBudget"), value: d ? totalBudget.value : null, format: "money" as const, compact: true, icon: PiggyBank },
    {
      id: "spent",
      label: t("finance.budgets.kpiSpent"),
      value: totalActual.value,
      format: "money" as const,
      compact: true,
      hint: totalShare.value !== null ? t("finance.budgets.ofBudget", { percent: shareText(totalShare.value * 100, fmt.lang.value) }) : undefined,
    },
    {
      id: "left",
      label: t("finance.budgets.kpiLeft"),
      value: d && anyBudget.value ? totalLeft.value : null,
      format: "money" as const,
      compact: true,
      hint: overCount.value ? t("finance.budgets.overCount", { n: overCount.value }, overCount.value) : undefined,
    },
    { id: "days", label: t("finance.budgets.kpiDays"), value: d ? (timing.value === "current" ? d.days_left : timing.value === "future" ? d.days_in_month : 0) : null, format: "number" as const, hint: daysLine.value },
  ];
});

// Actions ----------------------------------------------------------------------------------

async function go(next: string): Promise<void> {
  if (next === month.value) return;
  if (dirty.value) {
    const answer = await confirm({ title: t("finance.budgets.leaveTitle"), message: t("finance.budgets.leaveBody"), confirmLabel: t("common.discard"), tone: "danger" });
    if (!answer) return;
  }
  month.value = next;
}

function setDraft(row: BudgetRow, value: string | null): void {
  drafts[row.category.id] = value;
}

function store(answer: BudgetMonth): void {
  client.setQueryData(financeKeys.of(cid.value, "budgets", { month: answer.month }), answer);
}

const saving = ref(false);
async function save(): Promise<void> {
  if (!dirty.value) return;
  saving.value = true;
  try {
    const answer = await financeApi.setBudgets(cid.value, { month: month.value, rows: changes.value });
    store(answer);
    clearDrafts();
    toast.success(t("finance.budgets.saved"));
    refresh();
  } catch (failure) {
    const unshown = unshownFieldError(failure);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}

const copying = ref(false);
async function copyLastMonth(): Promise<void> {
  copying.value = true;
  try {
    const before = new Set(rows.value.filter((row) => row.budget !== null).map((row) => row.category.id));
    const answer = await financeApi.copyBudgets(cid.value, month.value);
    const added = answer.rows.filter((row) => row.budget !== null && !before.has(row.category.id)).length;
    store(answer);
    if (added) toast.success(t("finance.budgets.copied", { n: added }, added));
    else toast.info(t("finance.budgets.copiedNone"));
    refresh();
  } catch {
    // The HTTP layer has said what went wrong.
  } finally {
    copying.value = false;
  }
}

const maxMonth = computed(() => shiftMonth(thisMonth.value, 12));
const percent = (share: number | null) => (share === null ? "" : shareText(share * 100, fmt.lang.value));
</script>

<template>
  <div>
    <PageHeader :title="t('finance.nav.budgets')" :description="t('finance.budgets.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="secondary" :icon="Copy" :loading="copying" :disabled="dirty || stale || !rows.length" :title="dirty ? t('finance.budgets.copyDirty') : t('finance.budgets.copyHint')" data-copy @click="copyLastMonth">
          {{ t("finance.budgets.copy") }}
        </UiButton>
      </template>
    </PageHeader>

    <div class="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
      <MonthSwitcher :month="month" :current="thisMonth" :max="maxMonth" @go="go" />
      <span class="text-sm text-muted" data-days-left>{{ daysLine }}</span>
    </div>

    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else class="flex flex-col gap-4">
      <KpiStrip :items="kpis" :loading="query.isPending.value" :columns="4" phone="grid" />

      <div v-if="query.isPending.value" class="ui-card flex flex-col gap-3 p-4">
        <SkeletonBlock v-for="n in 6" :key="n" height="36px" />
      </div>

      <div v-else-if="data && !rows.length" class="ui-card">
        <EmptyState :icon="Tags" :title="t('finance.budgets.noCategories')" :description="t('finance.budgets.noCategoriesBody')">
          <UiButton v-if="canManage" variant="primary" :to="`/c/${cid}/finance/settings/categories`">{{ t("finance.budgets.openCategories") }}</UiButton>
        </EmptyState>
      </div>

      <template v-else-if="data">
        <div v-if="!anySaved" class="ui-card" data-budgets-empty>
          <EmptyState size="sm" :icon="PiggyBank" :title="t('finance.budgets.emptyTitle')" :description="canManage ? t('finance.budgets.emptyBody') : t('finance.budgets.emptyBodyView')">
            <UiButton v-if="canManage" size="sm" variant="secondary" :icon="Copy" :loading="copying" :disabled="stale" @click="copyLastMonth">{{ t("finance.budgets.copy") }}</UiButton>
          </EmptyState>
        </div>

        <!-- Phones: one card per category, the same numbers stacked. -->
        <ul v-if="isPhone" class="ui-card flex flex-col divide-y divide-line" :aria-busy="stale || undefined">
          <li v-for="line in lines" :key="line.row.category.id" :class="['flex flex-col gap-2 px-4 py-3', line.depth && 'pl-8']" :data-category="line.row.category.id">
            <div class="flex min-w-0 items-center gap-2">
              <span class="size-2 shrink-0 rounded-full" :style="{ background: colorFor(line.row.category.id, line.row.category.color) }" aria-hidden="true" />
              <span :class="['min-w-0 flex-1 truncate text-base text-fg', !line.depth && 'font-semibold']">{{ line.row.category.name }}</span>
              <span class="shrink-0 text-sm tabular-nums text-muted"><MoneyText :value="line.row.actual" decimals="never" compact /></span>
            </div>
            <MoneyInput
              v-if="canManage"
              :model-value="budgetOf(line.row)"
              size="sm"
              :disabled="stale"
              :placeholder="t('finance.budgets.noBudget')"
              :aria-label="t('finance.budgets.budgetFor', { name: line.row.category.name })"
              @update:model-value="(value) => setDraft(line.row, value)"
            />
            <div v-if="shareOf(line.row) !== null" class="flex items-center gap-2">
              <ProgressBar :value="(shareOf(line.row) ?? 0) * 100" :max="100" size="sm" :tone="BUDGET_TONES[statusOf(line.row)]" :target="pace ?? undefined" class="min-w-0 flex-1" />
              <span :class="['w-12 shrink-0 text-right text-xs font-semibold tabular-nums', statusOf(line.row) === 'over' ? 'text-danger' : statusOf(line.row) === 'warning' ? 'text-warning' : 'text-muted']">{{ percent(shareOf(line.row)) }}</span>
            </div>
          </li>
        </ul>

        <div v-else class="ui-card overflow-hidden" :aria-busy="stale || undefined">
          <div class="overflow-x-auto">
            <table class="w-full min-w-[760px] border-collapse text-sm" data-budgets>
              <thead>
                <tr class="border-b border-line bg-surface-2/50 text-left text-xs font-semibold text-muted dark:bg-surface-3/40">
                  <th scope="col" class="px-4 py-2.5">{{ t("finance.budgets.category") }}</th>
                  <th scope="col" class="w-48 px-3 py-2.5 text-right">{{ t("finance.budgets.budget") }}</th>
                  <th scope="col" class="w-36 px-3 py-2.5 text-right">{{ t("finance.budgets.spent") }}</th>
                  <th scope="col" class="w-60 px-3 py-2.5">{{ t("finance.budgets.used") }}</th>
                  <th scope="col" class="w-40 px-4 py-2.5 text-right">{{ t("finance.budgets.left") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="line in lines" :key="line.row.category.id" :class="['border-b border-line last:border-b-0', edited(line.row) && 'bg-accent-soft/30']" :data-category="line.row.category.id">
                  <td class="px-4 py-2">
                    <div :class="['flex min-w-0 items-center gap-2', line.depth && 'pl-6']">
                      <span class="size-2 shrink-0 rounded-full" :style="{ background: colorFor(line.row.category.id, line.row.category.color) }" aria-hidden="true" />
                      <span :class="['truncate', line.depth ? 'text-fg' : 'font-semibold text-fg']" :title="line.row.category.name">{{ line.row.category.name }}</span>
                    </div>
                  </td>
                  <td class="px-3 py-1.5">
                    <MoneyInput
                      v-if="canManage"
                      :model-value="budgetOf(line.row)"
                      size="sm"
                      :disabled="stale"
                      :placeholder="t('finance.budgets.noBudget')"
                      :aria-label="t('finance.budgets.budgetFor', { name: line.row.category.name })"
                      @update:model-value="(value) => setDraft(line.row, value)"
                    />
                    <span v-else-if="line.row.budget !== null" class="block text-right tabular-nums text-fg"><MoneyText :value="line.row.budget" decimals="never" /></span>
                    <span v-else class="block text-right text-subtle">{{ t("finance.budgets.noBudget") }}</span>
                  </td>
                  <td class="px-3 py-2 text-right tabular-nums text-fg"><MoneyText :value="line.row.actual" decimals="never" /></td>
                  <td class="px-3 py-2">
                    <div v-if="shareOf(line.row) !== null" class="flex items-center gap-2">
                      <ProgressBar
                        :value="(shareOf(line.row) ?? 0) * 100"
                        :max="100"
                        size="sm"
                        :tone="BUDGET_TONES[statusOf(line.row)]"
                        :target="pace ?? undefined"
                        class="min-w-0 flex-1"
                        :data-status="statusOf(line.row)"
                      />
                      <span :class="['w-12 shrink-0 text-right text-xs font-semibold tabular-nums', statusOf(line.row) === 'over' ? 'text-danger' : statusOf(line.row) === 'warning' ? 'text-warning' : 'text-muted']">{{ percent(shareOf(line.row)) }}</span>
                    </div>
                    <span v-else class="text-xs text-subtle">—</span>
                  </td>
                  <td class="px-4 py-2 text-right tabular-nums">
                    <template v-if="leftOf(line.row) !== null">
                      <span v-if="dec(leftOf(line.row)!).isNegative()" class="font-semibold text-danger">{{ t("finance.budgets.over", { amount: fmt.money(dec(leftOf(line.row)!).abs().toFixed(2), undefined, { decimals: "never" }) }) }}</span>
                      <span v-else class="text-fg"><MoneyText :value="leftOf(line.row)" decimals="never" /></span>
                    </template>
                    <span v-else class="text-subtle">—</span>
                  </td>
                </tr>
              </tbody>
              <tfoot>
                <tr class="border-t border-line-strong bg-surface-2/40 font-semibold dark:bg-surface-3/30" data-totals>
                  <th scope="row" class="px-4 py-2.5 text-left text-fg">{{ t("finance.budgets.total") }}</th>
                  <td class="px-3 py-2.5 text-right tabular-nums text-fg"><MoneyText :value="totalBudget" decimals="never" /></td>
                  <td class="px-3 py-2.5 text-right tabular-nums text-fg"><MoneyText :value="totalActual" decimals="never" /></td>
                  <td class="px-3 py-2.5">
                    <div v-if="totalShare !== null" class="flex items-center gap-2">
                      <ProgressBar :value="totalShare * 100" :max="100" size="sm" :tone="BUDGET_TONES[totalStatus]" :target="pace ?? undefined" class="min-w-0 flex-1" />
                      <span class="w-12 shrink-0 text-right text-xs tabular-nums text-muted">{{ percent(totalShare) }}</span>
                    </div>
                  </td>
                  <td class="px-4 py-2.5 text-right tabular-nums">
                    <template v-if="anyBudget && totalLeft !== null">
                      <span v-if="dec(totalLeft).isNegative()" class="text-danger">{{ t("finance.budgets.over", { amount: fmt.money(dec(totalLeft).abs().toFixed(2), undefined, { decimals: "never" }) }) }}</span>
                      <span v-else class="text-fg"><MoneyText :value="totalLeft" decimals="never" /></span>
                    </template>
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
          <p v-if="pace !== null" class="border-t border-line px-4 py-2 text-xs text-muted">
            <span class="mr-1.5 inline-block h-2.5 w-px translate-y-0.5 bg-fg/60" aria-hidden="true" />{{ t("finance.budgets.paceLegend", { percent: shareText(pace, fmt.lang.value) }) }}
          </p>
        </div>
      </template>
    </div>

    <StickyActionBar v-if="canManage" :show="dirty" :message="t('finance.budgets.unsaved', { n: changes.length }, changes.length)">
      <UiButton variant="ghost" @click="clearDrafts">{{ t("common.discard") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-save @click="save">{{ t("common.save") }}</UiButton>
    </StickyActionBar>
  </div>
</template>
