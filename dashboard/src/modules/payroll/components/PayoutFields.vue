<script setup lang="ts">
/**
 * How money leaves: the method (cash, card, bank transfer) and the finance account it comes
 * from, in the currency being paid. Used by "Mark paid" on a run and "Pay" on an advance.
 * The accounts come from finance (only someone who may record money sees them); the first
 * account that suits the method is chosen for them.
 */
import { Banknote, CreditCard, Landmark } from "@lucide/vue";
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { Currency } from "@/api/types";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";

import { useAccounts } from "../api";
import { accountsFor, suitsMethod } from "../lib";
import type { PayoutMethod } from "../types";

const method = defineModel<PayoutMethod>("method", { required: true });
const account = defineModel<number | null>("account", { required: true });
const props = withDefaults(defineProps<{ currency: Currency; enabled?: boolean; error?: string | null }>(), { enabled: true, error: null });

const { t, te } = useI18n();
const accounts = useAccounts(() => props.enabled);
const choices = computed(() => accountsFor(accounts.data.value ?? [], props.currency, method.value));
const options = computed(() => choices.value.map((row) => ({ value: row.id, label: row.name, description: te(`payroll.accountKind.${row.kind}`) ? t(`payroll.accountKind.${row.kind}`) : undefined })));

// A method change (or the accounts arriving) picks the first account that suits it, unless the
// chosen one already does.
watch(
  [choices, method],
  () => {
    const chosen = choices.value.find((row) => row.id === account.value);
    if (chosen && suitsMethod(chosen.kind, method.value)) return;
    account.value = choices.value[0]?.id ?? null;
  },
  { immediate: true },
);
</script>

<template>
  <div class="flex flex-col gap-4">
    <FormField :label="t('payroll.payout.method')" required>
      <SegmentedControl
        v-model="method"
        block
        :options="[
          { value: 'cash', label: t('payroll.method.cash'), icon: Banknote },
          { value: 'card', label: t('payroll.method.card'), icon: CreditCard },
          { value: 'bank', label: t('payroll.method.bank'), icon: Landmark },
        ]"
      />
    </FormField>
    <FormField :label="t('payroll.payout.account')" :error="error" required :hint="t('payroll.payout.accountHint')">
      <SkeletonBlock v-if="accounts.isPending.value" height="40px" radius="8px" />
      <ErrorState v-else-if="accounts.isError.value" compact :error="accounts.error.value" :retry="() => accounts.refetch()" />
      <InlineAlert v-else-if="!options.length" tone="warning" size="sm" :description="t('payroll.payout.noAccount', { currency: currency })" />
      <SelectBox v-else v-model="account" :options="options" :invalid="!!error" />
    </FormField>
  </div>
</template>
