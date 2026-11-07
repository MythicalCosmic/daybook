<script setup lang="ts">
/**
 * Recurring payments (plan §1.6 "recurring bills as reminders or auto-posted", "tax calendar";
 * §6.2 "recurring rules, the tax calendar templates"): every rule with its schedule, the next due
 * day (overdue ones marked), the amount or "changes each time", and what can be done with it: pay
 * a bill's open occurrence, skip it, post an automatic one now, edit, switch off. Tabs split bills,
 * automatic entries and taxes; the tax calendar card adds a regime's taxes in one go. `?rule=12`
 * (links from the calendar, reminders and the inbox) opens that rule: its payment when a bill is
 * open and the viewer may pay, else its editor for someone who manages finance.
 */
import { Ban, CalendarClock, MoreHorizontal, Pencil, Play, Plus, Power, Repeat, SkipForward, Wallet } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DataTable from "@/components/DataTable.vue";
import DropdownMenu from "@/components/DropdownMenu.vue";
import type { MenuEntry } from "@/components/menuTypes";
import EmptyState from "@/components/EmptyState.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { dec } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { financeApi, useRecurring, useRefresh } from "../api";
import RecurringRuleDialog from "../components/RecurringRuleDialog.vue";
import RulePayDialog from "../components/RulePayDialog.vue";
import TaxCalendarCard from "../components/TaxCalendarCard.vue";
import { colorFor, dayStyle, ruleGroup, scheduleText, type RuleGroup } from "../lib";
import type { RecurringRule } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const cid = useCompanyId();
const confirm = useConfirm();
const refresh = useRefresh();
const canManage = computed(() => company.can("finance.manage"));
const canPay = computed(() => company.can("finance.record"));

const tab = useRouteState<"all" | RuleGroup>("tab", rs.enum(["all", "bill", "auto", "tax"] as const, "all"));
const showOff = useRouteState("off", rs.boolean(false));
const focus = useRouteState("rule", rs.optionalNumber());
const query = useRecurring(() => ({ active: showOff.value ? "all" : "true" }));
const rules = computed(() => query.data.value ?? []);
const shown = computed(() => (tab.value === "all" ? rules.value : rules.value.filter((rule) => ruleGroup(rule) === tab.value)));
const count = (group: RuleGroup) => rules.value.filter((rule) => ruleGroup(rule) === group).length;
const tabs = computed(() => [
  { id: "all", label: t("finance.recurring.tab.all"), icon: Repeat, count: query.data.value ? rules.value.length : undefined },
  { id: "bill", label: t("finance.recurring.tab.bill"), count: query.data.value ? count("bill") : undefined },
  { id: "auto", label: t("finance.recurring.tab.auto"), count: query.data.value ? count("auto") : undefined },
  { id: "tax", label: t("finance.recurring.tab.tax"), count: query.data.value ? count("tax") : undefined },
]);
const overdue = computed(() => rules.value.filter((rule) => rule.is_active && rule.overdue));

const table = useDataTable({ id: "finance.recurring" });
const columns = computed<TableColumn<RecurringRule>[]>(() => [
  { id: "name", header: t("finance.recurring.field.name"), minWidth: 220, sticky: true, hideable: false, value: (row) => row.name },
  { id: "schedule", header: t("finance.recurring.schedule"), width: 190, value: (row) => schedule(row) },
  { id: "next", header: t("finance.recurring.next"), width: 150, value: (row) => row.next_due_on ?? "" },
  { id: "amount", header: t("finance.field.amount"), numeric: true, width: 140, value: (row) => row.amount },
  { id: "account", header: t("finance.field.account"), width: 150, value: (row) => row.account?.name ?? "" },
  { id: "actions", header: "", width: 168, hideable: false, align: "end", value: () => "" },
]);

function schedule(rule: RecurringRule): string {
  return scheduleText(rule, t, (day) => fmt.day(day, "short"));
}
const isOpenBill = (rule: RecurringRule) => rule.is_active && rule.mode === "bill" && !!rule.next_due_on;
const canRun = (rule: RecurringRule) => canManage.value && rule.is_active && rule.mode === "auto" && !!rule.next_due_on;

// Dialogs ----------------------------------------------------------------------------------

const editing = ref<RecurringRule | null>(null);
const editOpen = ref(false);
const paying = ref<RecurringRule | null>(null);
const payOpen = ref(false);

function create(): void {
  editing.value = null;
  editOpen.value = true;
}
function edit(rule: RecurringRule): void {
  if (!canManage.value) return;
  editing.value = rule;
  editOpen.value = true;
}
function pay(rule: RecurringRule): void {
  paying.value = rule;
  payOpen.value = true;
}

// A link to one rule opens what it is for, once the list has it.
watch(
  [focus, () => query.data.value],
  ([id, list]) => {
    if (!id || !list) return;
    const rule = list.find((row) => row.id === id);
    if (!rule && !showOff.value) {
      showOff.value = true;
      return;
    }
    focus.value = null;
    if (!rule) return;
    if (isOpenBill(rule) && canPay.value) pay(rule);
    else if (canManage.value) edit(rule);
  },
  { immediate: true },
);

// Actions ----------------------------------------------------------------------------------

async function skip(rule: RecurringRule): Promise<void> {
  const answer = await confirm({
    title: t("finance.recurring.skipTitle"),
    message: t("finance.recurring.skipBody", { date: rule.next_due_on ? fmt.day(rule.next_due_on, "long") : "—" }),
    confirmLabel: t("finance.recurring.skip"),
    onConfirm: () => financeApi.skipRecurring(cid.value, rule.id, rule.next_due_on),
  });
  if (!answer) return;
  toast.success(t("finance.recurring.skipped"));
  refresh();
}

async function runNow(rule: RecurringRule): Promise<void> {
  const answer = await confirm({
    title: t("finance.recurring.runTitle"),
    message: t("finance.recurring.runBody", { amount: fmt.money(rule.amount, rule.currency), account: rule.account?.name ?? "—" }),
    confirmLabel: t("finance.recurring.runNow"),
    onConfirm: () => financeApi.runRecurring(cid.value, rule.id, rule.next_due_on),
  });
  if (!answer) return;
  toast.success(t("finance.recurring.posted", { name: rule.name }));
  refresh();
}

async function switchOff(rule: RecurringRule): Promise<void> {
  const answer = await confirm({
    title: t("finance.recurring.offTitle", { name: rule.name }),
    message: t("finance.recurring.offBody"),
    tone: "danger",
    confirmLabel: t("finance.recurring.switchOff"),
    onConfirm: () => financeApi.stopRecurring(cid.value, rule.id),
  });
  if (!answer) return;
  toast.success(t("finance.recurring.switchedOff"));
  refresh();
}

async function switchOn(rule: RecurringRule): Promise<void> {
  try {
    await financeApi.updateRecurring(cid.value, rule.id, { is_active: true });
    toast.success(t("finance.recurring.switchedOn"));
    refresh();
  } catch {
    // The HTTP layer has said what went wrong.
  }
}

function menu(rule: RecurringRule): MenuEntry[] {
  const items: MenuEntry[] = [];
  if (canManage.value) items.push({ label: t("common.edit"), icon: Pencil, onSelect: () => edit(rule) });
  if (canManage.value && isOpenBill(rule)) items.push({ label: t("finance.recurring.skip"), icon: SkipForward, onSelect: () => void skip(rule) });
  if (canRun(rule)) items.push({ label: t("finance.recurring.runNow"), icon: Play, onSelect: () => void runNow(rule) });
  if (canManage.value) {
    items.push({ type: "separator" });
    items.push(
      rule.is_active
        ? { label: t("finance.recurring.switchOff"), icon: Ban, danger: true, onSelect: () => void switchOff(rule) }
        : { label: t("finance.recurring.switchOn"), icon: Power, onSelect: () => void switchOn(rule) },
    );
  }
  return items;
}

function amountKnown(rule: RecurringRule): boolean {
  return !dec(rule.amount).isZero();
}
const emptyTitle = computed(() => (tab.value === "tax" ? t("finance.recurring.emptyTax") : t("finance.recurring.emptyTitle")));
</script>

<template>
  <div>
    <PageHeader v-model:tab="tab" :title="t('finance.nav.recurring')" :description="t('finance.recurring.description')" :tabs="tabs">
      <template #actions>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" data-new-rule @click="create">{{ t("finance.recurring.new") }}</UiButton>
      </template>
    </PageHeader>

    <div class="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div class="flex min-w-0 flex-col gap-3">
        <InlineAlert
          v-if="overdue.length"
          tone="danger"
          size="sm"
          :title="t('finance.recurring.overdueTitle', { n: overdue.length }, overdue.length)"
          :description="overdue.map((rule) => rule.name).join(', ')"
        />
        <DataTable
          :state="table"
          :columns="columns"
          :rows="shown"
          row-key="id"
          :loading="query.isPending.value"
          :fetching="query.isFetching.value"
          :error="query.error.value"
          :retry="() => query.refetch()"
          :clickable="canManage"
          hide-pagination
          :row-class="(row) => (row.is_active ? undefined : 'opacity-60')"
          @row-click="edit"
        >
          <template #toolbar>
            <span class="flex-1" />
            <ToggleSwitch v-model="showOff" size="sm" :label="t('finance.recurring.showOff')" />
          </template>
          <template #empty>
            <EmptyState :icon="CalendarClock" :title="emptyTitle" :description="t('finance.recurring.emptyBody')">
              <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="create">{{ t("finance.recurring.new") }}</UiButton>
            </EmptyState>
          </template>
          <template #cell-name="{ row }">
            <div class="flex min-w-0 items-center gap-2.5">
              <span class="size-2 shrink-0 rounded-full" :style="{ background: colorFor(row.category.id, row.category.color) }" aria-hidden="true" />
              <div class="min-w-0">
                <p class="flex min-w-0 items-center gap-1.5">
                  <span class="truncate text-base font-medium text-fg" :title="row.name">{{ row.name }}</span>
                  <StatusPill v-if="row.is_tax" tone="info" size="sm" variant="outline" :label="t('finance.recurring.taxPill')" />
                  <StatusPill v-else-if="row.mode === 'auto'" tone="primary" size="sm" variant="outline" :label="t('finance.recurring.autoPill')" />
                  <StatusPill v-if="!row.is_active" tone="neutral" size="sm" :label="t('finance.recurring.offPill')" />
                </p>
                <p class="truncate text-xs text-muted" :title="row.counterparty?.name ?? row.category.name">{{ row.counterparty?.name ?? row.category.name }}<template v-if="row.kind === 'income'"> · {{ t("finance.quick.mode.income") }}</template></p>
              </div>
            </div>
          </template>
          <template #cell-schedule="{ row }"><span class="truncate text-sm text-fg" :title="schedule(row)">{{ schedule(row) }}</span></template>
          <template #cell-next="{ row }">
            <div v-if="row.next_due_on" class="flex min-w-0 flex-col">
              <span :class="['text-sm', row.overdue ? 'font-semibold text-danger' : 'text-fg']">{{ fmt.day(row.next_due_on, dayStyle(row.next_due_on)) }}</span>
              <StatusPill v-if="row.overdue" tone="danger" size="sm" class="mt-0.5 self-start" :label="t('finance.recurring.overdue')" />
            </div>
            <span v-else class="text-sm text-subtle">{{ t("finance.recurring.finished") }}</span>
          </template>
          <template #cell-amount="{ row }">
            <span v-if="row.amount_varies && !amountKnown(row)" class="text-sm text-muted">{{ t("finance.recurring.varies") }}</span>
            <span v-else class="text-sm font-semibold tabular-nums text-fg" :title="row.amount_varies ? t('finance.recurring.usualHint') : undefined">
              <template v-if="row.amount_varies">≈ </template><MoneyText :value="row.amount" :currency="row.currency" decimals="never" />
            </span>
          </template>
          <template #cell-account="{ row }"><span class="truncate text-sm text-muted">{{ row.account?.name ?? "—" }}</span></template>
          <template #cell-actions="{ row }">
            <div class="flex items-center justify-end gap-1">
              <UiButton v-if="isOpenBill(row) && canPay" size="sm" :variant="row.overdue ? 'primary' : 'secondary'" :icon="Wallet" data-pay @click="pay(row)">
                {{ row.kind === "income" ? t("finance.recurring.markReceived") : t("finance.recurring.pay") }}
              </UiButton>
              <UiButton v-else-if="canRun(row)" size="sm" variant="secondary" :icon="Play" data-run @click="runNow(row)">{{ t("finance.recurring.runNow") }}</UiButton>
              <DropdownMenu v-if="menu(row).length" :items="menu(row)" width="220px">
                <template #trigger>
                  <IconButton :icon="MoreHorizontal" :label="t('finance.recurring.actions', { name: row.name })" size="sm" />
                </template>
              </DropdownMenu>
            </div>
          </template>
          <template #card="{ row }">
            <div class="flex items-start gap-3">
              <span class="mt-1.5 size-2 shrink-0 rounded-full" :style="{ background: colorFor(row.category.id, row.category.color) }" aria-hidden="true" />
              <div class="min-w-0 flex-1">
                <p class="truncate text-base font-semibold text-fg">{{ row.name }}</p>
                <p class="truncate text-xs text-muted">{{ schedule(row) }}</p>
                <p v-if="row.next_due_on" :class="['text-xs', row.overdue ? 'font-semibold text-danger' : 'text-muted']">
                  {{ t("finance.recurring.nextOn", { date: fmt.day(row.next_due_on, "weekdayShort") }) }}<template v-if="row.overdue"> · {{ t("finance.recurring.overdue") }}</template>
                </p>
              </div>
              <div class="flex shrink-0 flex-col items-end gap-1.5">
                <span v-if="row.amount_varies && !amountKnown(row)" class="text-sm text-muted">{{ t("finance.recurring.varies") }}</span>
                <span v-else class="text-sm font-semibold tabular-nums text-fg"><MoneyText :value="row.amount" :currency="row.currency" decimals="never" compact /></span>
                <UiButton v-if="isOpenBill(row) && canPay" size="sm" variant="secondary" @click.stop="pay(row)">{{ row.kind === "income" ? t("finance.recurring.markReceived") : t("finance.recurring.pay") }}</UiButton>
              </div>
            </div>
          </template>
        </DataTable>
      </div>

      <TaxCalendarCard class="self-start" />
    </div>

    <RecurringRuleDialog v-if="canManage" v-model:open="editOpen" :rule="editing" />
    <RulePayDialog v-if="paying" v-model:open="payOpen" :rule="paying" />
  </div>
</template>
