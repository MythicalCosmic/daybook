<script setup lang="ts">
/**
 * Add or edit a counterparty (the one party directory: customers, suppliers, the landlord, the
 * tax office): name, kind, phone (+998…), taxpayer number, contact, Telegram, address, bank
 * details for invoices, a default category, a credit limit, tags and notes.
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import ComboBox from "@/components/ComboBox.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MultiSelect from "@/components/MultiSelect.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { financeApi, useCategories, useRefresh } from "../api";
import { categoryOptions } from "../lib";
import type { Counterparty, CounterpartyKind } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ party?: Counterparty | null }>();
const emit = defineEmits<{ saved: [party: Counterparty] }>();

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const categories = useCategories(open);
const editing = computed(() => !!props.party);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});

const empty = () => ({
  name: "",
  kind: "customer" as CounterpartyKind,
  phone: "",
  tin: "",
  contact_person: "",
  telegram_username: "",
  address: "",
  bank_details: "",
  notes: "",
  default_category: null as number | null,
  credit_limit: null as string | null,
  credit_blocked: false,
  tags: [] as string[],
  is_active: true,
});
const form = reactive(empty());

watch(
  () => [open.value, props.party] as const,
  ([isOpen, party]) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    Object.assign(form, empty(), party ? { ...party, default_category: party.default_category?.id ?? null } : {});
  },
  { immediate: true },
);

const kinds = computed(() => (["customer", "supplier", "both", "state", "other"] as const).map((kind) => ({ value: kind, label: t(`finance.partyKind.${kind}`) })));
const categoryChoices = computed(() => categoryOptions(categories.data.value, null, { activeOnly: true }));
const tagOptions = computed(() => form.tags.map((tag) => ({ value: tag, label: tag })));

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.name.trim()) {
    errors.name = t("finance.parties.errName");
    return;
  }
  saving.value = true;
  try {
    const payload = { ...form, name: form.name.trim() };
    const saved = editing.value ? await financeApi.updateCounterparty(company.currentId ?? 0, props.party!.id, payload) : await financeApi.createCounterparty(company.currentId ?? 0, payload);
    toast.success(editing.value ? t("finance.parties.saved") : t("finance.parties.created", { name: saved.name }));
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
  <UiDialog v-model:open="open" :title="editing ? t('finance.parties.editTitle') : t('finance.parties.newTitle')" size="lg">
    <div class="flex flex-col gap-4">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_200px]">
        <FormField :label="t('finance.parties.name')" :error="errors.name" required>
          <TextInput v-model="form.name" :maxlength="200" :placeholder="t('finance.parties.namePlaceholder')" autofocus />
        </FormField>
        <FormField :label="t('finance.parties.kind')">
          <SelectBox v-model="form.kind" :options="kinds" />
        </FormField>
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <FormField :label="t('finance.parties.phone')" :error="errors.phone" optional>
          <TextInput v-model="form.phone" type="tel" inputmode="tel" placeholder="+998 90 123 45 67" />
        </FormField>
        <FormField :label="t('finance.parties.tin')" :error="errors.tin" optional>
          <TextInput v-model="form.tin" inputmode="numeric" :maxlength="14" mono placeholder="305112874" />
        </FormField>
        <FormField :label="t('finance.parties.telegram')" optional>
          <TextInput v-model="form.telegram_username" prefix="@" :maxlength="64" />
        </FormField>
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('finance.parties.contact')" optional>
          <TextInput v-model="form.contact_person" :maxlength="100" />
        </FormField>
        <FormField :label="t('finance.parties.address')" optional>
          <TextInput v-model="form.address" :maxlength="255" />
        </FormField>
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('finance.parties.defaultCategory')" :hint="t('finance.parties.defaultCategoryHint')" optional>
          <ComboBox v-model="form.default_category" :options="categoryChoices" clearable />
        </FormField>
        <FormField :label="t('finance.parties.creditLimit')" :hint="t('finance.parties.creditLimitHint')" optional>
          <MoneyInput v-model="form.credit_limit" />
        </FormField>
      </div>
      <FormField :label="t('finance.parties.tags')" optional>
        <MultiSelect v-model="form.tags" :options="tagOptions" creatable :placeholder="t('finance.parties.tagsPlaceholder')" @create="(tag: string) => form.tags.push(tag)" />
      </FormField>
      <FormField :label="t('finance.parties.bankDetails')" :hint="t('finance.parties.bankDetailsHint')" optional>
        <TextArea v-model="form.bank_details" :rows="2" autosize />
      </FormField>
      <FormField :label="t('finance.parties.notes')" optional>
        <TextArea v-model="form.notes" :rows="2" autosize />
      </FormField>
      <div v-if="editing" class="flex flex-col gap-2">
        <ToggleSwitch v-model="form.credit_blocked" :label="t('finance.parties.blocked')" :description="t('finance.parties.blockedHint')" layout="row" />
        <ToggleSwitch v-model="form.is_active" :label="t('finance.parties.active')" layout="row" />
      </div>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" @click="save">{{ editing ? t("common.save") : t("finance.parties.create") }}</UiButton>
    </template>
  </UiDialog>
</template>
