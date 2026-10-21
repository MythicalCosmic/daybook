<script setup lang="ts">
/**
 * One debt in a side panel synced with `?debt=`: who owes whom, how much is left and since when,
 * the payments so far, an instalment plan, and the decisions: record a payment, change the due
 * date or who chases it, write it off, or cancel a debt recorded by mistake.
 */
import { Ban, CalendarClock, CircleCheck, EyeOff, HandCoins, History, MoreHorizontal, Pencil, Plus, Split, Trash2, Undo2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import AuditTrail from "@/components/AuditTrail.vue";
import DatePicker from "@/components/DatePicker.vue";
import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import NumberInput from "@/components/NumberInput.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { addMonths } from "@/lib/dates";
import { dec } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { financeApi, useDebt, useOptions, useRefresh } from "../api";
import { dayStyle, DEBT_TONES, share } from "../lib";
import PaymentDialog from "./PaymentDialog.vue";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();

const id = computed(() => {
  const raw = route.query.debt;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && /^\d+$/.test(value) ? Number(value) : null;
});
const query = useDebt(id);
const detail = computed(() => query.data.value ?? null);
const debt = computed(() => detail.value?.debt ?? null);
const tab = ref<"details" | "history">("details");
const payOpen = ref(false);
const editing = ref(false);
const planning = ref(false);
const saving = ref(false);
const canRecord = computed(() => company.can("finance.record"));
const options = useOptions(editing);

watch(id, () => {
  tab.value = "details";
  editing.value = false;
  planning.value = false;
});

const receivable = computed(() => debt.value?.direction === "receivable");
const paidShare = computed(() => (debt.value ? share(debt.value.paid, debt.value.amount) : 0));
const items = computed<DescriptionItem[]>(() => {
  const d = debt.value;
  if (!d) return [];
  return [
    { key: "issued", label: t("finance.debts.issued"), value: fmt.day(d.issued_on, "medium") },
    { key: "due", label: t("finance.debts.due"), value: d.due_on ? fmt.day(d.due_on, "medium") : t("finance.debts.noDue") },
    { key: "amount", label: t("finance.debts.amount"), value: fmt.money(d.amount, d.currency) },
    { key: "paid", label: t("finance.debts.paid"), value: fmt.money(d.paid, d.currency) },
    { key: "branch", label: t("finance.field.branch"), value: d.branch?.name ?? "—" },
    { key: "responsible", label: t("finance.debts.responsible"), value: d.responsible?.name ?? "—" },
    ...(d.source ? [{ key: "source", label: t("finance.tx.source"), value: `${d.source.label} #${d.source.id}`, wide: true }] : []),
  ];
});

// Editing ----------------------------------------------------------------------------------

const draft = ref({ due_on: null as string | null, responsible: null as number | null, description: "" });
function startEdit(): void {
  const d = debt.value;
  if (!d) return;
  draft.value = { due_on: d.due_on, responsible: d.responsible?.id ?? null, description: d.description };
  editing.value = true;
}
const people = computed(() => (options.data.value?.members ?? []).map((m) => ({ value: m.id, label: m.name, description: m.position })));

async function saveEdit(): Promise<void> {
  if (!debt.value) return;
  saving.value = true;
  try {
    await financeApi.updateDebt(company.currentId ?? 0, debt.value.id, draft.value);
    toast.success(t("finance.debts.saved"));
    editing.value = false;
    refresh();
  } finally {
    saving.value = false;
  }
}

async function writeOff(): Promise<void> {
  const d = debt.value;
  if (!d) return;
  const answer = await confirm({
    title: t("finance.debts.writeOffTitle"),
    message: t(receivable.value ? "finance.debts.writeOffBodyIn" : "finance.debts.writeOffBodyOut", { amount: fmt.money(d.outstanding, d.currency) }),
    tone: "danger",
    reason: "required",
    reasonLabel: t("finance.tx.voidReason"),
    confirmLabel: t("finance.debts.writeOff"),
    onConfirm: (reason) => financeApi.writeOffDebt(company.currentId ?? 0, d.id, reason),
  });
  if (answer) {
    toast.success(t("finance.debts.writtenOff"));
    refresh();
  }
}

async function cancel(): Promise<void> {
  const d = debt.value;
  if (!d) return;
  const answer = await confirm({
    title: t("finance.debts.cancelTitle"),
    message: t("finance.debts.cancelBody"),
    tone: "danger",
    reason: "required",
    reasonLabel: t("finance.tx.voidReason"),
    confirmLabel: t("finance.debts.cancel"),
    onConfirm: (reason) => financeApi.cancelDebt(company.currentId ?? 0, d.id, reason),
  });
  if (answer) {
    toast.success(t("finance.debts.cancelled"));
    refresh();
  }
}

// Instalments ------------------------------------------------------------------------------

const plan = ref<Array<{ due_on: string | null; amount: string | null }>>([]);
const splitInto = ref<number | null>(3);

function startPlan(): void {
  const d = detail.value;
  if (!d) return;
  plan.value = d.installments.length ? d.installments.map((row) => ({ due_on: row.due_on, amount: row.amount })) : [];
  if (!plan.value.length) split();
  planning.value = true;
}

function split(): void {
  const d = debt.value;
  const n = Math.max(1, Math.min(24, splitInto.value ?? 1));
  if (!d) return;
  const total = dec(d.amount);
  const step = total.div(n).toDecimalPlaces(d.currency === "USD" ? 2 : 0, 1);
  const start = d.due_on && d.due_on > d.issued_on ? d.issued_on : d.issued_on;
  plan.value = Array.from({ length: n }, (_, index) => ({
    due_on: addMonths(start, index + 1),
    amount: index === n - 1 ? total.minus(step.times(n - 1)).toFixed(2) : step.toFixed(2),
  }));
}

const planTotal = computed(() => plan.value.reduce((sum, row) => sum.plus(dec(row.amount ?? 0)), dec(0)));
const planOk = computed(() => !!debt.value && planTotal.value.eq(dec(debt.value.amount)) && plan.value.every((row) => row.due_on && row.amount));

async function savePlan(): Promise<void> {
  if (!debt.value || !planOk.value) return;
  saving.value = true;
  try {
    await financeApi.setInstallments(
      company.currentId ?? 0,
      debt.value.id,
      plan.value.map((row) => ({ due_on: row.due_on!, amount: row.amount! })),
    );
    toast.success(t("finance.debts.planSaved"));
    planning.value = false;
    refresh();
  } finally {
    saving.value = false;
  }
}

const installmentTone = { paid: "success", partial: "info", due: "neutral", overdue: "danger" } as const;
const fieldLabels = computed(() => ({ due_on: t("finance.debts.due"), description: t("finance.field.note"), responsible: t("finance.debts.responsible"), branch: t("finance.field.branch") }));
const moreMenu = computed<MenuEntry[]>(() => {
  const list: MenuEntry[] = [];
  if (!debt.value || !detail.value) return list;
  if (detail.value.can_write_off) list.push({ label: t("finance.debts.writeOff"), icon: Undo2, onSelect: writeOff });
  if (detail.value.can_cancel) list.push({ label: t("finance.debts.cancel"), icon: Ban, danger: true, onSelect: cancel });
  return list;
});

</script>

<template>
  <UiDrawer query-key="debt" size="md" :title="debt ? debt.direction_label : t('finance.debts.debt')">
    <template #default>
      <div class="p-5">
        <div v-if="query.isPending.value && id" class="flex flex-col gap-4">
          <SkeletonBlock height="72px" />
          <SkeletonBlock v-for="n in 5" :key="n" height="16px" />
        </div>
        <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
        <div v-else-if="debt && detail" class="flex flex-col gap-5">
          <header class="flex items-start gap-3">
            <span :class="['grid size-11 shrink-0 place-items-center rounded-[12px]', receivable ? 'bg-success-soft text-success' : 'bg-danger-soft text-danger']" aria-hidden="true">
              <HandCoins :size="20" />
            </span>
            <div class="min-w-0 flex-1">
              <p class="truncate text-base font-semibold text-fg">{{ debt.party?.name ?? t("finance.debts.hidden") }}</p>
              <p class="text-[1.625rem] font-semibold leading-8 tracking-[-0.02em] tabular-nums text-fg"><MoneyText :value="debt.outstanding" :currency="debt.currency" /></p>
              <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
                <StatusPill :tone="DEBT_TONES[debt.status]" size="sm" :label="t(`finance.debtStatus.${debt.status}`)" />
                <StatusPill tone="neutral" size="sm" variant="outline" :label="t(`finance.debtKind.${debt.kind}`)" />
                <StatusPill v-if="debt.days_overdue" tone="danger" size="sm" :label="t('finance.debts.late', { n: debt.days_overdue }, debt.days_overdue)" />
                <StatusPill v-if="debt.is_opening" tone="info" size="sm" variant="outline" :label="t('finance.debts.opening')" />
              </div>
            </div>
          </header>

          <div>
            <ProgressBar :value="paidShare" :max="100" size="sm" tone="success" />
            <p class="mt-1.5 text-xs text-muted">{{ t("finance.debts.paidOf", { paid: fmt.money(debt.paid, debt.currency), amount: fmt.money(debt.amount, debt.currency) }) }}</p>
          </div>

          <SegmentedControl
            v-model="tab"
            size="sm"
            :options="[
              { value: 'details', label: t('finance.tx.details'), icon: HandCoins },
              { value: 'history', label: t('finance.tx.history'), icon: History },
            ]"
          />

          <template v-if="tab === 'details'">
            <InlineAlert v-if="debt.masked" tone="info" size="sm" :icon="EyeOff" :title="t('finance.tx.maskedTitle')" :description="t('finance.debts.maskedBody')" />
            <InlineAlert v-if="debt.is_locked" tone="info" size="sm" :title="t('finance.debts.lockedTitle')" :description="t('finance.debts.lockedBody')" />
            <p v-if="debt.description && !editing" class="rounded-[10px] bg-surface-2 px-3 py-2.5 text-base text-fg">{{ debt.description }}</p>

            <DescriptionList v-if="!editing" :items="items" :columns="2" />
            <div v-else class="flex flex-col gap-3 rounded-[12px] border border-line p-3">
              <FormField :label="t('finance.debts.due')">
                <DatePicker v-model="draft.due_on" :min="debt.issued_on" clearable />
              </FormField>
              <FormField :label="t('finance.debts.responsible')" optional>
                <SelectBox v-model="draft.responsible" :options="people" clearable />
              </FormField>
              <FormField :label="t('finance.field.note')" optional>
                <TextInput v-model="draft.description" :maxlength="300" />
              </FormField>
              <div class="flex justify-end gap-2">
                <UiButton variant="ghost" @click="editing = false">{{ t("common.cancel") }}</UiButton>
                <UiButton variant="primary" :loading="saving" @click="saveEdit">{{ t("common.save") }}</UiButton>
              </div>
            </div>

            <section class="flex flex-col gap-2">
              <div class="flex items-center gap-2">
                <CalendarClock :size="15" class="text-subtle" />
                <h3 class="flex-1 text-sm font-semibold text-fg">{{ t("finance.debts.plan") }}</h3>
                <UiButton v-if="debt.status === 'open' && !debt.masked && canRecord && !planning" size="sm" variant="ghost" :icon="Split" @click="startPlan">
                  {{ detail.installments.length ? t("finance.debts.changePlan") : t("finance.debts.makePlan") }}
                </UiButton>
              </div>
              <ul v-if="detail.installments.length && !planning" class="flex flex-col divide-y divide-line rounded-[10px] border border-line">
                <li v-for="row in detail.installments" :key="row.id" class="flex items-center gap-3 px-3 py-2">
                  <span class="w-24 shrink-0 text-sm text-fg">{{ fmt.day(row.due_on, dayStyle(row.due_on)) }}</span>
                  <StatusPill :tone="installmentTone[row.status]" size="sm" :label="t(`finance.installment.${row.status}`)" />
                  <span class="flex-1" />
                  <span class="text-sm font-semibold tabular-nums text-fg"><MoneyText :value="row.amount" :currency="debt.currency" /></span>
                </li>
              </ul>
              <p v-else-if="!planning" class="text-sm text-muted">{{ t("finance.debts.noPlan") }}</p>
              <div v-if="planning" class="flex flex-col gap-2 rounded-[12px] border border-line p-3">
                <div class="flex items-end gap-2">
                  <FormField :label="t('finance.debts.splitInto')" class="w-36">
                    <NumberInput v-model="splitInto" :min="1" :max="24" />
                  </FormField>
                  <UiButton size="sm" @click="split">{{ t("finance.debts.split") }}</UiButton>
                </div>
                <div v-for="(row, index) in plan" :key="index" class="flex items-center gap-2">
                  <DatePicker v-model="row.due_on" :min="debt.issued_on" size="sm" class="w-40" />
                  <MoneyInput v-model="row.amount" :currencies="[debt.currency]" size="sm" class="min-w-0 flex-1" />
                  <IconButton :icon="Trash2" size="sm" :label="t('common.delete')" @click="plan.splice(index, 1)" />
                </div>
                <button type="button" class="inline-flex w-fit items-center gap-1 text-sm font-semibold text-accent-fg hover:underline" @click="plan.push({ due_on: null, amount: null })">
                  <Plus :size="14" />{{ t("finance.debts.addInstallment") }}
                </button>
                <p :class="['text-xs', planOk ? 'text-success' : 'text-warning']">
                  <CircleCheck v-if="planOk" :size="12" class="mr-1 inline" />{{ t("finance.debts.planTotal", { total: fmt.money(planTotal.toFixed(2), debt.currency), amount: fmt.money(debt.amount, debt.currency) }) }}
                </p>
                <div class="flex justify-end gap-2">
                  <UiButton variant="ghost" size="sm" @click="planning = false">{{ t("common.cancel") }}</UiButton>
                  <UiButton variant="primary" size="sm" :disabled="!planOk" :loading="saving" @click="savePlan">{{ t("common.save") }}</UiButton>
                </div>
              </div>
            </section>

            <section v-if="detail.payments.length" class="flex flex-col gap-2">
              <h3 class="text-sm font-semibold text-fg">{{ t("finance.debts.movements") }}</h3>
              <ul class="flex flex-col divide-y divide-line rounded-[10px] border border-line">
                <li v-for="row in detail.payments" :key="row.id" :class="['flex items-center gap-3 px-3 py-2', row.status === 'void' && 'opacity-50']">
                  <span class="w-20 shrink-0 text-sm text-muted">{{ fmt.day(row.occurred_on, dayStyle(row.occurred_on)) }}</span>
                  <span class="min-w-0 flex-1 truncate text-sm text-fg">{{ row.kind_label }}<template v-if="row.account"> · {{ row.account.name }}</template></span>
                  <span class="text-sm font-semibold tabular-nums"><MoneyText :value="row.amount" :currency="row.currency" sign="always" colored /></span>
                </li>
              </ul>
            </section>
          </template>
          <AuditTrail v-else target-type="debt" :target-id="debt.id" :field-labels="fieldLabels" />
          <PaymentDialog v-model:open="payOpen" :debt="debt" />
        </div>
      </div>
    </template>
    <template #footer>
      <div v-if="debt && detail && debt.status === 'open' && !editing" class="flex w-full flex-wrap items-center gap-2">
        <DropdownMenu v-if="moreMenu.length" :items="moreMenu" align="start" side="top" width="220px">
          <template #trigger>
            <IconButton :icon="MoreHorizontal" :label="t('finance.debts.more')" variant="ghost" size="sm" />
          </template>
        </DropdownMenu>
        <span class="flex-1" />
        <UiButton v-if="canRecord" size="sm" :icon="Pencil" @click="startEdit">{{ t("common.edit") }}</UiButton>
        <UiButton v-if="detail.can_pay" variant="primary" size="sm" :icon="HandCoins" @click="payOpen = true">{{ receivable ? t("finance.debts.recordIn") : t("finance.debts.recordOut") }}</UiButton>
      </div>
    </template>
  </UiDrawer>
</template>
