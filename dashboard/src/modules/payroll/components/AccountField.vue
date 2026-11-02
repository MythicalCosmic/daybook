<script setup lang="ts">
/**
 * The finance account money goes out of (or comes back into), in the currency at hand: the ones
 * that suit the payout method first. Shows the loading, failure and "no account in so‘m" states.
 * The accounts come from finance (only someone who may record money sees them).
 */
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { Currency } from "@/api/types";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";

import { useAccounts } from "../api";
import { accountsFor, suitsMethod } from "../lib";
import type { PayoutMethod } from "../types";

const account = defineModel<number | null>({ required: true });
const props = withDefaults(
  defineProps<{ currency: Currency; method?: PayoutMethod; label: string; hint?: string; enabled?: boolean; error?: string | null }>(),
  { method: "cash", hint: undefined, enabled: true, error: null },
);

const { t, te } = useI18n();
const accounts = useAccounts(() => props.enabled);
const choices = computed(() => accountsFor(accounts.data.value ?? [], props.currency, props.method));
const options = computed(() => choices.value.map((row) => ({ value: row.id, label: row.name, description: te(`payroll.accountKind.${row.kind}`) ? t(`payroll.accountKind.${row.kind}`) : undefined })));

// A method change (or the accounts arriving) picks the first account that suits it, unless the
// chosen one already does.
watch(
  [choices, () => props.method],
  () => {
    const chosen = choices.value.find((row) => row.id === account.value);
    if (chosen && suitsMethod(chosen.kind, props.method)) return;
    account.value = choices.value[0]?.id ?? null;
  },
  { immediate: true },
);
</script>

<template>
  <FormField :label="label" :error="error" required :hint="hint">
    <SkeletonBlock v-if="accounts.isPending.value" height="40px" radius="8px" />
    <ErrorState v-else-if="accounts.isError.value" compact :error="accounts.error.value" :retry="() => accounts.refetch()" />
    <InlineAlert v-else-if="!options.length" tone="warning" size="sm" :description="t('payroll.payout.noAccount', { currency })" />
    <SelectBox v-else v-model="account" :options="options" :invalid="!!error" data-testid="account-select" />
  </FormField>
</template>
