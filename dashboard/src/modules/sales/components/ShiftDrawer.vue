<script setup lang="ts">
/**
 * The shift drawer (`?shift=1042`, plan §6.2 "Shift detail"): the four numbers that matter (net,
 * expected cash, counted, difference against the tolerance), what needs attention (disputed, AI
 * mismatch, forced close, a float that differed), then tabs: the Z-report and terminal photos
 * beside the typed totals and the AI reading, the cash formula with both banknote counts, the
 * movements and the timeline, and the audit history. Verify, dispute, correct and force-close in
 * the footer; `V` verifies and `D` disputes while it's open. The `sales.shift.detail` slot hosts
 * other modules' additions.
 */
import { AlertTriangle, CheckCircle2, CircleDot, Clock, History, LockKeyhole, Receipt, ShieldAlert, ShieldCheck, Sparkles, Wallet } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import AuditTrail from "@/components/AuditTrail.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TimelineList, { type TimelineEvent } from "@/components/TimelineList.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useHotkey } from "@/core/hotkeys";
import { dec, subtract, sum } from "@/lib/decimal";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { salesApi, useShift, useShiftWrite } from "../api";
import { DIFFERENCE_TONES, METHOD_ICONS, SHIFT_TONES, differenceClass, differenceLevel } from "../format";
import type { ShiftDetail } from "../types";
import CashCountBreakdown from "./CashCountBreakdown.vue";
import CorrectDialog from "./CorrectDialog.vue";
import ForceCloseDialog from "./ForceCloseDialog.vue";
import MovementList from "./MovementList.vue";
import ShiftPhotos from "./ShiftPhotos.vue";
import VerifyDialog from "./VerifyDialog.vue";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const confirm = useConfirm();

const shiftId = computed(() => {
  const raw = route.query.shift;
  const value = Number(Array.isArray(raw) ? raw[0] : raw);
  return Number.isInteger(value) && value > 0 ? value : null;
});
const query = useShift(shiftId);
const shift = computed<ShiftDetail | undefined>(() => (query.data.value?.id === shiftId.value ? query.data.value : undefined));
const skeleton = useDelayedPending(computed(() => query.isPending.value && !!shiftId.value));

type Tab = "summary" | "cash" | "activity" | "history";
const tab = ref<Tab>("summary");
watch(shiftId, () => (tab.value = "summary"));
const tabs = computed(() => [
  { value: "summary" as const, label: t("sales.drawer.tab.summary") },
  { value: "cash" as const, label: t("sales.drawer.tab.cash") },
  { value: "activity" as const, label: t("sales.drawer.tab.activity"), count: shift.value?.movements.length || undefined },
  { value: "history" as const, label: t("sales.drawer.tab.history") },
]);

const level = computed(() => (shift.value ? differenceLevel(shift.value.difference, shift.value.tolerance) : "unknown"));
/** Open, and no single receipts recorded: its sales are unknown until the close. */
const awaitingTotals = computed(() => shift.value?.status === "open" && !shift.value.receipts_recorded);
/** Cash that left the till so far (payouts, handovers, safe, bank) minus what came in. */
const movedOut = computed(() => {
  const f = shift.value?.cash_flow;
  if (!f) return "0.00";
  return subtract(sum([f.payout, f.handover, f.to_safe, f.to_bank]), sum([f.from_safe, f.deposit]));
});
const title = computed(() => shift.value?.code ?? t("sales.drawer.loading"));
const description = computed(() => {
  const s = shift.value;
  if (!s) return undefined;
  return [s.cashier.name, s.branch.name, s.register.name, fmt.day(s.business_day, "weekday")].join(" · ");
});

const verifyOpen = ref(false);
const correctOpen = ref(false);
const forceOpen = ref(false);
const dispute = useShiftWrite((cid, vars: { id: number; reason: string }) => salesApi.dispute(cid, vars.id, vars.reason));
const canManage = computed(() => company.can("sales.manage"));

async function askDispute(): Promise<void> {
  const s = shift.value;
  if (!s?.actions.dispute) return;
  const answer = await confirm({
    title: t("sales.dispute.title", { code: s.code }),
    message: t("sales.dispute.body", { name: s.cashier.name }),
    confirmLabel: t("sales.dispute.submit"),
    tone: "danger",
    reason: "required",
    reasonLabel: t("sales.dispute.reason"),
    reasonPlaceholder: t("sales.dispute.placeholder"),
    icon: ShieldAlert,
  });
  if (!answer) return;
  await dispute.mutateAsync({ id: s.id, reason: answer.reason });
  toast.success(t("sales.dispute.done", { code: s.code }));
}

useHotkey("v", () => shift.value?.actions.verify && (verifyOpen.value = true), { description: "sales.keys.verify", group: "page", allowInDialogs: true, enabled: () => !!shift.value });
useHotkey("d", () => void askDispute(), { description: "sales.keys.dispute", group: "page", allowInDialogs: true, enabled: () => !!shift.value });

const flow = computed(() => {
  const s = shift.value;
  if (!s) return [];
  const f = s.cash_flow;
  const rows: Array<{ key: string; label: string; amount: string; sign: 1 | -1 }> = [
    { key: "opening_float", label: t("sales.flow.float"), amount: f.opening_float, sign: 1 },
    { key: "cash_sales", label: t("sales.flow.cashSales"), amount: f.cash_sales, sign: 1 },
    { key: "cash_refunds", label: t("sales.flow.cashRefunds"), amount: f.cash_refunds, sign: -1 },
    { key: "from_safe", label: t("sales.movement.kind.from_safe"), amount: f.from_safe, sign: 1 },
    { key: "deposit", label: t("sales.movement.kind.deposit"), amount: f.deposit, sign: 1 },
    { key: "payout", label: t("sales.movement.kind.payout"), amount: f.payout, sign: -1 },
    { key: "handover", label: t("sales.movement.kind.handover"), amount: f.handover, sign: -1 },
    { key: "to_safe", label: t("sales.movement.kind.to_safe"), amount: f.to_safe, sign: -1 },
    { key: "to_bank", label: t("sales.movement.kind.to_bank"), amount: f.to_bank, sign: -1 },
  ];
  return rows.filter((row) => row.key === "opening_float" || row.key === "cash_sales" || !dec(row.amount).isZero());
});

const EVENT_ICONS: Record<string, typeof Clock> = { opened: CircleDot, closed: Receipt, force_closed: LockKeyhole, verified: ShieldCheck, disputed: ShieldAlert, corrected: History, ai_reading: Sparkles };
const timeline = computed<TimelineEvent[]>(() =>
  (shift.value?.timeline ?? []).map((event, index) => {
    const kind = event.kind.startsWith("movement.") ? "movement" : event.kind;
    const movementKind = event.kind.replace("movement.", "");
    const titleKey = kind === "movement" ? `sales.movement.kind.${movementKind}` : `sales.timeline.${event.kind.replace(".", "_")}`;
    const amount = event.amount ? fmt.money(event.amount) : "";
    return {
      key: `${event.kind}-${index}`,
      at: event.at,
      title: t(titleKey),
      body: [amount, event.text].filter(Boolean).join(" · ") || undefined,
      icon: EVENT_ICONS[kind] ?? Wallet,
      tone: kind === "disputed" || event.kind === "handover.declined" ? "danger" : kind === "verified" ? "success" : kind === "force_closed" ? "warning" : "neutral",
      actor: event.actor ? { name: event.actor.name } : null,
    };
  }),
);
</script>

<template>
  <UiDrawer query-key="shift" size="lg" :title="title" :description="description">
    <template #header-actions>
      <StatusPill v-if="shift" size="sm" :tone="SHIFT_TONES[shift.status]" :label="t(`sales.status.${shift.status}`)" :live="shift.status === 'open'" />
    </template>

    <div v-if="skeleton" class="flex flex-col gap-4 p-5">
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <SkeletonBlock v-for="n in 4" :key="n" height="68px" radius="12px" />
      </div>
      <SkeletonBlock height="32px" radius="8px" width="70%" />
      <div class="grid grid-cols-2 gap-3"><SkeletonBlock height="220px" radius="12px" /><SkeletonBlock height="220px" radius="12px" /></div>
    </div>
    <ErrorState v-else-if="query.isError.value" class="m-5" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="shift" class="flex flex-col gap-4 p-5 max-sm:p-4">
      <!-- The four numbers, exact: a cash check is about the last thousand ("1M expected, 1M
           counted, 1K short" hides it). -->
      <dl class="grid grid-cols-2 gap-px overflow-hidden rounded-[12px] border border-line bg-line sm:grid-cols-4" data-testid="shift-figures">
        <div class="bg-surface p-3">
          <dt class="text-xs text-muted">{{ t("sales.shift.net") }}</dt>
          <!-- Shift totals arrive with the Z-report: an open till has no sales to show yet, not zero. -->
          <template v-if="awaitingTotals">
            <dd class="mt-1 text-md font-semibold text-subtle" data-testid="net-awaiting">—</dd>
            <dd class="mt-0.5 text-[11px] text-subtle">{{ t("sales.shift.movedOutHint") }}</dd>
          </template>
          <template v-else>
            <dd class="mt-1 text-md font-semibold tabular-nums text-fg"><MoneyText :value="shift.net" /></dd>
            <dd class="mt-0.5 text-[11px] text-subtle">{{ t("sales.shift.receipts", { n: shift.receipts }, shift.receipts) }}</dd>
          </template>
        </div>
        <!-- An open till without receipts has no sales yet (they come with the Z-report at close),
             so "expected" would read float minus cash out, often below zero: show the cash out. -->
        <div v-if="awaitingTotals" class="bg-surface p-3">
          <dt class="text-xs text-muted">{{ t("sales.shift.movedOut") }}</dt>
          <dd class="mt-1 text-md font-semibold tabular-nums text-fg"><MoneyText :value="movedOut" /></dd>
          <dd class="mt-0.5 text-[11px] text-subtle">{{ t("sales.shift.movedOutSub") }}</dd>
        </div>
        <div v-else class="bg-surface p-3">
          <dt class="text-xs text-muted">{{ t("sales.shift.expected") }}</dt>
          <dd class="mt-1 text-md font-semibold tabular-nums text-fg"><MoneyText :value="shift.expected_cash ?? shift.cash_flow.expected" /></dd>
          <dd class="mt-0.5 text-[11px] text-subtle">{{ shift.status === "open" ? t("sales.shift.soFar") : t("sales.shift.inTill") }}</dd>
        </div>
        <div class="bg-surface p-3">
          <dt class="text-xs text-muted">{{ shift.recount_cash ? t("sales.shift.recounted") : t("sales.shift.counted") }}</dt>
          <!-- Not counted yet: a quiet dash, like the other tiles' placeholders. -->
          <dd :class="['mt-1 text-md font-semibold tabular-nums', shift.counted_cash === null ? 'text-subtle' : 'text-fg']"><MoneyText :value="shift.counted_cash" /></dd>
          <dd v-if="shift.recount_cash" class="mt-0.5 text-[11px] text-subtle">{{ t("sales.shift.cashierCounted", { amount: fmt.money(shift.cashier_counted) }) }}</dd>
          <dd v-else class="mt-0.5 text-[11px] text-subtle">{{ t("sales.shift.blind") }}</dd>
        </div>
        <div :class="['p-3', level === 'short' ? 'bg-danger-soft/50' : level === 'over' ? 'bg-warning-soft/50' : 'bg-surface']">
          <dt class="text-xs text-muted">{{ t("sales.shift.difference") }}</dt>
          <dd :class="['mt-1 text-md font-semibold', differenceClass(level)]">
            <MoneyText v-if="shift.difference !== null" class="tabular-nums" :value="shift.difference" sign="always" />
            <span v-else class="text-subtle">—</span>
          </dd>
          <dd class="mt-0.5 text-[11px] text-subtle">
            <!-- "Within 5,000": the currency is in the figure above, and "В пределах 5 000 сум" would not fit the tile. -->
            <StatusPill v-if="level !== 'unknown'" size="sm" variant="plain" :tone="DIFFERENCE_TONES[level]" :label="t(`sales.level.${level}`, { amount: fmt.money(shift.tolerance, undefined, { currencyDisplay: 'none' }) })" :title="t(`sales.level.${level}`, { amount: fmt.money(shift.tolerance) })" />
            <template v-else>{{ shift.status === "open" ? t("sales.shift.notClosed") : t("sales.shift.notCounted") }}</template>
          </dd>
        </div>
      </dl>

      <!-- What needs attention -->
      <div v-if="shift.status === 'disputed' || shift.ai_mismatch || shift.forced || (shift.float_difference && !dec(shift.float_difference).isZero())" class="flex flex-col gap-2">
        <InlineAlert v-if="shift.status === 'disputed'" tone="danger" size="sm" :icon="ShieldAlert" :title="t('sales.drawer.disputed')" :description="shift.note" />
        <InlineAlert v-if="shift.ai_mismatch" tone="warning" size="sm" :icon="Sparkles" :title="t('sales.drawer.aiMismatch')" :description="shift.ai_reading.notes || t('sales.drawer.aiMismatchBody')" />
        <InlineAlert v-if="shift.forced" tone="warning" size="sm" :icon="LockKeyhole" :title="t('sales.drawer.forced', { name: shift.closed_by?.name ?? '' })" :description="shift.note" />
        <InlineAlert
          v-if="shift.float_difference && !dec(shift.float_difference).isZero()"
          tone="info"
          size="sm"
          :icon="AlertTriangle"
          :title="t('sales.drawer.float', { amount: fmt.money(shift.float_difference) })"
          :description="t('sales.drawer.floatBody', { expected: fmt.money(shift.expected_float), counted: fmt.money(shift.opening_float) })"
        />
      </div>

      <SegmentedControl v-model="tab" :options="tabs" block :aria-label="t('sales.drawer.tabs')" />

      <!-- Summary: photos, totals per method, ledger -->
      <template v-if="tab === 'summary'">
        <section v-if="shift.status !== 'open'" class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold text-fg">{{ t("sales.drawer.photos") }}</h3>
          <ShiftPhotos :shift="shift" />
        </section>
        <section class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold text-fg">{{ t("sales.drawer.payments") }}</h3>
          <div v-if="shift.payments.length" class="overflow-hidden rounded-[12px] border border-line">
            <table class="w-full text-sm tabular-nums">
              <thead>
                <tr class="border-b border-line bg-surface-2/60 text-xs text-muted">
                  <th class="px-4 py-2 text-left font-medium">{{ t("sales.correct.method") }}</th>
                  <th class="px-3 py-2 text-right font-medium">{{ t("sales.payments.sales") }}</th>
                  <th class="px-3 py-2 text-right font-medium max-sm:hidden">{{ t("sales.payments.refunds") }}</th>
                  <th class="px-4 py-2 text-right font-medium">{{ t("sales.payments.net") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="payment in shift.payments" :key="payment.method.id" class="border-b border-line last:border-b-0">
                  <td class="px-4 py-2">
                    <span class="flex items-center gap-2 font-medium text-fg">
                      <component :is="METHOD_ICONS[payment.method.kind]" :size="15" class="text-subtle" aria-hidden="true" />{{ payment.method.name }}
                      <UiBadge v-if="payment.method.kind === 'credit'" size="sm" tone="info">{{ t("sales.payments.credit") }}</UiBadge>
                    </span>
                  </td>
                  <td class="px-3 py-2 text-right text-fg"><MoneyText :value="payment.sales" /></td>
                  <td class="px-3 py-2 text-right text-muted max-sm:hidden"><MoneyText v-if="!dec(payment.refunds).isZero()" :value="payment.refunds" /><span v-else>—</span></td>
                  <td class="px-4 py-2 text-right font-semibold text-fg">
                    <MoneyText :value="payment.net" />
                    <p v-if="!dec(payment.fee).isZero()" class="text-[11px] font-normal text-subtle">{{ t("sales.payments.fee", { amount: fmt.money(payment.fee) }) }}</p>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="rounded-[12px] border border-dashed border-line-strong px-4 py-3 text-sm text-muted">
            {{ shift.status === "open" ? t("sales.drawer.paymentsAtClose") : t("sales.drawer.noPayments") }}
          </p>
          <p v-if="shift.cashier_note" class="rounded-[10px] bg-surface-2/70 px-3 py-2 text-sm text-muted">«{{ shift.cashier_note }}»</p>
        </section>
        <section v-if="shift.ledger.length" class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold text-fg">{{ t("sales.drawer.ledger") }}</h3>
          <ul class="divide-y divide-line rounded-[12px] border border-line">
            <li v-for="row in shift.ledger" :key="row.id" class="flex items-center gap-3 px-4 py-2 text-sm">
              <span class="min-w-0 flex-1">
                <span class="block truncate font-medium text-fg">{{ row.category?.name ?? t(`sales.ledger.${row.kind}`) }}</span>
                <span class="block truncate text-xs text-muted">{{ row.account?.name }}</span>
              </span>
              <MoneyText :value="row.amount" sign="always" colored class="text-sm font-semibold" />
            </li>
          </ul>
        </section>
        <ExtensionSlot name="sales.shift.detail" :context="{ shift }" class="empty:hidden" />
      </template>

      <!-- Cash: the formula and both counts -->
      <template v-else-if="tab === 'cash'">
        <section class="overflow-hidden rounded-[12px] border border-line">
          <ul class="divide-y divide-line">
            <li v-for="row in flow" :key="row.key" class="flex items-center justify-between px-4 py-2 text-sm">
              <span class="text-muted">{{ row.label }}</span>
              <span :class="['font-medium tabular-nums', row.sign < 0 ? 'text-fg' : 'text-fg']">{{ row.sign < 0 ? "−" : "+" }} <MoneyText :value="row.amount" /></span>
            </li>
          </ul>
          <div class="flex items-center justify-between border-t border-line-strong bg-surface-2/60 px-4 py-2.5 text-sm font-semibold">
            <span class="text-fg">{{ awaitingTotals ? t("sales.flow.soFar") : t("sales.flow.expected") }}</span>
            <MoneyText :value="shift.cash_flow.expected" />
          </div>
          <p v-if="awaitingTotals" class="border-t border-line px-4 py-2 text-xs text-muted">{{ t("sales.drawer.paymentsAtClose") }}</p>
          <div class="flex items-center justify-between border-t border-line px-4 py-2 text-sm">
            <span class="text-muted">{{ shift.recount_cash ? t("sales.shift.recounted") : t("sales.shift.counted") }}</span>
            <MoneyText :value="shift.counted_cash" />
          </div>
          <div :class="['flex items-center justify-between border-t border-line px-4 py-2.5 text-sm font-semibold', differenceClass(level)]">
            <span>{{ t("sales.shift.difference") }}</span>
            <MoneyText v-if="shift.difference !== null" :value="shift.difference" sign="always" />
            <span v-else>—</span>
          </div>
        </section>
        <section class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold text-fg">{{ t("sales.drawer.counts") }}</h3>
          <CashCountBreakdown :count="shift.opening_count" :title="t('sales.count.opening')" :compare="shift.status === 'open' ? null : shift.closing_count" :compare-title="t('sales.count.closing')" />
        </section>
      </template>

      <!-- Activity: movements and timeline -->
      <template v-else-if="tab === 'activity'">
        <section class="flex flex-col gap-1">
          <h3 class="text-sm font-semibold text-fg">{{ t("sales.drawer.movements") }}</h3>
          <MovementList v-if="shift.movements.length" :movements="shift.movements" dense />
          <p v-else class="py-2 text-sm text-muted">{{ t("sales.drawer.noMovements") }}</p>
        </section>
        <section class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold text-fg">{{ t("sales.drawer.timeline") }}</h3>
          <TimelineList :events="timeline" dense />
        </section>
      </template>

      <AuditTrail v-else target-type="cashshift" :target-id="shift.id" />
    </div>

    <template v-if="shift && canManage" #footer>
      <UiButton v-if="shift.actions.force_close" variant="danger" :icon="LockKeyhole" @click="forceOpen = true">{{ t("sales.force.action") }}</UiButton>
      <template v-else>
        <UiButton v-if="shift.actions.correct" variant="ghost" @click="correctOpen = true">{{ t("sales.correct.action") }}</UiButton>
        <UiButton v-if="shift.actions.dispute" variant="secondary" :icon="ShieldAlert" kbd="D" @click="askDispute">{{ t("sales.dispute.action") }}</UiButton>
        <UiButton v-if="shift.actions.verify" variant="primary" :icon="ShieldCheck" kbd="V" @click="verifyOpen = true">{{ t("sales.verify.action") }}</UiButton>
        <span v-else-if="shift.status === 'verified'" class="flex items-center gap-1.5 text-sm text-success">
          <CheckCircle2 :size="15" />{{ t("sales.drawer.verifiedBy", { name: shift.verified_by?.name ?? "", time: shift.verified_at ? fmt.instant(shift.verified_at, "short") : "" }) }}
        </span>
      </template>
    </template>
  </UiDrawer>
  <template v-if="shift">
    <VerifyDialog v-model:open="verifyOpen" :shift="shift" />
    <CorrectDialog v-model:open="correctOpen" :shift="shift" />
    <ForceCloseDialog v-model:open="forceOpen" :shift="shift" />
  </template>
</template>
