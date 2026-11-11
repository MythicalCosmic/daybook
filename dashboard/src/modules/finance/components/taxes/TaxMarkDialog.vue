<script setup lang="ts">
/**
 * Mark a tax deadline done (v12). A payment is recorded now (an expense "Taxes" to the tax office
 * from an account, the estimate filled in), linked to a payment already in the books (the tax
 * payments around the deadline are offered), or only marked. A filing deadline is marked filed.
 */
import { Link2, Receipt, Wallet } from "@lucide/vue";
import { useQuery } from "@tanstack/vue-query";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import RadioCards from "@/components/RadioCards.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { financeKeys, useOptions, useRefresh } from "../../api";
import { creditApi, type TaxDeadline } from "../../credit";
import { pickerOrder } from "../../lib";
import AccountChips from "../AccountChips.vue";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ deadline: TaxDeadline }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const options = useOptions(open);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const filing = computed(() => props.deadline.action === "file");
const form = reactive({ how: "record" as "record" | "link" | "mark", account: null as number | null, amount: null as string | null, done_on: null as string | null, transaction: null as number | null, note: "" });

const candidates = useQuery({
  queryKey: computed(() => financeKeys.of(company.currentId ?? 0, "tax-candidates", { key: props.deadline.key })),
  queryFn: () => creditApi.candidates(company.currentId ?? 0, props.deadline.key),
  enabled: computed(() => open.value && !filing.value && form.how === "link"),
  staleTime: 10_000,
});
const accounts = computed(() => pickerOrder((options.data.value?.accounts ?? []).filter((a) => a.currency === company.currency)));
const howOptions = computed(() => [
  { value: "record" as const, label: t("finance.taxes.mark.record"), description: t("finance.taxes.mark.recordHint"), icon: Wallet },
  { value: "link" as const, label: t("finance.taxes.mark.link"), description: t("finance.taxes.mark.linkHint"), icon: Link2 },
  { value: "mark" as const, label: t("finance.taxes.mark.only"), description: t("finance.taxes.mark.onlyHint"), icon: Receipt },
]);

function fill(): void {
  if (!form.done_on && options.data.value) form.done_on = options.data.value.today;
  if (form.account === null) form.account = accounts.value.find((a) => a.kind === "bank")?.id ?? accounts.value[0]?.id ?? null;
}
watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    Object.assign(form, { how: "record", account: null, amount: props.deadline.estimate, done_on: options.data.value?.today ?? null, transaction: null, note: "" });
    fill();
  },
  { immediate: true },
);
watch(() => options.data.value, fill);

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!filing.value && form.how === "record") {
    if (!form.account) errors.account = t("finance.quick.errAccount");
    if (!form.amount) errors.amount = t("finance.quick.errAmount");
  }
  if (!filing.value && form.how === "link" && !form.transaction) errors.transaction = t("finance.taxes.mark.errPick");
  if (Object.keys(errors).length) return;
  saving.value = true;
  try {
    await creditApi.mark(company.currentId ?? 0, {
      rule: props.deadline.rule,
      period_start: props.deadline.period_start,
      done_on: form.done_on!,
      transaction: !filing.value && form.how === "link" ? form.transaction : null,
      account: !filing.value && form.how === "record" ? form.account : null,
      amount: !filing.value && form.how !== "link" ? form.amount || null : null,
      note: form.note,
    });
    toast.success(filing.value ? t("finance.taxes.mark.filed") : t("finance.taxes.mark.paid"));
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
  <UiDialog v-model:open="open" :title="filing ? t('finance.taxes.mark.fileTitle') : t('finance.taxes.mark.payTitle')" :description="`${deadline.name} · ${deadline.period_label}`" size="md">
    <div class="flex flex-col gap-4">
      <div class="flex flex-wrap items-center justify-between gap-2 rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm">
        <span class="text-muted">{{ t("finance.taxes.dueOn", { date: fmt.day(deadline.due_on, "long") }) }}</span>
        <span v-if="deadline.estimate" class="font-semibold tabular-nums text-fg">
          <template v-if="!deadline.booked">≈ </template><MoneyText :value="deadline.estimate" :currency="deadline.currency" decimals="never" />
        </span>
      </div>
      <template v-if="!filing">
        <RadioCards v-model="form.how" :options="howOptions" :columns="3" />
        <template v-if="form.how === 'record'">
          <FormField :label="t('finance.taxes.mark.amount')" :error="errors.amount" :hint="deadline.estimate ? t('finance.taxes.mark.amountHint') : undefined" required>
            <MoneyInput v-model="form.amount" :currencies="[deadline.currency]" :invalid="!!errors.amount" />
          </FormField>
          <FormField :label="t('finance.debts.fromAccount')" :error="errors.account" required>
            <AccountChips v-model="form.account" :accounts="accounts" :invalid="!!errors.account" />
          </FormField>
        </template>
        <FormField v-else-if="form.how === 'link'" :label="t('finance.taxes.mark.pick')" :error="errors.transaction" required>
          <SkeletonBlock v-if="candidates.isPending.value" height="96px" radius="10px" />
          <EmptyState v-else-if="!candidates.data.value?.length" size="sm" :icon="Link2" :title="t('finance.taxes.mark.none')" :description="t('finance.taxes.mark.noneBody')" />
          <ul v-else class="flex max-h-60 flex-col divide-y divide-line overflow-y-auto rounded-[10px] border border-line" role="radiogroup">
            <li v-for="row in candidates.data.value" :key="row.id">
              <label :class="['flex cursor-pointer items-center gap-3 px-3 py-2 text-sm', form.transaction === row.id && 'bg-accent-soft/40']">
                <input v-model="form.transaction" type="radio" :value="row.id" class="accent-[var(--c-accent)]" />
                <span class="w-20 shrink-0 tabular-nums text-muted">{{ fmt.day(row.occurred_on, "medium") }}</span>
                <span class="min-w-0 flex-1 truncate text-fg">{{ row.description || row.category || row.account }}</span>
                <span class="shrink-0 font-semibold tabular-nums text-fg"><MoneyText :value="row.amount" decimals="never" /></span>
              </label>
            </li>
          </ul>
        </FormField>
        <FormField v-else :label="t('finance.taxes.mark.amountPaid')" optional>
          <MoneyInput v-model="form.amount" :currencies="[deadline.currency]" />
        </FormField>
      </template>
      <FormField :label="filing ? t('finance.taxes.mark.filedOn') : t('finance.debts.paidOn')" required>
        <DatePicker v-model="form.done_on" :max="options.data.value?.today ?? null" />
      </FormField>
      <FormField :label="t('finance.field.note')" optional>
        <TextInput v-model="form.note" :maxlength="300" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-save-mark @click="save">{{ filing ? t("finance.taxes.mark.saveFiled") : t("finance.taxes.mark.savePaid") }}</UiButton>
    </template>
  </UiDialog>
</template>
