<script setup lang="ts">
/**
 * "Add expense to project": an expense on the finance ledger (`finance.services.record_transaction`
 * with the project), from an account the person may record on, in an expense category.
 */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { Money } from "@/api/types";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { addExpense, useCompanyId, useExpenseOptions, useRefreshProjects } from "../api";
import type { ProjectDetail } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ project: ProjectDetail }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const companyId = useCompanyId();
const refresh = useRefreshProjects();
const options = useExpenseOptions(() => props.project.id, open);

const amount = ref<Money | null>(null);
const account = ref<number | null>(null);
const category = ref<number | null>(null);
const counterparty = ref<number | null>(null);
const occurredOn = ref<string | null>(null);
const description = ref("");
const errors = ref<Record<string, string>>({});
const saving = ref(false);

const accountOptions = computed(() =>
  (options.data.value?.accounts ?? []).map((a) => ({ value: a.id, label: a.name, description: `${fmt.money(a.balance, a.currency)} · ${a.currency}` })),
);
const categoryOptions = computed(() => {
  const all = options.data.value?.categories ?? [];
  return all.map((c) => ({ value: c.id, label: c.name, group: c.parent_id ? all.find((p) => p.id === c.parent_id)?.name : undefined }));
});
const counterpartyOptions = computed(() => (options.data.value?.counterparties ?? []).map((c) => ({ value: c.id, label: c.name })));
const currency = computed(() => options.data.value?.accounts.find((a) => a.id === account.value)?.currency ?? company.currency);

watch(open, (value) => {
  if (!value) return;
  amount.value = null;
  category.value = null;
  counterparty.value = null;
  occurredOn.value = todayIn(company.timezone);
  description.value = "";
  errors.value = {};
});
watch(
  () => options.data.value?.accounts,
  (accounts) => {
    if (accounts?.length && !accounts.some((a) => a.id === account.value)) account.value = accounts[0]!.id;
  },
);

async function save(): Promise<void> {
  errors.value = {};
  if (!amount.value || Number(amount.value) <= 0) errors.value.amount = t("projects.money.amountRequired");
  if (!account.value) errors.value.account = t("projects.money.accountRequired");
  if (!category.value) errors.value.category = t("projects.money.categoryRequired");
  if (Object.keys(errors.value).length) return;
  saving.value = true;
  try {
    await addExpense(companyId.value, props.project.id, {
      amount: amount.value!,
      account: account.value!,
      category: category.value!,
      occurred_on: occurredOn.value ?? todayIn(company.timezone),
      description: description.value.trim(),
      counterparty: counterparty.value,
    });
    toast.success(t("projects.money.added", { amount: fmt.money(amount.value!, currency.value) }));
    open.value = false;
    void refresh();
  } catch {
    // The HTTP layer showed why.
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('projects.money.addTitle')" :description="`${project.key} · ${project.name}`" size="md">
    <form id="expense-form" class="flex flex-col gap-4" @submit.prevent="save">
      <InlineAlert v-if="options.data.value && !options.data.value.accounts.length" tone="warning" :description="t('projects.money.noAccounts')" />
      <FormField :label="t('projects.money.amount')" :error="errors.amount" required>
        <MoneyInput v-model="amount" :currency="currency" :currencies="[currency]" autofocus />
      </FormField>
      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('projects.money.account')" :error="errors.account" required>
          <SelectBox v-model="account" :options="accountOptions" />
        </FormField>
        <FormField :label="t('projects.money.category')" :error="errors.category" required>
          <SelectBox v-model="category" :options="categoryOptions" :placeholder="t('projects.money.categoryPlaceholder')" />
        </FormField>
      </div>
      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('projects.money.date')">
          <DatePicker v-model="occurredOn" :max="todayIn(company.timezone)" />
        </FormField>
        <FormField :label="t('projects.money.supplier')" optional>
          <SelectBox v-model="counterparty" :options="counterpartyOptions" clearable :placeholder="t('projects.money.noSupplier')" />
        </FormField>
      </div>
      <FormField :label="t('projects.money.description')" optional>
        <TextInput v-model="description" :maxlength="300" :placeholder="t('projects.money.descriptionPlaceholder')" />
      </FormField>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="expense-form" :loading="saving">{{ t("projects.money.add") }}</UiButton>
    </template>
  </UiDialog>
</template>
