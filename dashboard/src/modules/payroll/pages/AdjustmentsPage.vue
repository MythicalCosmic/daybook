<script setup lang="ts">
/**
 * Bonuses and fines (plan §6.2 "proposed inbox, disputes with answer box, bulk approve, Give bonus
 * dialog"): tabs for proposed, approved, rejected and disputed ones; where each came from (by hand,
 * a rule, a task, attendance); approve or reject one or many; answer a dispute; give a bonus or
 * record a fine (`?new=bonus|fine` from the palette). A row opens its drawer on `?adjustment=`.
 */
import { CalendarRange, Check, Gift, MessageCircleWarning, Rows3, Scale, Sparkles, X } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import ApproveRejectButtons from "@/components/ApproveRejectButtons.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { payrollApi, useAdjustments, useRefresh } from "../api";
import AdjustmentDrawer from "../components/AdjustmentDrawer.vue";
import PayAmount from "../components/PayAmount.vue";
import ProposeDialog from "../components/ProposeDialog.vue";
import SourceLabel from "../components/SourceLabel.vue";
import { ADJUSTMENT_TONES, bulkOutcome, bulkPlan, isAddition, isDecidable, periodOf, shiftPeriod, signedAmount } from "../lib";
import type { Adjustment, AdjustmentKind } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();
const canManage = computed(() => company.can("payroll.manage"));
const canPropose = computed(() => company.can(["payroll.propose", "payroll.manage"]));

const TABS = ["proposed", "approved", "rejected", "disputed"] as const;
type Tab = (typeof TABS)[number];
const tab = useRouteState<Tab>("tab", rs.enum(TABS, "proposed"));

const current = computed(() => periodOf(todayIn(company.timezone)));
const defs = computed<FilterDef[]>(() => [
  {
    key: "period",
    label: t("payroll.adjustments.month"),
    type: "select",
    icon: CalendarRange,
    options: [0, -1, -2, -3, -4, -5, 1].map((shift) => {
      const value = shiftPeriod(current.value, shift);
      return { value, label: fmt.day(value, "monthYear") };
    }),
  },
  {
    key: "kind",
    label: t("payroll.adjustments.kind"),
    type: "multi",
    icon: Rows3,
    options: (["bonus", "fine", "allowance", "deduction"] as const).map((kind) => ({ value: kind, label: t(`payroll.adjustmentKind.${kind}`) })),
  },
  {
    key: "source",
    label: t("payroll.adjustments.source"),
    type: "multi",
    icon: Sparkles,
    options: (["manual", "rule", "task", "attendance", "discipline"] as const).map((source) => ({ value: source, label: t(`payroll.source.${source}`) })),
  },
]);
const filters = useUrlFilters(defs);
const search = useRouteState("q", rs.string(""));
const table = useDataTable({ id: "payroll.adjustments", url: true });
table.resetPageOn(() => [filters.params.value, search.value, tab.value]);

const tabParams = (value: Tab) => (value === "disputed" ? { disputed: "true" } : { status: value });
const params = computed(() => ({ ...tabParams(tab.value), ...filters.params.value, ...(search.value ? { q: search.value } : {}), ...table.params.value }));
const list = useAdjustments(params);
const proposedCount = useAdjustments(() => ({ status: "proposed", page_size: 1 }));
const disputedCount = useAdjustments(() => ({ disputed: "open", page_size: 1 }));
const rows = computed(() => list.data.value?.results ?? []);
const filtered = computed(() => filters.active.value > 0 || !!search.value);

const tabs = computed(() => [
  { id: "proposed", label: t("payroll.adjustments.tab.proposed"), count: proposedCount.data.value?.count },
  { id: "approved", label: t("payroll.adjustments.tab.approved") },
  { id: "rejected", label: t("payroll.adjustments.tab.rejected") },
  { id: "disputed", label: t("payroll.adjustments.tab.disputed"), count: disputedCount.data.value?.count || undefined },
]);

const selectable = computed(() => tab.value === "proposed" && canManage.value);
const columns = computed<TableColumn<Adjustment>[]>(() => [
  { id: "person", header: t("payroll.payslips.person"), minWidth: 200, sticky: true, hideable: false, value: (row) => row.member.name },
  { id: "amount", header: t("payroll.field.amount"), width: 150, numeric: true, value: (row) => row.amount ?? null },
  { id: "reason", header: t("payroll.adjustments.reason"), minWidth: 220, value: (row) => (tab.value === "disputed" ? row.dispute_text : row.reason) },
  { id: "source", header: t("payroll.adjustments.source"), width: 190, value: (row) => t(`payroll.source.${row.source}`) },
  { id: "period", header: t("payroll.adjustments.month"), width: 120, value: (row) => fmt.day(row.period, "monthYear") },
  ...(tab.value === "proposed" && canManage.value ? [{ id: "decide", header: "", width: 96, hideable: false, value: () => "" }] : [{ id: "status", header: t("payroll.payslips.status"), width: 130, value: (row: Adjustment) => t(`payroll.adjustmentStatus.${row.status}`) }]),
]);

function open(row: Adjustment): void {
  void router.push({ query: { ...route.query, adjustment: String(row.id) } });
}
const activeKey = computed(() => (typeof route.query.adjustment === "string" ? route.query.adjustment : null));

async function decide(row: Adjustment, decision: "approve" | "reject", reason = ""): Promise<void> {
  await payrollApi.decideAdjustment(company.currentId ?? 0, row.id, decision, reason);
  toast.success(decision === "approve" ? t("payroll.adjustments.approved") : t("payroll.adjustments.rejected"));
  refresh();
}

async function bulk(selected: string[], decision: "approve" | "reject", clear: () => void): Promise<void> {
  const count = bulkPlan(rows.value, selected, decision).ids.length;
  if (!count) return;
  const answer = await confirm({
    title: decision === "approve" ? t("payroll.adjustments.bulkApproveTitle", { n: count }, count) : t("payroll.adjustments.bulkRejectTitle", { n: count }, count),
    message: decision === "approve" ? t("payroll.adjustments.bulkApproveBody") : t("payroll.adjustments.bulkRejectBody"),
    confirmLabel: decision === "approve" ? t("common.approve") : t("common.reject"),
    tone: decision === "approve" ? "primary" : "danger",
    reason: decision === "reject" ? "required" : "none",
    reasonLabel: t("common.reason"),
    reasonPlaceholder: t("common.reasonPlaceholder"),
  });
  if (!answer) return;
  const plan = bulkPlan(rows.value, selected, decision, answer.reason);
  try {
    const outcome = bulkOutcome(await payrollApi.bulkDecide(company.currentId ?? 0, plan.body));
    const skipped = outcome.refused.length + plan.skipped.length;
    toast.success(t("payroll.adjustments.bulkDone", { n: outcome.decided }, outcome.decided));
    // What the server refused (decided meanwhile, locked…), in its own words when there is one.
    if (skipped) toast.info(outcome.refused.length === 1 && outcome.refused[0]!.error ? outcome.refused[0]!.error : t("payroll.adjustments.bulkSkipped", { n: skipped }, skipped));
    clear();
    refresh();
  } catch {
    // The HTTP layer said why.
  }
}

// "Give a bonus" / "Record a fine", also from the palette (?new=bonus|fine).
const proposeOpen = ref(false);
const proposeKind = ref<AdjustmentKind>("bonus");
function propose(kind: AdjustmentKind): void {
  proposeKind.value = kind;
  proposeOpen.value = true;
}
const newParam = useRouteState("new", rs.string(""));
watch(
  newParam,
  (value) => {
    if (!value) return;
    newParam.value = "";
    if (canPropose.value && (value === "bonus" || value === "fine" || value === "allowance" || value === "deduction")) propose(value);
  },
  { immediate: true },
);

const emptyText = computed(() => {
  if (filtered.value) return { title: t("payroll.adjustments.noMatch"), body: t("payroll.adjustments.noMatchBody") };
  return { title: t(`payroll.adjustments.empty.${tab.value}`), body: t(`payroll.adjustments.emptyBody.${tab.value}`) };
});
</script>

<template>
  <div>
    <PageHeader v-model:tab="tab" :title="t('payroll.nav.adjustments')" :description="t('payroll.adjustments.description')" :tabs="tabs">
      <template v-if="canPropose" #actions>
        <UiButton :icon="Scale" data-testid="new-fine" @click="propose('fine')">{{ t("payroll.adjustments.newFine") }}</UiButton>
        <UiButton variant="primary" :icon="Gift" data-testid="new-bonus" @click="propose('bonus')">{{ t("payroll.adjustments.newBonus") }}</UiButton>
      </template>
    </PageHeader>

    <DataTable
      :state="table"
      :columns="columns"
      :rows="rows"
      :total="list.data.value?.count"
      row-key="id"
      :loading="list.isPending.value"
      :fetching="list.isFetching.value"
      :error="list.error.value"
      :retry="() => list.refetch()"
      clickable
      :selectable="selectable"
      :active-key="activeKey"
      :filtered="filtered"
      :row-class="(row: Adjustment) => (isDecidable(row) || tab !== 'proposed' ? undefined : 'opacity-60')"
      csv-name="bonuses-fines"
      @row-click="open"
      @clear-filters="
        filters.clear();
        search = '';
      "
    >
      <template #toolbar>
        <FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable :search-placeholder="t('payroll.adjustments.searchPlaceholder')" />
      </template>
      <template #bulk="{ selected, clear }">
        <UiButton size="sm" variant="primary" :icon="Check" data-testid="bulk-approve" @click="bulk(selected, 'approve', clear)">{{ t("payroll.adjustments.approveSome", { n: selected.length }, selected.length) }}</UiButton>
        <UiButton size="sm" variant="danger" :icon="X" data-testid="bulk-reject" @click="bulk(selected, 'reject', clear)">{{ t("payroll.adjustments.rejectSome", { n: selected.length }, selected.length) }}</UiButton>
      </template>
      <template #empty>
        <EmptyState :icon="tab === 'disputed' ? MessageCircleWarning : Gift" :tone="tab === 'proposed' || tab === 'disputed' ? 'success' : 'primary'" :title="emptyText.title" :description="emptyText.body">
          <UiButton v-if="!filtered && canPropose && tab !== 'disputed'" variant="primary" :icon="Gift" @click="propose('bonus')">{{ t("payroll.adjustments.newBonus") }}</UiButton>
        </EmptyState>
      </template>
      <template #cell-person="{ row }">
        <div class="flex min-w-0 items-center gap-2.5">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="30" />
          <div class="min-w-0">
            <p class="truncate text-base font-medium text-fg" :title="row.member.name">{{ row.member.name }}</p>
            <p class="truncate text-xs text-muted">{{ t(`payroll.adjustmentKind.${row.kind}`) }}<template v-if="row.member.position"> · {{ row.member.position }}</template></p>
          </div>
        </div>
      </template>
      <template #cell-amount="{ row }">
        <PayAmount cell strong :value="signedAmount(row)" :currency="row.currency" :sign="isAddition(row.kind) ? 'always' : 'auto'" colored />
      </template>
      <template #cell-reason="{ row }">
        <div class="min-w-0">
          <p class="truncate text-sm text-fg" :title="tab === 'disputed' ? row.dispute_text : row.reason">{{ tab === "disputed" ? row.dispute_text : row.reason }}</p>
          <p v-if="tab === 'disputed'" class="truncate text-xs text-muted">{{ row.dispute_answer ? t("payroll.adjustments.answered") : t("payroll.adjustments.waitingAnswer") }}</p>
        </div>
      </template>
      <template #cell-source="{ row }"><SourceLabel :row="row" /></template>
      <template #cell-period="{ row }"><span class="text-sm text-muted">{{ fmt.day(row.period, "monthYear") }}</span></template>
      <template #cell-status="{ row }">
        <StatusPill :tone="ADJUSTMENT_TONES[row.status]" size="sm" :label="t(`payroll.adjustmentStatus.${row.status}`)" />
      </template>
      <template #cell-decide="{ row }">
        <ApproveRejectButtons
          v-if="isDecidable(row)"
          compact
          :reject-title="t('payroll.adjustments.rejectTitle', { name: row.member.name })"
          :on-approve="() => decide(row, 'approve')"
          :on-reject="(reason: string) => decide(row, 'reject', reason)"
          @click.stop
        />
      </template>
      <template #card="{ row }">
        <div class="flex items-start gap-3">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="34" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
            <p class="line-clamp-2 text-sm text-fg">{{ tab === "disputed" ? row.dispute_text : row.reason }}</p>
            <p class="mt-0.5 truncate text-xs text-muted">{{ t(`payroll.adjustmentKind.${row.kind}`) }} · {{ fmt.day(row.period, "monthYear") }} · {{ t(`payroll.source.${row.source}`) }}</p>
          </div>
          <div class="flex shrink-0 flex-col items-end gap-1">
            <PayAmount cell strong :value="signedAmount(row)" :currency="row.currency" :sign="isAddition(row.kind) ? 'always' : 'auto'" colored />
            <StatusPill v-if="tab !== 'proposed'" :tone="ADJUSTMENT_TONES[row.status]" size="sm" :label="t(`payroll.adjustmentStatus.${row.status}`)" />
          </div>
        </div>
      </template>
    </DataTable>

    <AdjustmentDrawer />
    <ProposeDialog v-model:open="proposeOpen" :kind="proposeKind" />
  </div>
</template>
