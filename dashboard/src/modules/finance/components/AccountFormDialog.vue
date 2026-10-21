<script setup lang="ts">
/**
 * Add or edit a money account: kind and currency (fixed once created, so history keeps its
 * meaning), name, branch, the person holding it, who may record on it, bank details (last four
 * digits only), whether it may go below zero, its colour, and an opening balance for a new one.
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import type { Currency } from "@/api/types";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MultiSelect from "@/components/MultiSelect.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { financeApi, useOptions, useRefresh } from "../api";
import { ACCOUNT_SWATCHES } from "../lib";
import AccountKindPicker from "./AccountKindPicker.vue";
import type { Account, AccountKind } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ account?: Account | null }>();
const emit = defineEmits<{ saved: [account: Account] }>();

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const options = useOptions(open);
const editing = computed(() => !!props.account);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});

const form = reactive({
  name: "",
  kind: "cash" as AccountKind,
  currency: company.currency as Currency,
  branch: null as number | null,
  holder: null as number | null,
  operators: [] as number[],
  bank_name: "",
  number_last4: "",
  allow_negative: false,
  color: "",
  opening_balance: null as string | null,
  opening_on: null as string | null,
});

watch(
  () => [open.value, props.account] as const,
  ([isOpen, account]) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    Object.assign(form, {
      name: account?.name ?? "",
      kind: account?.kind ?? "cash",
      currency: account?.currency ?? company.currency,
      branch: account?.branch?.id ?? null,
      holder: account?.holder?.id ?? null,
      operators: account?.operators.map((o) => o.id) ?? [],
      bank_name: account?.bank_name ?? "",
      number_last4: account?.number_last4 ?? "",
      allow_negative: account?.allow_negative ?? false,
      color: account?.color ?? "",
      opening_balance: null,
      opening_on: options.data.value?.today ?? null,
    });
  },
  { immediate: true },
);
watch(
  () => options.data.value?.today,
  (day) => {
    if (day && !form.opening_on) form.opening_on = day;
  },
);

const needsHolder = computed(() => form.kind === "employee" || form.kind === "owner");
const isBanky = computed(() => form.kind === "bank" || form.kind === "card");
const people = computed(() => (options.data.value?.members ?? []).map((m) => ({ value: m.id, label: m.name, description: m.position, avatar: { name: m.name } })));
const branchOptions = computed(() => (options.data.value?.branches ?? []).map((b) => ({ value: b.id, label: b.name, description: b.code })));

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.name.trim()) errors.name = t("finance.accounts.errName");
  if (!editing.value && needsHolder.value && !form.holder) errors.holder = t("finance.accounts.errHolder");
  if (form.number_last4 && !/^\d{4}$/.test(form.number_last4)) errors.number_last4 = t("finance.accounts.errLast4");
  if (Object.keys(errors).length) return;
  saving.value = true;
  const cid = company.currentId ?? 0;
  try {
    const common = {
      name: form.name.trim(),
      branch: form.branch,
      operators: form.operators,
      bank_name: isBanky.value ? form.bank_name : "",
      number_last4: isBanky.value ? form.number_last4 : "",
      allow_negative: form.allow_negative,
      color: form.color,
    };
    const saved = editing.value
      ? await financeApi.updateAccount(cid, props.account!.id, common)
      : await financeApi.createAccount(cid, {
          ...common,
          kind: form.kind,
          currency: form.currency,
          holder: needsHolder.value ? form.holder : null,
          opening_balance: form.opening_balance,
          opening_on: form.opening_balance ? form.opening_on : null,
        });
    toast.success(editing.value ? t("finance.accounts.saved") : t("finance.accounts.created", { name: saved.name }));
    emit("saved", saved);
    refresh();
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="editing ? t('finance.accounts.editTitle') : t('finance.accounts.newTitle')" :description="editing ? undefined : t('finance.accounts.newDescription')" size="lg">
    <div class="flex flex-col gap-4">
      <FormField v-if="!editing" :label="t('finance.accounts.kind')" required>
        <AccountKindPicker v-model="form.kind" />
        <p class="mt-1.5 text-xs text-muted">{{ t(`finance.accountKindHint.${form.kind}`) }}</p>
      </FormField>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto]">
        <FormField :label="t('finance.accounts.name')" :error="errors.name" required>
          <TextInput v-model="form.name" :maxlength="100" :placeholder="t(`finance.accounts.namePlaceholder.${form.kind}`)" autofocus />
        </FormField>
        <FormField v-if="!editing" :label="t('finance.field.currency')">
          <SegmentedControl v-model="form.currency" :options="[{ value: 'UZS', label: 'UZS' }, { value: 'USD', label: 'USD' }]" />
        </FormField>
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('finance.field.branch')" :hint="t('finance.accounts.branchHint')" optional>
          <SelectBox v-model="form.branch" :options="branchOptions" clearable :placeholder="t('finance.accounts.companyLevel')" />
        </FormField>
        <FormField v-if="needsHolder && !editing" :label="t('finance.accounts.holder')" :error="errors.holder" required>
          <SelectBox v-model="form.holder" :options="people" :placeholder="t('finance.accounts.pickPerson')" />
        </FormField>
        <FormField v-else :label="t('finance.accounts.operators')" :hint="t('finance.accounts.operatorsHint')" optional>
          <MultiSelect v-model="form.operators" :options="people" :placeholder="t('finance.accounts.pickPeople')" />
        </FormField>
      </div>
      <FormField v-if="needsHolder && !editing" :label="t('finance.accounts.operators')" :hint="t('finance.accounts.operatorsHint')" optional>
        <MultiSelect v-model="form.operators" :options="people" :placeholder="t('finance.accounts.pickPeople')" />
      </FormField>
      <div v-if="isBanky" class="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_140px]">
        <FormField :label="t('finance.accounts.bank')" optional>
          <TextInput v-model="form.bank_name" :maxlength="100" placeholder="Kapitalbank" />
        </FormField>
        <FormField :label="t('finance.accounts.last4')" :error="errors.number_last4" :hint="t('finance.accounts.last4Hint')" optional>
          <TextInput v-model="form.number_last4" :maxlength="4" inputmode="numeric" mono placeholder="4417" />
        </FormField>
      </div>
      <div class="grid grid-cols-1 items-start gap-3 sm:grid-cols-2">
        <FormField :label="t('finance.accounts.color')" optional>
          <div class="flex flex-wrap items-center gap-1.5">
            <button
              v-for="swatch in ACCOUNT_SWATCHES"
              :key="swatch"
              type="button"
              :class="['size-6 rounded-full border-2 transition-transform hover:scale-110', form.color === swatch ? 'border-fg' : 'border-transparent']"
              :style="{ background: swatch }"
              :aria-label="swatch"
              :aria-pressed="form.color === swatch"
              @click="form.color = swatch"
            />
            <button type="button" :class="['h-6 rounded-full border px-2 text-xs font-medium', form.color === '' ? 'border-fg text-fg' : 'border-line text-muted']" @click="form.color = ''">
              {{ t("finance.accounts.autoColor") }}
            </button>
          </div>
        </FormField>
        <ToggleSwitch v-model="form.allow_negative" class="sm:pt-6" :label="t('finance.accounts.allowNegative')" :description="t('finance.accounts.allowNegativeHint')" layout="row" />
      </div>
      <div v-if="!editing" class="grid grid-cols-1 gap-3 rounded-[12px] bg-surface-2 p-3 sm:grid-cols-2">
        <FormField :label="t('finance.accounts.opening')" :hint="t('finance.accounts.openingHint')" optional>
          <MoneyInput v-model="form.opening_balance" :currencies="[form.currency]" negative />
        </FormField>
        <FormField :label="t('finance.accounts.openingOn')" optional>
          <DatePicker v-model="form.opening_on" :max="options.data.value?.today ?? null" />
        </FormField>
      </div>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" @click="save">{{ editing ? t("common.save") : t("finance.accounts.create") }}</UiButton>
    </template>
  </UiDialog>
</template>
