<script setup lang="ts">
/**
 * Record a loan, or change its terms before the first payment (v12): who lent (or borrowed), how
 * much and when, where the money arrived (or "from before my books"), the rate, the term, the
 * first payment's day, how it is repaid (equal payments, equal principal, or the bank's own
 * schedule typed row by row), grace months, how interest is counted and a one-off fee. The
 * schedule the terms make shows beside the form as it is typed: the first payment, the interest
 * in all, what the loan really costs a year, and every payment.
 */
import { ArrowDownLeft, ArrowUpRight, CalendarClock, Clock, Landmark, ListOrdered, Plus, Trash2, TrendingDown } from "@lucide/vue";
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import type { Currency } from "@/api/types";
import ComboBox from "@/components/ComboBox.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import NumberInput from "@/components/NumberInput.vue";
import type { SelectOption } from "@/components/options";
import RadioCards from "@/components/RadioCards.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { addDays, addMonths } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { financeApi, searchCounterparties, useOptions, useRefresh } from "../../api";
import { creditApi, principalGap, type Loan, type LoanBasis, type LoanDirection, type LoanMethod, type LoanPreview, type LoanTerms, type ScheduleRow } from "../../credit";
import { pickerOrder } from "../../lib";
import AccountChips from "../AccountChips.vue";

const open = defineModel<boolean>("open", { default: false });
/** With `loan`: change its terms (nothing paid yet); without: record a new loan. */
const props = withDefaults(defineProps<{ loan?: Loan | null; rows?: ScheduleRow[] }>(), { loan: null, rows: () => [] });
const emit = defineEmits<{ saved: [id: number] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const options = useOptions(open);
const canManage = computed(() => company.can("finance.manage"));
const editing = computed(() => !!props.loan);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});

const form = reactive({
  direction: "payable" as LoanDirection,
  counterparty: null as number | null,
  amount: null as string | null,
  currency: company.currency as Currency,
  issued_on: null as string | null,
  moved: "now" as "now" | "before",
  account: null as number | null,
  annual_rate: 24 as number | null,
  term_months: 12 as number | null,
  first_due_on: null as string | null,
  method: "annuity" as LoanMethod,
  grace_months: 0 as number | null,
  basis: "monthly" as LoanBasis,
  fee: null as string | null,
  rows: [] as ScheduleRow[],
  description: "",
});
const partySelected = ref<SelectOption<number> | null>(null);

function reset(): void {
  for (const key of Object.keys(errors)) delete errors[key];
  const today = options.data.value?.today ?? null;
  const loan = props.loan;
  Object.assign(form, {
    direction: loan?.direction ?? "payable",
    counterparty: loan?.counterparty.id ?? null,
    amount: loan?.amount ?? null,
    currency: loan?.currency ?? company.currency,
    issued_on: loan?.issued_on ?? today,
    moved: loan?.is_opening ? "before" : "now",
    account: loan?.account?.id ?? null,
    annual_rate: loan ? Number(loan.annual_rate) : 24,
    term_months: loan?.term_months ?? 12,
    first_due_on: loan?.first_due_on ?? (today ? addMonths(today, 1) : null),
    method: loan?.method ?? "annuity",
    grace_months: loan?.grace_months ?? 0,
    basis: loan?.basis ?? "monthly",
    fee: null,
    rows: props.rows.length ? props.rows.map((row) => ({ ...row })) : [],
    description: loan?.description ?? "",
  });
  partySelected.value = loan ? { value: loan.counterparty.id, label: loan.counterparty.name } : null;
  preview.value = null;
}
watch(open, (isOpen) => isOpen && reset(), { immediate: true });
watch(
  () => options.data.value?.today,
  (day) => {
    if (!day || editing.value) return;
    if (!form.issued_on) form.issued_on = day;
    if (!form.first_due_on) form.first_due_on = addMonths(day, 1);
  },
);

const taken = computed(() => form.direction === "payable");
const accounts = computed(() => pickerOrder((options.data.value?.accounts ?? []).filter((a) => a.currency === form.currency)));
watch(accounts, (list) => {
  if (form.account !== null && !list.some((a) => a.id === form.account)) form.account = null;
  if (form.account === null && !editing.value) form.account = list.find((a) => a.kind === "bank")?.id ?? null;
});

const methodOptions = computed(() => [
  { value: "annuity" as const, label: t("finance.loans.method.annuity"), description: t("finance.loans.method.annuityHint"), icon: CalendarClock },
  { value: "equal_principal" as const, label: t("finance.loans.method.equal_principal"), description: t("finance.loans.method.equalHint"), icon: TrendingDown },
  { value: "custom" as const, label: t("finance.loans.method.custom"), description: t("finance.loans.method.customHint"), icon: ListOrdered },
]);
const basisOptions = computed(() => [
  { value: "monthly" as const, label: t("finance.loans.basis.monthly") },
  { value: "actual" as const, label: t("finance.loans.basis.actual") },
]);

// Typed rows (the bank's own schedule) ---------------------------------------------------------

function addRow(): void {
  const last = form.rows.at(-1)?.due_on ?? form.first_due_on ?? form.issued_on;
  form.rows.push({ due_on: last ? (form.rows.length ? addMonths(last, 1) : last) : "", principal: "", interest: "" });
}
function removeRow(index: number): void {
  form.rows.splice(index, 1);
}
watch(
  () => form.method,
  (method) => {
    if (method === "custom" && !form.rows.length) for (let i = 0; i < Math.min(form.term_months ?? 3, 3); i++) addRow();
  },
);
const gap = computed(() => principalGap(form.amount, form.rows));

// The live schedule ------------------------------------------------------------------------------

const preview = ref<LoanPreview | null>(null);
const previewing = ref(false);
const previewError = ref<string | null>(null);
let timer: ReturnType<typeof setTimeout> | null = null;
let ticket = 0;

const terms = computed<LoanTerms | null>(() => {
  if (!form.amount || !form.issued_on) return null;
  if (form.method === "custom") {
    if (!form.rows.length || form.rows.some((row) => !row.due_on)) return null;
    return {
      amount: form.amount,
      currency: form.currency,
      issued_on: form.issued_on,
      annual_rate: String(form.annual_rate ?? 0),
      method: "custom",
      basis: form.basis,
      term_months: form.rows.length,
      first_due_on: null,
      grace_months: 0,
      fee: taken.value ? (form.fee ?? "0") : "0",
      rows: form.rows.map((row) => ({ due_on: row.due_on, principal: row.principal || "0", interest: row.interest || "0" })),
    };
  }
  if (!form.term_months || !form.first_due_on || form.annual_rate === null) return null;
  return {
    amount: form.amount,
    currency: form.currency,
    issued_on: form.issued_on,
    annual_rate: String(form.annual_rate),
    method: form.method,
    basis: form.basis,
    term_months: form.term_months,
    first_due_on: form.first_due_on,
    grace_months: form.grace_months ?? 0,
    fee: taken.value ? (form.fee ?? "0") : "0",
  };
});

watch(
  terms,
  (value) => {
    if (timer) clearTimeout(timer);
    if (!value || !open.value) {
      preview.value = null;
      previewError.value = null;
      return;
    }
    timer = setTimeout(() => void load(value), 350);
  },
  { deep: true },
);
onBeforeUnmount(() => timer && clearTimeout(timer));

async function load(value: LoanTerms): Promise<void> {
  const mine = ++ticket;
  previewing.value = true;
  try {
    const result = await creditApi.preview(company.currentId ?? 0, value);
    if (mine !== ticket) return;
    preview.value = result;
    previewError.value = null;
  } catch (error) {
    if (mine !== ticket) return;
    preview.value = null;
    previewError.value = isApiError(error) ? error.message || Object.values(error.fieldErrors)[0]?.[0] || null : null;
  } finally {
    if (mine === ticket) previewing.value = false;
  }
}

const showAll = ref(false);
const shownRows = computed(() => {
  const rows = preview.value?.rows ?? [];
  if (showAll.value || rows.length <= 6) return rows;
  return [...rows.slice(0, 4), ...rows.slice(-1)];
});
const hidden = computed(() => (preview.value?.rows.length ?? 0) - shownRows.value.length);

// Saving -------------------------------------------------------------------------------------------

async function partySource(q: string, signal: AbortSignal): Promise<SelectOption<number>[]> {
  const rows = await searchCounterparties(company.currentId ?? 0, q, signal);
  return rows.map((row) => ({ value: row.id, label: row.name, description: [row.kind_label, row.phone].filter(Boolean).join(" · "), avatar: { name: row.name } }));
}

async function createParty(name: string): Promise<void> {
  try {
    const created = await financeApi.createCounterparty(company.currentId ?? 0, { name, kind: "other" });
    form.counterparty = created.id;
    partySelected.value = { value: created.id, label: created.name };
  } catch {
    // The HTTP layer showed why.
  }
}

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!editing.value) {
    if (!form.counterparty) errors.counterparty = t("finance.loans.errLender");
    if (!form.amount) errors.amount = t("finance.quick.errAmount");
    if (form.moved === "now" && !form.account) errors.account = t("finance.quick.errAccount");
  }
  if (form.method !== "custom" && !form.first_due_on) errors.first_due_on = t("finance.loans.errFirst");
  if (form.method === "custom" && gap.value !== "0.00") errors.rows = t("finance.loans.errRows", { gap: fmt.money(gap.value, form.currency) });
  if (!terms.value) errors.terms = t("finance.loans.errTerms");
  if (Object.keys(errors).length) return;
  saving.value = true;
  const cid = company.currentId ?? 0;
  const value = terms.value!;
  try {
    if (props.loan) {
      await creditApi.replaceSchedule(cid, props.loan.id, {
        annual_rate: value.annual_rate,
        method: value.method,
        basis: value.basis,
        term_months: value.term_months,
        ...(value.method === "custom" ? { rows: value.rows } : { first_due_on: value.first_due_on, grace_months: value.grace_months }),
      });
      toast.success(t("finance.loans.scheduleSaved"));
      emit("saved", props.loan.id);
    } else {
      const made = await creditApi.createLoan(cid, {
        ...value,
        direction: form.direction,
        counterparty: form.counterparty!,
        account: form.moved === "now" ? form.account : null,
        description: form.description,
      });
      toast.success(t("finance.loans.created"));
      emit("saved", made.id);
    }
    refresh();
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
    const unshown = unshownFieldError(error, ["counterparty", "amount", "account", "first_due_on", "rows"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}

const minFirst = computed(() => (form.issued_on ? addDays(form.issued_on, 1) : null));
</script>

<template>
  <UiDialog
    v-model:open="open"
    :title="editing ? t('finance.loans.editTitle') : t('finance.loans.newTitle')"
    :description="editing ? t('finance.loans.editDescription') : t('finance.loans.newDescription')"
    size="xl"
  >
    <div class="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <div class="flex min-w-0 flex-col gap-4">
        <template v-if="!editing">
          <SegmentedControl
            v-model="form.direction"
            block
            :options="[
              { value: 'payable', label: t('finance.loans.taken'), icon: ArrowDownLeft },
              { value: 'receivable', label: t('finance.loans.given'), icon: ArrowUpRight },
            ]"
          />
          <FormField :label="taken ? t('finance.loans.lender') : t('finance.loans.borrower')" :error="errors.counterparty" required>
            <ComboBox
              v-model="form.counterparty"
              :source="partySource"
              :selected="partySelected"
              creatable
              :invalid="!!errors.counterparty"
              :placeholder="taken ? t('finance.loans.lenderPlaceholder') : t('finance.loans.borrowerPlaceholder')"
              @create="createParty"
            />
          </FormField>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <FormField :label="t('finance.loans.amount')" :error="errors.amount" required :hint="form.moved === 'before' ? t('finance.loans.amountBeforeHint') : undefined">
              <MoneyInput v-model="form.amount" v-model:currency="form.currency" :currencies="['UZS', 'USD']" :invalid="!!errors.amount" />
            </FormField>
            <FormField :label="t('finance.loans.startedOn')" required>
              <DatePicker v-model="form.issued_on" :max="options.data.value?.today ?? null" />
            </FormField>
          </div>
          <FormField :label="taken ? t('finance.loans.arrived') : t('finance.loans.left')" :error="errors.account" :required="form.moved === 'now'">
            <div class="flex flex-col gap-2">
              <SegmentedControl
                v-model="form.moved"
                size="sm"
                :options="[
                  { value: 'now', label: t('finance.loans.movedNow'), icon: Landmark },
                  ...(canManage ? [{ value: 'before' as const, label: t('finance.loans.movedBefore'), icon: Clock }] : []),
                ]"
              />
              <AccountChips v-if="form.moved === 'now'" v-model="form.account" :accounts="accounts" :invalid="!!errors.account" />
              <p v-else class="text-xs text-muted">{{ t("finance.loans.movedBeforeHint") }}</p>
            </div>
          </FormField>
        </template>

        <FormField :label="t('finance.loans.how')">
          <RadioCards v-model="form.method" :options="methodOptions" :columns="3" />
        </FormField>

        <div v-if="form.method !== 'custom'" class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <FormField :label="t('finance.loans.rate')" required>
            <NumberInput v-model="form.annual_rate" :min="0" :max="100" :decimals="3" suffix="%" />
          </FormField>
          <FormField :label="t('finance.loans.term')" required>
            <NumberInput v-model="form.term_months" :min="1" :max="600" :suffix="t('finance.loans.monthsShort')" />
          </FormField>
          <FormField :label="t('finance.loans.firstDue')" :error="errors.first_due_on" required class="col-span-2">
            <DatePicker v-model="form.first_due_on" :min="minFirst" />
          </FormField>
          <FormField :label="t('finance.loans.grace')" :hint="t('finance.loans.graceHint')" class="col-span-2">
            <NumberInput v-model="form.grace_months" :min="0" :max="Math.max((form.term_months ?? 1) - 1, 0)" :suffix="t('finance.loans.monthsShort')" />
          </FormField>
          <FormField :label="t('finance.loans.basisLabel')" class="col-span-2">
            <SelectBox v-model="form.basis" :options="basisOptions" />
          </FormField>
        </div>

        <div v-else class="flex flex-col gap-2" data-custom-rows>
          <div class="flex items-center justify-between gap-2">
            <p class="text-sm font-medium text-fg">{{ t("finance.loans.rowsTitle") }}</p>
            <span :class="['text-xs tabular-nums', gap === '0.00' ? 'text-success' : 'text-warning']">
              {{ gap === "0.00" ? t("finance.loans.rowsMatch") : t("finance.loans.rowsGap", { gap: fmt.money(gap, form.currency) }) }}
            </span>
          </div>
          <div class="overflow-x-auto rounded-[10px] border border-line">
            <table class="w-full min-w-[30rem] text-sm">
              <thead class="bg-surface-2 text-xs text-muted">
                <tr>
                  <th class="px-2 py-2 text-left font-medium">{{ t("finance.loans.col.date") }}</th>
                  <th class="px-2 py-2 text-left font-medium">{{ t("finance.loans.col.principal") }}</th>
                  <th class="px-2 py-2 text-left font-medium">{{ t("finance.loans.col.interest") }}</th>
                  <th class="w-10" />
                </tr>
              </thead>
              <tbody class="divide-y divide-line">
                <tr v-for="(row, index) in form.rows" :key="index">
                  <td class="px-2 py-1.5"><DatePicker v-model="row.due_on" size="sm" :min="form.issued_on" /></td>
                  <td class="px-2 py-1.5"><MoneyInput v-model="row.principal" size="sm" :currencies="[form.currency]" /></td>
                  <td class="px-2 py-1.5"><MoneyInput v-model="row.interest" size="sm" :currencies="[form.currency]" /></td>
                  <td class="px-1 text-right"><IconButton :icon="Trash2" size="sm" variant="ghost" :label="t('common.delete')" @click="removeRow(index)" /></td>
                </tr>
              </tbody>
            </table>
          </div>
          <UiButton size="sm" variant="secondary" :icon="Plus" class="self-start" @click="addRow">{{ t("finance.loans.addRow") }}</UiButton>
          <p v-if="errors.rows" class="text-xs text-danger">{{ errors.rows }}</p>
        </div>

        <FormField v-if="taken" :label="t('finance.loans.fee')" :hint="t('finance.loans.feeHint')" optional>
          <MoneyInput v-model="form.fee" :currencies="[form.currency]" />
        </FormField>
        <FormField v-if="!editing" :label="t('finance.field.note')" optional>
          <TextInput v-model="form.description" :maxlength="300" :placeholder="t('finance.loans.notePlaceholder')" />
        </FormField>
      </div>

      <!-- The schedule the terms make, as they are typed. -->
      <aside class="flex min-w-0 flex-col gap-3 rounded-[14px] border border-line bg-surface-2/60 p-4 lg:sticky lg:top-0 lg:self-start" :aria-label="t('finance.loans.previewTitle')" data-preview>
        <p class="text-sm font-semibold text-fg">{{ t("finance.loans.previewTitle") }}</p>
        <template v-if="preview">
          <dl class="grid grid-cols-2 gap-x-3 gap-y-2.5">
            <div class="col-span-2">
              <dt class="text-xs text-muted">{{ form.method === "annuity" ? t("finance.loans.monthly") : t("finance.loans.firstPayment") }}</dt>
              <dd class="text-2xl font-semibold tabular-nums text-fg"><MoneyText :value="preview.first_payment" :currency="form.currency" decimals="never" /></dd>
            </div>
            <div>
              <dt class="text-xs text-muted">{{ t("finance.loans.totalInterest") }}</dt>
              <dd class="text-sm font-semibold tabular-nums text-fg"><MoneyText :value="preview.totals.interest" :currency="form.currency" compact decimals="never" /></dd>
            </div>
            <div>
              <dt class="text-xs text-muted">{{ t("finance.loans.cost") }}</dt>
              <dd class="text-sm font-semibold tabular-nums text-fg" :title="t('finance.loans.costHint')">{{ fmt.percent(Number(preview.effective_rate), 1) }}</dd>
            </div>
            <div class="col-span-2">
              <dt class="text-xs text-muted">{{ t("finance.loans.totalPaid") }}</dt>
              <dd class="text-sm tabular-nums text-fg"><MoneyText :value="preview.totals.payments" :currency="form.currency" decimals="never" /></dd>
            </div>
          </dl>
          <ol class="flex flex-col divide-y divide-line rounded-[10px] border border-line bg-surface text-xs">
            <template v-for="(row, index) in shownRows" :key="row.position">
              <li v-if="hidden > 0 && index === shownRows.length - 1" class="px-3 py-1.5 text-center text-subtle">
                <button type="button" class="font-medium text-accent-fg hover:underline" @click="showAll = true">{{ t("finance.loans.showAll", { n: preview.rows.length }) }}</button>
              </li>
              <li class="flex items-center gap-2 px-3 py-1.5">
                <span class="w-5 shrink-0 tabular-nums text-subtle">{{ row.position }}</span>
                <span class="w-20 shrink-0 tabular-nums text-muted">{{ fmt.day(row.due_on, "short") }}</span>
                <span class="min-w-0 flex-1 truncate text-right font-medium tabular-nums text-fg"><MoneyText :value="row.payment" :currency="form.currency" decimals="never" /></span>
                <span class="hidden w-20 shrink-0 text-right tabular-nums text-subtle sm:inline" :title="t('finance.loans.col.balance')"><MoneyText :value="row.balance" :currency="form.currency" compact decimals="never" /></span>
              </li>
            </template>
          </ol>
          <p class="text-xs text-subtle">{{ t("finance.loans.previewNote") }}</p>
        </template>
        <SkeletonBlock v-else-if="previewing" height="180px" radius="10px" />
        <InlineAlert v-else-if="previewError" tone="warning" size="sm" :description="previewError" />
        <p v-else class="text-sm text-muted">{{ t("finance.loans.previewEmpty") }}</p>
      </aside>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-save-loan @click="save">{{ editing ? t("finance.loans.saveSchedule") : t("finance.loans.create") }}</UiButton>
    </template>
  </UiDialog>
</template>
