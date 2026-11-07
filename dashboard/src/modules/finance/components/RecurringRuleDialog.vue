<script setup lang="ts">
/**
 * A recurring payment (plan §1.6 "recurring bills (rent, utilities, internet) as reminders or
 * auto-posted"): what it is, a reminder that stays open until paid ("bill") or an entry posted by
 * itself on its day ("auto", which needs an account and a fixed amount), the category and who it is
 * paid to, the amount (or "it changes each time"), how often and on which day (a weekday for weekly
 * rules, a day of the month otherwise, 31 meaning the last day), what to do on a day off, and the
 * reminder. Every writable field of `recurring/` (v6-i contract §2).
 */
import { ChevronDown } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import CheckBox from "@/components/CheckBox.vue";
import ComboBox from "@/components/ComboBox.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import RadioCards from "@/components/RadioCards.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import type { SelectOption } from "@/components/options";
import { toast } from "@/components/useToast";
import { dec } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyStore, useCompanyToday } from "@/stores/company";

import { financeApi, searchCounterparties, useCategories, useOptions, useRefresh } from "../api";
import { ACCOUNT_ICONS, categoryOptions, pickerOrder, ruleDayFrom } from "../lib";
import type { CategoryKind, HolidayRule, RecurringFrequency, RecurringInput, RecurringMode, RecurringRule } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ rule?: RecurringRule | null }>(), { rule: null });
const emit = defineEmits<{ saved: [rule: RecurringRule] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const cid = useCompanyId();
const today = useCompanyToday();
const refresh = useRefresh();
const options = useOptions(open);
const categories = useCategories(open);
const saving = ref(false);
const more = ref(false);
const errors = reactive<Record<string, string | undefined>>({});

interface Form {
  name: string;
  kind: CategoryKind;
  mode: RecurringMode;
  frequency: RecurringFrequency;
  interval: number | null;
  day: number | null;
  on_holiday: HolidayRule;
  category: number | null;
  counterparty: number | null;
  account: number | null;
  branch: number | null;
  amount: string | null;
  amount_varies: boolean;
  starts_on: string | null;
  ends_on: string | null;
  remind_days_before: number | null;
  payer: number | null;
  create_task: boolean;
}

const form = reactive<Form>(blank());
const counterpartyOption = ref<SelectOption<number> | null>(null);

function blank(): Form {
  const start = today.value;
  return {
    name: "",
    kind: "expense",
    mode: "bill",
    frequency: "monthly",
    interval: 1,
    day: ruleDayFrom(start, "monthly"),
    on_holiday: "before",
    category: null,
    counterparty: null,
    account: null,
    branch: null,
    amount: null,
    amount_varies: false,
    starts_on: start,
    ends_on: null,
    remind_days_before: 3,
    payer: null,
    create_task: false,
  };
}

function fromRule(rule: RecurringRule): Form {
  return {
    name: rule.name,
    kind: rule.kind,
    mode: rule.mode,
    frequency: rule.frequency,
    interval: rule.interval,
    day: rule.day,
    on_holiday: rule.on_holiday,
    category: rule.category?.id ?? null,
    counterparty: rule.counterparty?.id ?? null,
    account: rule.account?.id ?? null,
    branch: rule.branch?.id ?? null,
    // A varying amount saved as 0 shows as an empty field, not "0".
    amount: rule.amount_varies && dec(rule.amount).isZero() ? null : rule.amount,
    amount_varies: rule.amount_varies,
    starts_on: rule.starts_on,
    ends_on: rule.ends_on,
    remind_days_before: rule.remind_days_before,
    payer: rule.payer?.id ?? null,
    create_task: rule.create_task ?? false,
  };
}

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    Object.assign(form, props.rule ? fromRule(props.rule) : blank());
    counterpartyOption.value = props.rule?.counterparty ? { value: props.rule.counterparty.id, label: props.rule.counterparty.name } : null;
    more.value = false;
    for (const key of Object.keys(errors)) delete errors[key];
  },
  { immediate: true },
);

// Choices ----------------------------------------------------------------------------------

const categoryChoices = computed(() => categoryOptions(categories.data.value, form.kind, { activeOnly: true }));

// The person's own changes only (not a rule loaded into the form): another kind drops a category
// of the old kind, an automatic entry gets a fixed amount and an account, and weekly days (1–7)
// and monthly ones (1–31) don't mix, so the day becomes the one the start date falls on.
function setKind(kind: CategoryKind): void {
  form.kind = kind;
  if (form.category && !categoryOptions(categories.data.value, kind).some((option) => option.value === form.category)) form.category = null;
}
function setMode(mode: RecurringMode | null): void {
  if (!mode) return;
  form.mode = mode;
  if (mode !== "auto") return;
  form.amount_varies = false;
  if (form.account === null) form.account = accounts.value[0]?.id ?? null;
}
function setFrequency(next: RecurringFrequency | null): void {
  if (!next) return;
  const before = form.frequency;
  form.frequency = next;
  if ((next === "weekly") !== (before === "weekly")) form.day = ruleDayFrom(form.starts_on ?? today.value, next);
}

const accounts = computed(() => pickerOrder(options.data.value?.accounts ?? [], { id: props.rule?.account?.id ?? null }));
const accountChoices = computed<SelectOption<number>[]>(() =>
  accounts.value.map((account) => ({ value: account.id, label: account.name, icon: ACCOUNT_ICONS[account.kind], description: account.currency !== company.currency ? account.currency : undefined })),
);
const account = computed(() => accounts.value.find((row) => row.id === form.account) ?? null);
const currency = computed(() => account.value?.currency ?? props.rule?.currency ?? company.currency);
const people = computed<SelectOption<number>[]>(() => (options.data.value?.members ?? []).map((m) => ({ value: m.id, label: m.name, description: m.position, avatar: { name: m.name } })));
const branches = computed<SelectOption<number>[]>(() => (options.data.value?.branches ?? []).map((b) => ({ value: b.id, label: b.name })));

const auto = computed(() => form.mode === "auto");

const frequencies = computed<SelectOption<RecurringFrequency>[]>(() =>
  (["weekly", "monthly", "quarterly", "yearly"] as const).map((value) => ({ value, label: t(`finance.recurring.frequency.${value}`) })),
);
const dayChoices = computed<SelectOption<number>[]>(() => {
  if (form.frequency === "weekly") return [1, 2, 3, 4, 5, 6, 7].map((day) => ({ value: day, label: t(`common.weekday.long.${day - 1}`) }));
  return Array.from({ length: 31 }, (_, index) => index + 1).map((day) => ({ value: day, label: day === 31 ? t("finance.recurring.lastDayOption") : String(day) }));
});
const holidays = computed<SelectOption<HolidayRule>[]>(() => (["before", "after", "keep"] as const).map((value) => ({ value, label: t(`finance.recurring.holiday.${value}`) })));

async function counterpartySource(query: string, signal: AbortSignal): Promise<SelectOption<number>[]> {
  const rows = await searchCounterparties(cid.value, query, signal);
  return rows.map((row) => ({ value: row.id, label: row.name, description: row.kind_label, avatar: { name: row.name } }));
}

// Saving -----------------------------------------------------------------------------------

function validate(): boolean {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.name.trim()) errors.name = t("finance.recurring.errName");
  if (!form.category) errors.category = t("finance.quick.errCategory");
  if (!form.day) errors.day = t("finance.recurring.errDay");
  if (!form.starts_on) errors.starts_on = t("finance.quick.errDay");
  if (form.ends_on && form.starts_on && form.ends_on < form.starts_on) errors.ends_on = t("finance.recurring.errEnds");
  const hasAmount = !!form.amount && dec(form.amount).gt(0);
  if (!form.amount_varies && !hasAmount) errors.amount = t("finance.quick.errAmount");
  if (auto.value && !form.account) errors.account = t("finance.recurring.errAccount");
  return Object.keys(errors).length === 0;
}

function body(): RecurringInput {
  return {
    name: form.name.trim(),
    kind: form.kind,
    mode: form.mode,
    frequency: form.frequency,
    interval: Math.max(1, form.interval ?? 1),
    day: form.day!,
    on_holiday: form.on_holiday,
    category: form.category!,
    counterparty: form.counterparty,
    account: form.account,
    branch: form.branch,
    amount: form.amount && dec(form.amount).gt(0) ? form.amount : "0.00",
    amount_varies: auto.value ? false : form.amount_varies,
    starts_on: form.starts_on!,
    ends_on: form.ends_on,
    remind_days_before: Math.max(0, form.remind_days_before ?? 0),
    payer: form.payer,
    // A task is for a bill someone pays by hand, and needs whoever pays it.
    create_task: !auto.value && form.payer !== null && form.create_task,
  };
}

const SHOWN = ["name", "kind", "mode", "frequency", "interval", "day", "on_holiday", "category", "counterparty", "account", "branch", "amount", "amount_varies", "starts_on", "ends_on", "remind_days_before", "payer", "create_task"];

async function save(): Promise<void> {
  if (!validate()) return;
  saving.value = true;
  try {
    const saved = props.rule ? await financeApi.updateRecurring(cid.value, props.rule.id, body()) : await financeApi.createRecurring(cid.value, body());
    toast.success(props.rule ? t("finance.recurring.saved") : t("finance.recurring.created", { name: saved.name }));
    refresh();
    emit("saved", saved);
    open.value = false;
  } catch (failure) {
    if (isApiError(failure)) {
      for (const [field, messages] of Object.entries(failure.fieldErrors)) errors[field] = messages[0];
      // Options that live behind "More" open it, so their message is seen.
      if (["on_holiday", "remind_days_before", "payer", "create_task", "branch"].some((field) => errors[field])) more.value = true;
    }
    const unshown = unshownFieldError(failure, SHOWN);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}

const unit = computed(() => t(`finance.recurring.unit.${form.frequency}`, { n: form.interval ?? 1 }, form.interval ?? 1));
const nextDates = computed(() => (props.rule?.upcoming ?? []).map((day) => fmt.day(day, "weekdayShort")).join(" · "));
</script>

<template>
  <UiDialog v-model:open="open" :title="rule ? t('finance.recurring.editTitle') : t('finance.recurring.newTitle')" :description="t('finance.recurring.dialogHint')" size="lg">
    <div class="flex flex-col gap-4" data-rule-form>
      <FormField :label="t('finance.recurring.field.name')" :error="errors.name" required>
        <TextInput v-model="form.name" :maxlength="100" :placeholder="t('finance.recurring.namePlaceholder')" :invalid="!!errors.name" />
      </FormField>

      <div class="flex flex-col gap-2">
        <SegmentedControl
          :model-value="form.kind"
          size="sm"
          :aria-label="t('finance.recurring.field.kind')"
          :options="[
            { value: 'expense', label: t('finance.quick.mode.expense') },
            { value: 'income', label: t('finance.quick.mode.income') },
          ]"
          @update:model-value="setKind"
        />
        <RadioCards
          :model-value="form.mode"
          :columns="2"
          @update:model-value="setMode"
          :options="[
            { value: 'bill', label: t('finance.recurring.mode.bill'), description: t('finance.recurring.mode.billHint') },
            { value: 'auto', label: t('finance.recurring.mode.auto'), description: t('finance.recurring.mode.autoHint') },
          ]"
        />
      </div>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('finance.field.category')" :error="errors.category" required>
          <ComboBox v-model="form.category" :options="categoryChoices" :placeholder="t('finance.quick.categoryPlaceholder')" :invalid="!!errors.category" />
        </FormField>
        <FormField :label="form.kind === 'income' ? t('finance.quick.fromWhom') : t('finance.quick.toWhom')" :error="errors.counterparty" optional>
          <ComboBox
            v-model="form.counterparty"
            :source="counterpartySource"
            :selected="counterpartyOption"
            clearable
            :placeholder="t('finance.recurring.partyPlaceholder')"
            @change="(option) => (counterpartyOption = (option as SelectOption<number> | null) ?? null)"
          />
        </FormField>
      </div>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="form.amount_varies ? t('finance.recurring.field.usualAmount') : t('finance.field.amount')" :error="errors.amount" :required="!form.amount_varies" :optional="form.amount_varies" :hint="form.amount_varies ? t('finance.recurring.variesHint') : undefined">
          <div class="flex flex-col gap-2">
            <MoneyInput v-model="form.amount" :currencies="[currency]" :invalid="!!errors.amount" />
            <CheckBox v-if="!auto" v-model="form.amount_varies" size="sm" :label="t('finance.recurring.field.varies')" />
          </div>
        </FormField>
        <FormField :label="auto ? t('finance.recurring.field.account') : t('finance.recurring.field.accountUsual')" :error="errors.account" :required="auto" :optional="!auto" :hint="auto ? t('finance.recurring.accountAutoHint') : t('finance.recurring.accountBillHint')">
          <SelectBox v-model="form.account" :options="accountChoices" :clearable="!auto" :placeholder="t('finance.quick.errAccount')" :invalid="!!errors.account" />
        </FormField>
      </div>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <FormField :label="t('finance.recurring.field.frequency')" :error="errors.frequency" required>
          <SelectBox :model-value="form.frequency" :options="frequencies" @update:model-value="setFrequency" />
        </FormField>
        <FormField :label="t('finance.recurring.field.interval')" :error="errors.interval">
          <NumberInput v-model="form.interval" :min="1" :max="24" :suffix="unit" />
        </FormField>
        <FormField :label="form.frequency === 'weekly' ? t('finance.recurring.field.weekday') : t('finance.recurring.field.day')" :error="errors.day" required :hint="form.frequency === 'quarterly' || form.frequency === 'yearly' ? t('finance.recurring.dayFromStart') : undefined">
          <SelectBox v-model="form.day" :options="dayChoices" :invalid="!!errors.day" />
        </FormField>
      </div>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('finance.recurring.field.starts')" :error="errors.starts_on" required>
          <DatePicker v-model="form.starts_on" :invalid="!!errors.starts_on" />
        </FormField>
        <FormField :label="t('finance.recurring.field.ends')" :error="errors.ends_on" optional>
          <DatePicker v-model="form.ends_on" :min="form.starts_on" clearable :placeholder="t('finance.recurring.never')" :invalid="!!errors.ends_on" />
        </FormField>
      </div>

      <p v-if="rule && nextDates" class="rounded-[10px] bg-surface-2 px-3 py-2 text-sm text-muted dark:bg-surface-3/60" data-next-dates>{{ t("finance.recurring.nextDates", { dates: nextDates }) }}</p>

      <button type="button" class="inline-flex w-fit items-center gap-1 text-sm font-semibold text-accent-fg hover:underline" :aria-expanded="more" @click="more = !more">
        {{ t("finance.recurring.moreOptions") }}<ChevronDown :size="14" :class="['transition-transform', more && 'rotate-180']" aria-hidden="true" />
      </button>
      <div v-if="more" class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('finance.recurring.field.holiday')" :error="errors.on_holiday">
          <SelectBox v-model="form.on_holiday" :options="holidays" />
        </FormField>
        <FormField :label="t('finance.recurring.field.remind')" :error="errors.remind_days_before" :hint="t('finance.recurring.remindHint')">
          <NumberInput v-model="form.remind_days_before" :min="0" :max="30" :suffix="t('finance.recurring.daysBefore', { n: form.remind_days_before ?? 0 }, form.remind_days_before ?? 0)" />
        </FormField>
        <FormField :label="t('finance.recurring.field.payer')" :error="errors.payer" :hint="t('finance.recurring.payerHint')" optional>
          <SelectBox v-model="form.payer" :options="people" clearable :placeholder="t('finance.recurring.payerPlaceholder')" />
        </FormField>
        <div v-if="!auto && form.payer !== null" class="sm:col-span-2" data-create-task>
          <CheckBox v-model="form.create_task" :label="t('finance.recurring.createTask')" :description="t('finance.recurring.createTaskHint')" />
          <p v-if="errors.create_task" class="mt-1 text-sm text-danger">{{ errors.create_task }}</p>
        </div>
        <FormField :label="t('finance.field.branch')" :error="errors.branch" optional>
          <SelectBox v-model="form.branch" :options="branches" clearable :placeholder="t('finance.quick.branchPlaceholder')" />
        </FormField>
      </div>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-save-rule @click="save">{{ rule ? t("common.save") : t("finance.recurring.create") }}</UiButton>
    </template>
  </UiDialog>
</template>
