<script setup lang="ts">
/**
 * Record a debt (plan §1.6 "nasiya/qarz"): owed to us or by us, by a counterparty or an employee,
 * the amount and currency, the days, and how it came about: money moved now (a loan, an advance),
 * sold or bought on credit (income or expense booked now, paid later), or owed from before the
 * books started (an opening debt).
 */
import { ArrowDownLeft, ArrowUpRight, Clock, HandCoins, ShoppingBag } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import type { Currency } from "@/api/types";
import ComboBox from "@/components/ComboBox.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import type { SelectOption } from "@/components/options";
import RadioCards from "@/components/RadioCards.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { financeApi, searchCounterparties, useCategories, useOptions, useRefresh } from "../api";
import { categoryOptions, pickerOrder } from "../lib";
import type { Debt, DebtDirection, DebtInput } from "../types";
import AccountChips from "./AccountChips.vue";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ direction?: DebtDirection; counterparty?: { id: number; name: string } | null }>(), { direction: "receivable", counterparty: null });
const emit = defineEmits<{ saved: [debt: Debt] }>();

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const options = useOptions(open);
const categories = useCategories(open);
const canManage = computed(() => company.can("finance.manage"));
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});

const form = reactive({
  direction: props.direction as DebtDirection,
  partyType: "counterparty" as "counterparty" | "member",
  counterparty: null as number | null,
  member: null as number | null,
  kind: "trade" as DebtInput["kind"],
  mode: "category" as DebtInput["mode"],
  amount: null as string | null,
  currency: company.currency as Currency,
  issued_on: null as string | null,
  due_on: null as string | null,
  account: null as number | null,
  category: null as number | null,
  responsible: null as number | null,
  description: "",
});
const partySelected = ref<SelectOption<number> | null>(null);

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    Object.assign(form, {
      direction: props.direction,
      partyType: "counterparty",
      counterparty: props.counterparty?.id ?? null,
      member: null,
      kind: "trade",
      mode: "category",
      amount: null,
      currency: company.currency,
      issued_on: options.data.value?.today ?? null,
      due_on: null,
      account: null,
      category: null,
      responsible: null,
      description: "",
    });
    partySelected.value = props.counterparty ? { value: props.counterparty.id, label: props.counterparty.name } : null;
  },
  { immediate: true },
);
watch(
  () => options.data.value?.today,
  (day) => {
    if (day && !form.issued_on) form.issued_on = day;
  },
);

const receivable = computed(() => form.direction === "receivable");
const KINDS = ["trade", "loan", "advance", "bill", "tax", "other"] as const;
const kindOptions = computed(() =>
  KINDS.filter((kind) => (kind === "advance" ? receivable.value : kind === "bill" || kind === "tax" ? !receivable.value : true)).map((kind) => ({ value: kind, label: t(`finance.debtKind.${kind}`) })),
);
const modeOptions = computed(() => [
  { value: "category" as const, label: receivable.value ? t("finance.debts.modeSold") : t("finance.debts.modeBought"), description: receivable.value ? t("finance.debts.modeSoldHint") : t("finance.debts.modeBoughtHint"), icon: ShoppingBag },
  { value: "account" as const, label: receivable.value ? t("finance.debts.modeLent") : t("finance.debts.modeBorrowed"), description: receivable.value ? t("finance.debts.modeLentHint") : t("finance.debts.modeBorrowedHint"), icon: HandCoins },
  ...(canManage.value ? [{ value: "opening" as const, label: t("finance.debts.modeOpening"), description: t("finance.debts.modeOpeningHint"), icon: Clock }] : []),
]);
watch(
  () => form.kind,
  (kind) => {
    if (kind === "loan" || kind === "advance") form.mode = "account";
    if (kind === "advance") form.partyType = "member";
  },
);
watch(
  () => form.direction,
  () => {
    if (!kindOptions.value.some((option) => option.value === form.kind)) form.kind = "trade";
    form.category = null;
  },
);

const accounts = computed(() => pickerOrder((options.data.value?.accounts ?? []).filter((a) => a.currency === form.currency)));
const categoryChoices = computed(() => categoryOptions(categories.data.value, receivable.value ? "income" : "expense", { activeOnly: true }));
const people = computed(() => (options.data.value?.members ?? []).map((m) => ({ value: m.id, label: m.name, description: m.position, avatar: { name: m.name } })));

async function partySource(q: string, signal: AbortSignal): Promise<SelectOption<number>[]> {
  const rows = await searchCounterparties(company.currentId ?? 0, q, signal);
  return rows.map((row) => ({ value: row.id, label: row.name, description: [row.kind_label, row.phone].filter(Boolean).join(" · "), avatar: { name: row.name } }));
}

async function createParty(name: string): Promise<void> {
  try {
    const created = await financeApi.createCounterparty(company.currentId ?? 0, { name, kind: receivable.value ? "customer" : "supplier" });
    form.counterparty = created.id;
    partySelected.value = { value: created.id, label: created.name };
  } catch {
    // The HTTP layer showed why.
  }
}

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (form.partyType === "counterparty" ? !form.counterparty : !form.member) errors.party = t("finance.debts.errParty");
  if (!form.amount) errors.amount = t("finance.quick.errAmount");
  if (form.mode === "account" && !form.account) errors.account = t("finance.quick.errAccount");
  if (form.mode === "category" && !form.category) errors.category = t("finance.quick.errCategory");
  if (Object.keys(errors).length) return;
  saving.value = true;
  try {
    const debt = await financeApi.createDebt(company.currentId ?? 0, {
      direction: form.direction,
      kind: form.kind,
      mode: form.mode,
      amount: form.amount!,
      currency: form.currency,
      issued_on: form.issued_on!,
      due_on: form.due_on,
      counterparty: form.partyType === "counterparty" ? form.counterparty : null,
      member: form.partyType === "member" ? form.member : null,
      account: form.mode === "account" ? form.account : null,
      category: form.mode === "category" ? form.category : null,
      responsible: form.responsible,
      description: form.description,
    });
    toast.success(t("finance.debts.created"));
    emit("saved", debt);
    refresh();
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field === "counterparty" || field === "member" ? "party" : field] = messages[0];
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('finance.debts.newTitle')" :description="t('finance.debts.newDescription')" size="lg">
    <div class="flex flex-col gap-4">
      <SegmentedControl
        v-model="form.direction"
        block
        :options="[
          { value: 'receivable', label: t('finance.debts.side.receivable'), icon: ArrowDownLeft },
          { value: 'payable', label: t('finance.debts.side.payable'), icon: ArrowUpRight },
        ]"
      />
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto]">
        <FormField :label="receivable ? t('finance.debts.whoOwes') : t('finance.debts.whomWeOwe')" :error="errors.party" required>
          <ComboBox
            v-if="form.partyType === 'counterparty'"
            v-model="form.counterparty"
            :source="partySource"
            :selected="partySelected"
            creatable
            :invalid="!!errors.party"
            :placeholder="t('finance.quick.partyPlaceholder')"
            @create="createParty"
          />
          <SelectBox v-else v-model="form.member" :options="people" :invalid="!!errors.party" :placeholder="t('finance.accounts.pickPerson')" />
        </FormField>
        <FormField :label="t('finance.debts.partyType')">
          <SegmentedControl
            v-model="form.partyType"
            size="sm"
            :options="[
              { value: 'counterparty', label: t('finance.debts.partyCounterparty') },
              { value: 'member', label: t('finance.debts.partyMember') },
            ]"
          />
        </FormField>
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('finance.field.amount')" :error="errors.amount" required>
          <MoneyInput v-model="form.amount" v-model:currency="form.currency" :currencies="['UZS', 'USD']" :invalid="!!errors.amount" />
        </FormField>
        <FormField :label="t('finance.debts.kind')">
          <SelectBox v-model="form.kind" :options="kindOptions" />
        </FormField>
      </div>
      <FormField :label="t('finance.debts.how')">
        <RadioCards v-model="form.mode" :options="modeOptions" :columns="modeOptions.length === 3 ? 3 : 2" />
      </FormField>
      <FormField v-if="form.mode === 'account'" :label="receivable ? t('finance.debts.paidFrom') : t('finance.debts.receivedTo')" :error="errors.account" required>
        <AccountChips v-model="form.account" :accounts="accounts" :invalid="!!errors.account" />
      </FormField>
      <FormField v-if="form.mode === 'category'" :label="t('finance.field.category')" :error="errors.category" required>
        <ComboBox v-model="form.category" :options="categoryChoices" :invalid="!!errors.category" />
      </FormField>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <FormField :label="t('finance.debts.issued')" required>
          <DatePicker v-model="form.issued_on" :max="options.data.value?.today ?? null" />
        </FormField>
        <FormField :label="t('finance.debts.due')" optional>
          <DatePicker v-model="form.due_on" :min="form.issued_on" clearable />
        </FormField>
        <FormField :label="t('finance.debts.responsible')" optional>
          <SelectBox v-model="form.responsible" :options="people" clearable />
        </FormField>
      </div>
      <FormField :label="t('finance.field.note')" optional>
        <TextInput v-model="form.description" :maxlength="300" :placeholder="t('finance.debts.notePlaceholder')" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" @click="save">{{ t("finance.debts.create") }}</UiButton>
    </template>
  </UiDialog>
</template>
