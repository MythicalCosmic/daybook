<script setup lang="ts">
/**
 * How money leaves: the method (cash, card, bank transfer) and the finance account it comes
 * from, in the currency being paid. Used by "Mark paid" on a run and "Pay out" on an advance.
 */
import { Banknote, CreditCard, Landmark } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import type { Currency } from "@/api/types";
import FormField from "@/components/FormField.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";

import type { PayoutMethod } from "../types";
import AccountField from "./AccountField.vue";

const method = defineModel<PayoutMethod>("method", { required: true });
const account = defineModel<number | null>("account", { required: true });
withDefaults(defineProps<{ currency: Currency; enabled?: boolean; error?: string | null }>(), { enabled: true, error: null });

const { t } = useI18n();
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
    <AccountField v-model="account" :currency="currency" :method="method" :label="t('payroll.payout.account')" :hint="t('payroll.payout.accountHint')" :enabled="enabled" :error="error" />
  </div>
</template>
