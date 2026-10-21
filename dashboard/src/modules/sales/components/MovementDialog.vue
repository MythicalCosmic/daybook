<script setup lang="ts">
/**
 * Record a cash movement from a till (managers, from the dashboard): a payout (an expense with a
 * category), a handover to a person (it moves only when they confirm), cash to or from the safe,
 * to the bank, or a deposit from another account. The till's open shift picks it up.
 */
import { Banknote } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";

import { salesApi, useOptions, useSalesMutation } from "../api";
import { MOVEMENT_ICONS, MOVEMENT_KINDS } from "../format";
import type { MovementInput, MovementKind } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ registerId?: number | null; kind?: MovementKind }>(), { registerId: null, kind: "payout" });

const { t } = useI18n();
const fmt = useFormat();
const options = useOptions();

const register = ref<number | null>(null);
const kind = ref<MovementKind>("payout");
const amount = ref<string | null>(null);
const receiver = ref<number | null>(null);
const account = ref<number | null>(null);
const category = ref<number | null>(null);
const reason = ref("");
const errors = ref<Record<string, string>>({});

watch(open, (value) => {
  if (!value) return;
  register.value = props.registerId ?? options.data.value?.registers.find((r) => r.is_active)?.id ?? null;
  kind.value = props.kind;
  amount.value = null;
  receiver.value = null;
  account.value = null;
  category.value = options.data.value?.categories.find((c) => c.code === "other_expense")?.id ?? null;
  reason.value = "";
  errors.value = {};
});

const kinds = computed(() => MOVEMENT_KINDS.map((value) => ({ value, label: t(`sales.movement.kind.${value}`), icon: MOVEMENT_ICONS[value] })));
// "Chilonzor · Kassa 1", as the movements table writes it: every branch has a "Kassa 1", and the
// closed picker shows only the label.
const registerOptions = computed(() => (options.data.value?.registers ?? []).filter((r) => r.is_active).map((r) => ({ value: r.id, label: `${r.branch} · ${r.name}` })));
const branchOf = computed(() => options.data.value?.registers.find((r) => r.id === register.value)?.branch_id ?? null);
const receivers = computed(() =>
  (options.data.value?.receivers ?? []).map((p) => ({ value: p.id, label: p.name, avatar: { name: p.name }, description: branchOf.value && !p.branch_ids.includes(branchOf.value) ? t("sales.movement.otherBranch") : undefined })),
);
const accounts = computed(() => (options.data.value?.accounts ?? []).filter((a) => a.kind !== "safe" && a.kind !== "cash").map((a) => ({ value: a.id, label: a.name })));
const categories = computed(() => (options.data.value?.categories ?? []).map((c) => ({ value: c.id, label: c.name })));

const record = useSalesMutation((cid, input: MovementInput) => salesApi.recordMovement(cid, input));

async function submit(): Promise<void> {
  const next: Record<string, string> = {};
  if (!register.value) next.register = t("sales.movement.pickTill");
  if (!amount.value) next.amount = t("common.form.required");
  if (kind.value === "handover" && !receiver.value) next.receiver = t("sales.movement.pickReceiver");
  if ((kind.value === "to_bank" || kind.value === "deposit") && !account.value) next.account = t("sales.movement.pickAccount");
  if (kind.value === "payout" && !reason.value.trim()) next.reason = t("sales.movement.reasonRequired");
  errors.value = next;
  if (Object.keys(next).length) return;
  await record.mutateAsync({
    register_id: register.value!,
    kind: kind.value,
    amount: amount.value!,
    receiver_id: kind.value === "handover" ? receiver.value : null,
    to_account_id: kind.value === "to_bank" || kind.value === "deposit" ? account.value : null,
    category_id: kind.value === "payout" ? category.value : null,
    reason: reason.value.trim(),
  });
  toast.success(t(kind.value === "handover" ? "sales.movement.sentHandover" : "sales.movement.recorded", { amount: fmt.money(amount.value) }));
  open.value = false;
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('sales.movement.title')" :description="t('sales.movement.body')" size="md">
    <div class="flex flex-col gap-4">
      <div role="radiogroup" :aria-label="t('sales.movement.kindLabel')" class="grid grid-cols-3 gap-2 max-sm:grid-cols-2">
        <button
          v-for="option in kinds"
          :key="option.value"
          type="button"
          role="radio"
          :aria-checked="kind === option.value"
          :class="[
            'pressable flex items-center gap-2 rounded-[10px] border px-3 py-2.5 text-left text-sm font-medium transition-colors',
            kind === option.value ? 'border-primary bg-accent-soft text-accent-fg' : 'border-line text-fg hover:border-line-strong hover:bg-highlight',
          ]"
          @click="kind = option.value"
        >
          <component :is="option.icon" :size="16" class="shrink-0" aria-hidden="true" />
          <span class="min-w-0 truncate">{{ option.label }}</span>
        </button>
      </div>
      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('sales.movement.till')" :error="errors.register" required>
          <SelectBox v-model="register" :options="registerOptions" :placeholder="t('sales.movement.pickTill')" />
        </FormField>
        <FormField :label="t('sales.movement.amount')" :error="errors.amount" required>
          <MoneyInput v-model="amount" />
        </FormField>
      </div>
      <FormField v-if="kind === 'handover'" :label="t('sales.movement.receiver')" :error="errors.receiver" :hint="t('sales.movement.receiverHint')" required>
        <SelectBox v-model="receiver" :options="receivers" :placeholder="t('sales.movement.pickReceiver')" />
      </FormField>
      <FormField v-if="kind === 'to_bank' || kind === 'deposit'" :label="kind === 'to_bank' ? t('sales.movement.toAccount') : t('sales.movement.fromAccount')" :error="errors.account" required>
        <SelectBox v-model="account" :options="accounts" :placeholder="t('sales.movement.pickAccount')" />
      </FormField>
      <FormField v-if="kind === 'payout'" :label="t('sales.movement.category')">
        <SelectBox v-model="category" :options="categories" />
      </FormField>
      <FormField :label="t('sales.movement.reason')" :error="errors.reason" :required="kind === 'payout'" :optional="kind !== 'payout'">
        <TextInput v-model="reason" :maxlength="200" :placeholder="t(`sales.movement.reasonPlaceholder.${kind}`)" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="Banknote" :loading="record.isPending.value" @click="submit">{{ t("sales.movement.submit") }}</UiButton>
    </template>
  </UiDialog>
</template>
