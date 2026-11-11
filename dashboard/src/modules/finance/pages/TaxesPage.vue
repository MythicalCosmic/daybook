<script setup lang="ts">
/**
 * The tax calendar (v12): every deadline of the company's regime and what it has (payroll,
 * premises, land), upcoming first, with what to do (file, pay, both), an estimate from the books
 * and how it is worked out, the law it comes from, and "Mark paid" / "Mark filed". As a list by
 * month or as a month view. Beside it: turnover tax or VAT on the last twelve months. Everywhere:
 * "Check with your accountant".
 */
import { AlertTriangle, BookOpen, CalendarDays, CalendarRange, Check, ExternalLink, List, Repeat, Settings2, Undo2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import CalendarMonth from "@/components/CalendarMonth.vue";
import { monthOf } from "@/components/calendar";
import type { CalendarItem } from "@/components/calendarItems";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { addDays } from "@/lib/dates";
import { sum } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { useRefresh } from "../api";
import TaxCompareCard from "../components/taxes/TaxCompareCard.vue";
import TaxMarkDialog from "../components/taxes/TaxMarkDialog.vue";
import { creditApi, deadlinesByMonth, deadlinesInOrder, TAX_TONES, useTaxCalendar, type TaxDeadline } from "../credit";

const { t } = useI18n();
const fmt = useFormat();
const cid = useCompanyId();
const company = useCompanyStore();
const refresh = useRefresh();
const confirm = useConfirm();
const canMark = computed(() => company.can("finance.record"));
const canManage = computed(() => company.can("finance.manage"));

const query = useTaxCalendar();
const data = computed(() => query.data.value ?? null);
const view = useRouteState<"list" | "month">("view", rs.enum(["list", "month"] as const, "list"));
const focus = useRouteState("deadline", rs.string(""));

const upcoming = computed(() => deadlinesInOrder((data.value?.deadlines ?? []).filter((row) => row.status !== "done" || row.due_on >= (data.value?.today ?? ""))));
const groups = computed(() => deadlinesByMonth(upcoming.value.filter((row) => row.status !== "overdue")));
const overdue = computed(() => upcoming.value.filter((row) => row.status === "overdue"));
const done = computed(() => deadlinesInOrder((data.value?.deadlines ?? []).filter((row) => row.status === "done" && row.due_on < (data.value?.today ?? ""))));
const showDone = ref(false);

const kpis = computed(() => {
  const d = data.value;
  const next = upcoming.value.find((row) => row.status === "due");
  const soon = d ? upcoming.value.filter((row) => row.status === "due" && row.due_on <= addDays(d.today, 30)) : [];
  return [
    { id: "next", label: t("finance.taxes.kpi.next"), value: next?.estimate ?? null, format: "money" as const, compact: true, icon: CalendarDays, hint: next ? `${next.tax_name} · ${fmt.day(next.due_on, "long")}` : t("finance.taxes.kpi.nothing") },
    { id: "soon", label: t("finance.taxes.kpi.soon"), value: d ? sum(soon.map((row) => row.estimate)) : null, format: "money" as const, compact: true, icon: CalendarRange, hint: t("finance.taxes.kpi.soonHint", { n: soon.length }, soon.length) },
    { id: "late", label: t("finance.taxes.kpi.late"), value: overdue.value.length, format: "number" as const, icon: AlertTriangle, hint: overdue.value.length ? t("finance.taxes.kpi.lateHint") : t("finance.taxes.kpi.onTime") },
  ];
});

// The month view -----------------------------------------------------------------------------------

const month = ref(monthOf(new Date().toISOString().slice(0, 10)));
watch(
  () => data.value?.today,
  (day) => day && (month.value = monthOf(day)),
  { immediate: true },
);
const selectedDay = ref<string | null>(null);
const COLORS = { done: "var(--c-success)", overdue: "var(--c-danger)", due: "var(--c-warning)" } as const;
const items = computed<CalendarItem[]>(() =>
  (data.value?.deadlines ?? []).map((row) => ({ id: row.key, kind: row.tax, title: `${row.tax_name}: ${row.period_label}`, start: row.due_on, all_day: true, color: COLORS[row.status], subtitle: row.action_label })),
);
const byKey = computed(() => new Map((data.value?.deadlines ?? []).map((row) => [row.key, row] as const)));
function openItem(item: CalendarItem): void {
  const row = byKey.value.get(String(item.id));
  if (row) focusRow(row);
}

// Marks ------------------------------------------------------------------------------------------

const marking = ref<TaxDeadline | null>(null);
const markOpen = ref(false);
function mark(row: TaxDeadline): void {
  marking.value = row;
  markOpen.value = true;
}
async function unmark(row: TaxDeadline): Promise<void> {
  if (!row.mark_id) return;
  const answer = await confirm({ title: t("finance.taxes.unmarkTitle"), message: t("finance.taxes.unmarkBody"), confirmLabel: t("common.undo"), tone: "danger" });
  if (!answer) return;
  try {
    await creditApi.unmark(cid.value, row.mark_id);
    toast.success(t("finance.taxes.unmarked"));
    refresh();
  } catch {
    // The HTTP layer said why.
  }
}

function focusRow(row: TaxDeadline): void {
  view.value = "list";
  focus.value = row.key;
  requestAnimationFrame(() => {
    const el = document.querySelector<HTMLElement>(`[data-deadline="${CSS.escape(row.key)}"]`);
    if (typeof el?.scrollIntoView === "function") el.scrollIntoView({ block: "center", behavior: "smooth" });
  });
}
watch(
  () => [focus.value, data.value] as const,
  ([key, loaded]) => {
    if (!key || !loaded) return;
    const row = byKey.value.get(key);
    if (row && row.status === "done" && row.due_on < loaded.today) showDone.value = true;
  },
  { immediate: true },
);

const monthTitle = (value: string) => fmt.day(`${value}-01`, "monthYear");
const day = (row: TaxDeadline) => Number(row.due_on.slice(8, 10));
const weekday = (row: TaxDeadline) => fmt.day(row.due_on, "weekdayShort");
const profile = computed(() => {
  const p = data.value?.profile;
  if (!p) return [];
  return [
    { key: "payroll", on: p.payroll, label: t("finance.taxes.profile.payroll") },
    { key: "property", on: p.property, label: t("finance.taxes.profile.property") },
    { key: "land", on: p.land, label: t("finance.taxes.profile.land") },
  ];
});
</script>

<template>
  <div>
    <PageHeader :title="t('finance.nav.taxes')" :description="t('finance.taxes.description')">
      <template #actions>
        <SegmentedControl
          v-model="view"
          size="sm"
          :aria-label="t('finance.taxes.view')"
          :options="[
            { value: 'list', label: t('finance.taxes.list'), icon: List },
            { value: 'month', label: t('finance.taxes.month'), icon: CalendarDays },
          ]"
        />
      </template>
    </PageHeader>

    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else class="flex flex-col gap-4">
      <InlineAlert v-for="warning in data?.warnings ?? []" :key="warning" tone="danger" :icon="AlertTriangle" :title="t('finance.taxes.regimeWarning')" :description="warning" data-regime-warning />

      <KpiStrip :items="kpis" :loading="query.isPending.value" :columns="3" phone="grid" />

      <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,360px)]">
        <div class="flex min-w-0 flex-col gap-4">
          <!-- What decides the calendar. -->
          <div v-if="data" class="ui-card flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 text-sm">
            <span class="text-muted">{{ t("finance.taxes.regime") }}</span>
            <StatusPill tone="primary" size="sm" :label="data.regime_label" />
            <span v-for="item in profile" :key="item.key" :class="['inline-flex items-center gap-1 text-xs', item.on ? 'text-fg' : 'text-subtle line-through']">
              <Check v-if="item.on" :size="12" class="text-success" aria-hidden="true" />{{ item.label }}
            </span>
            <span class="flex-1" />
            <RouterLink v-if="canManage" :to="`/c/${cid}/settings/finance`" class="inline-flex items-center gap-1 text-xs font-semibold text-accent-fg hover:underline"><Settings2 :size="13" aria-hidden="true" />{{ t("finance.taxes.change") }}</RouterLink>
          </div>

          <div v-if="query.isPending.value" class="flex flex-col gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="140px" radius="14px" /></div>

          <template v-else-if="data && view === 'month'">
            <div class="ui-card p-2">
              <CalendarMonth v-model:month="month" v-model:selected="selectedDay" :items="items" :max-per-day="3" @item-click="openItem" />
            </div>
          </template>

          <template v-else-if="data">
            <EmptyState v-if="!data.deadlines.length" class="ui-card" :icon="CalendarDays" :title="t('finance.taxes.emptyTitle')" :description="t('finance.taxes.emptyBody')" />

            <section v-if="overdue.length" class="ui-card overflow-hidden ring-1 ring-danger/40" :aria-label="t('finance.taxes.overdue')">
              <header class="border-b border-line bg-danger-soft/60 px-4 py-2.5 text-sm font-semibold text-danger">{{ t("finance.taxes.overdue") }}</header>
              <ul class="flex flex-col divide-y divide-line">
                <template v-for="row in overdue" :key="row.key">
                  <li :class="['flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3', focus === row.key && 'bg-accent-soft/40']" :data-deadline="row.key">
                    <div class="flex w-12 shrink-0 flex-col items-center rounded-[10px] bg-danger-soft py-1 text-danger">
                      <span class="text-lg font-semibold leading-none tabular-nums">{{ day(row) }}</span>
                      <span class="text-[10px] uppercase">{{ fmt.day(row.due_on, "monthYear").split(" ")[0] }}</span>
                    </div>
                    <div class="min-w-0 flex-1 basis-56">
                      <p class="text-sm font-semibold text-fg">{{ row.name }}</p>
                      <p class="text-xs text-muted">{{ row.period_label }} · {{ row.action_label }}</p>
                    </div>
                    <span v-if="row.estimate" class="text-sm font-semibold tabular-nums text-fg"><template v-if="!row.booked">≈ </template><MoneyText :value="row.estimate" :currency="row.currency" decimals="never" /></span>
                    <UiButton v-if="canMark" size="sm" variant="primary" @click="mark(row)">{{ row.action === "file" ? t("finance.taxes.markFiled") : t("finance.taxes.markPaid") }}</UiButton>
                  </li>
                </template>
              </ul>
            </section>

            <section v-for="group in groups" :key="group.month" class="ui-card overflow-hidden" :aria-label="monthTitle(group.month)">
              <header class="flex items-center gap-2 border-b border-line px-4 py-2.5">
                <h2 class="min-w-0 flex-1 text-sm font-semibold capitalize text-fg">{{ monthTitle(group.month) }}</h2>
                <span class="text-xs text-muted">{{ t("finance.taxes.count", { n: group.rows.length }, group.rows.length) }}</span>
              </header>
              <ul class="flex flex-col divide-y divide-line">
                <li v-for="row in group.rows" :key="row.key" :class="['flex flex-wrap items-start gap-x-4 gap-y-2 px-4 py-3', focus === row.key && 'bg-accent-soft/40', row.status === 'done' && 'opacity-70']" :data-deadline="row.key">
                  <div :class="['flex w-12 shrink-0 flex-col items-center rounded-[10px] py-1', row.status === 'done' ? 'bg-success-soft text-success' : 'bg-surface-2 text-fg']">
                    <span class="text-lg font-semibold leading-none tabular-nums">{{ day(row) }}</span>
                    <span class="text-[10px] uppercase text-muted">{{ weekday(row) }}</span>
                  </div>
                  <div class="min-w-0 flex-1 basis-56">
                    <p class="flex flex-wrap items-center gap-1.5 text-sm font-semibold text-fg">
                      {{ row.name }}
                      <StatusPill v-if="row.rate" tone="neutral" variant="outline" size="sm" :label="`${row.rate.replace(/\.?0+$/, '')} %`" />
                    </p>
                    <p class="text-xs text-muted">{{ row.period_label }} · {{ row.action_label }}</p>
                    <p v-if="row.basis" class="mt-0.5 text-xs text-subtle">{{ row.basis }}</p>
                    <p v-if="row.note" class="mt-0.5 text-xs text-subtle">{{ row.note }}</p>
                    <p class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-subtle">
                      <a :href="row.url" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 hover:text-fg hover:underline"><BookOpen :size="11" aria-hidden="true" />{{ row.law }}<ExternalLink :size="10" aria-hidden="true" /></a>
                      <RouterLink v-if="row.rule_id" :to="`/c/${cid}/finance/recurring?rule=${row.rule_id}`" class="inline-flex items-center gap-1 hover:text-fg hover:underline"><Repeat :size="11" aria-hidden="true" />{{ t("finance.taxes.byRule") }}</RouterLink>
                    </p>
                  </div>
                  <div class="flex shrink-0 flex-col items-end gap-1.5 max-sm:w-full max-sm:flex-row max-sm:items-center max-sm:justify-between">
                    <span v-if="row.status === 'done' && row.paid" class="text-sm font-semibold tabular-nums text-fg"><MoneyText :value="row.paid" :currency="row.currency" decimals="never" /></span>
                    <span v-else-if="row.estimate" class="text-sm font-semibold tabular-nums text-fg" :title="row.booked ? t('finance.taxes.booked') : t('finance.taxes.estimate')"><template v-if="!row.booked">≈ </template><MoneyText :value="row.estimate" :currency="row.currency" decimals="never" /></span>
                    <div class="flex items-center gap-1.5">
                      <StatusPill :tone="TAX_TONES[row.status]" size="sm" :label="row.status === 'done' ? (row.action === 'file' ? t('finance.taxes.filed') : t('finance.taxes.paid')) : t(`finance.taxes.status.${row.status}`)" />
                      <UiButton v-if="canMark && row.status !== 'done'" size="sm" variant="secondary" :data-mark="row.key" @click="mark(row)">{{ row.action === "file" ? t("finance.taxes.markFiled") : t("finance.taxes.markPaid") }}</UiButton>
                      <UiButton v-else-if="canManage && row.mark_id" size="sm" variant="ghost" :icon="Undo2" @click="unmark(row)">{{ t("common.undo") }}</UiButton>
                    </div>
                  </div>
                </li>
              </ul>
            </section>

            <section v-if="done.length" class="flex flex-col gap-2">
              <button type="button" class="inline-flex w-fit items-center gap-1.5 text-sm font-semibold text-muted hover:text-fg" :aria-expanded="showDone" @click="showDone = !showDone">
                <Check :size="14" aria-hidden="true" />{{ t("finance.taxes.doneCount", { n: done.length }, done.length) }}
              </button>
              <ul v-if="showDone" class="ui-card flex flex-col divide-y divide-line">
                <li v-for="row in done" :key="row.key" class="flex items-center gap-3 px-4 py-2 text-sm" :data-deadline="row.key">
                  <span class="w-20 shrink-0 tabular-nums text-muted">{{ fmt.day(row.due_on, "medium") }}</span>
                  <span class="min-w-0 flex-1 truncate text-fg">{{ row.name }} · {{ row.period_label }}</span>
                  <span v-if="row.paid" class="tabular-nums text-muted"><MoneyText :value="row.paid" :currency="row.currency" decimals="never" /></span>
                  <UiButton v-if="canManage && row.mark_id" size="sm" variant="ghost" :icon="Undo2" @click="unmark(row)">{{ t("common.undo") }}</UiButton>
                </li>
              </ul>
            </section>
          </template>
        </div>

        <aside class="flex min-w-0 flex-col gap-4">
          <TaxCompareCard />
          <div v-if="data" class="ui-card flex flex-col gap-2 p-4 text-xs text-muted" data-tax-sources>
            <p class="font-semibold text-warning">{{ data.disclaimer }}</p>
            <p>{{ t("finance.taxes.sourcesNote", { date: fmt.day(data.checked_on, "long"), days: data.remind_days }) }}</p>
            <ul class="flex flex-col gap-1">
              <li v-for="source in data.sources" :key="source.url">
                <a :href="source.url" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 text-accent-fg hover:underline">{{ source.label }}<ExternalLink :size="10" aria-hidden="true" /></a>
              </li>
            </ul>
          </div>
        </aside>
      </div>
    </div>

    <TaxMarkDialog v-if="marking" v-model:open="markOpen" :deadline="marking" />
  </div>
</template>
