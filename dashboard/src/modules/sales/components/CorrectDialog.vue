<script setup lang="ts">
/**
 * Correct a closed shift's totals (a typo in the cash total, a method mixed up): per payment
 * method sales and refunds, optionally the cash as the manager counted it, and a reason (required,
 * audited). The server recomputes the difference and voids and rebooks exactly what changed.
 */
import { PencilLine } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { subtract, sum } from "@/lib/decimal";

import { salesApi, useOptions, useShiftWrite } from "../api";
import { METHOD_ICONS } from "../format";
import type { MethodKind, PaymentLineInput, ShiftDetail } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ shift: ShiftDetail }>();

const { t } = useI18n();
const options = useOptions();

interface Line {
  id: number;
  name: string;
  kind: MethodKind;
  sales: string | null;
  refunds: string | null;
}

const lines = ref<Line[]>([]);
const counted = ref<string | null>(null);
const reason = ref("");
const reasonError = ref<string | null>(null);

function reset(): void {
  const typed = new Map(props.shift.payments.map((p) => [p.method.id, p]));
  const methods = options.data.value?.methods ?? props.shift.payments.map((p) => ({ ...p.method, is_active: true }));
  lines.value = methods
    .filter((m) => m.is_active || typed.has(m.id))
    .map((m) => ({ id: m.id, name: m.name, kind: m.kind, sales: typed.get(m.id)?.sales ?? null, refunds: typed.get(m.id)?.refunds ?? null }));
  counted.value = null;
  reason.value = "";
  reasonError.value = null;
}
watch(open, (value) => value && reset());
watch(() => options.data.value, () => open.value && reset());

const net = computed(() => sum(lines.value.map((line) => subtract(line.sales || "0", line.refunds || "0"))));
const correct = useShiftWrite((cid, vars: { id: number; payments: PaymentLineInput[]; reason: string; counted_cash: string | null }) =>
  salesApi.correct(cid, vars.id, { payments: vars.payments, reason: vars.reason, counted_cash: vars.counted_cash }),
);

async function submit(): Promise<void> {
  if (!reason.value.trim()) {
    reasonError.value = t("sales.correct.reasonRequired");
    return;
  }
  const payments = lines.value
    .filter((line) => line.sales || line.refunds)
    .map((line) => ({ method_id: line.id, sales: line.sales || "0", refunds: line.refunds || "0" }));
  await correct.mutateAsync({ id: props.shift.id, payments, reason: reason.value.trim(), counted_cash: counted.value || null });
  toast.success(t("sales.correct.done", { code: props.shift.code }));
  open.value = false;
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('sales.correct.title', { code: shift.code })" :description="t('sales.correct.body')" size="lg">
    <div class="flex flex-col gap-4">
      <div class="overflow-hidden rounded-[12px] border border-line">
        <div class="grid grid-cols-[minmax(0,1fr)_140px_140px] gap-2 border-b border-line bg-surface-2/60 px-3 py-2 text-xs font-medium text-muted max-sm:grid-cols-[minmax(0,1fr)_110px_110px]">
          <span>{{ t("sales.correct.method") }}</span>
          <span class="text-right">{{ t("sales.payments.sales") }}</span>
          <span class="text-right">{{ t("sales.payments.refunds") }}</span>
        </div>
        <div class="max-h-[46vh] overflow-y-auto">
          <div
            v-for="line in lines"
            :key="line.id"
            class="grid grid-cols-[minmax(0,1fr)_140px_140px] items-center gap-2 border-b border-line px-3 py-1.5 last:border-b-0 max-sm:grid-cols-[minmax(0,1fr)_110px_110px]"
          >
            <span class="flex min-w-0 items-center gap-2 text-sm font-medium text-fg">
              <component :is="METHOD_ICONS[line.kind]" :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
              <span class="truncate">{{ line.name }}</span>
            </span>
            <MoneyInput v-model="line.sales" size="sm" :aria-label="`${line.name} ${t('sales.payments.sales')}`" />
            <MoneyInput v-model="line.refunds" size="sm" :aria-label="`${line.name} ${t('sales.payments.refunds')}`" />
          </div>
        </div>
        <div class="flex items-center justify-between border-t border-line bg-surface-2/60 px-3 py-2 text-sm">
          <span class="font-medium text-muted">{{ t("sales.correct.newNet") }}</span>
          <span class="font-semibold text-fg"><MoneyText :value="net" /></span>
        </div>
      </div>
      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('sales.correct.counted')" :hint="t('sales.correct.countedHint')" optional>
          <MoneyInput v-model="counted" />
        </FormField>
        <FormField :label="t('sales.correct.reason')" :error="reasonError" required>
          <TextInput v-model="reason" :maxlength="300" :placeholder="t('sales.correct.reasonPlaceholder')" @update:model-value="reasonError = null" />
        </FormField>
      </div>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="PencilLine" :loading="correct.isPending.value" @click="submit">{{ t("sales.correct.submit") }}</UiButton>
    </template>
  </UiDialog>
</template>
