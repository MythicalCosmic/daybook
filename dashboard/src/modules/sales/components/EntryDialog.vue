<script setup lang="ts">
/**
 * A single receipt entered from the dashboard (a wholesale order, a sale made away from the till):
 * branch, sale or refund, how it was paid (one or several methods) and a note. It books into the
 * ledger on its own; receipts inside a shift come from Kassa.
 */
import { Plus, ReceiptText, Trash2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { sum } from "@/lib/decimal";

import { salesApi, useOptions, useSalesMutation } from "../api";
import type { EntryInput } from "../types";

const open = defineModel<boolean>("open", { default: false });
const { t } = useI18n();
const options = useOptions();

const branch = ref<number | null>(null);
const kind = ref<"sale" | "refund">("sale");
const lines = ref<Array<{ method: number | null; amount: string | null }>>([]);
const note = ref("");
const number = ref("");
const error = ref<string | null>(null);

watch(open, (value) => {
  if (!value) return;
  branch.value = options.data.value?.branches[0]?.id ?? null;
  kind.value = "sale";
  lines.value = [{ method: options.data.value?.methods.find((m) => m.kind === "cash")?.id ?? null, amount: null }];
  note.value = "";
  number.value = "";
  error.value = null;
});

const branches = computed(() => (options.data.value?.branches ?? []).map((b) => ({ value: b.id, label: b.name })));
const methods = computed(() => (options.data.value?.methods ?? []).filter((m) => m.is_active && m.kind !== "credit").map((m) => ({ value: m.id, label: m.name })));
const total = computed(() => sum(lines.value.map((line) => line.amount || "0")));
const kinds = computed(() => [
  { value: "sale" as const, label: t("sales.entries.sale") },
  { value: "refund" as const, label: t("sales.entries.refund") },
]);

const create = useSalesMutation((cid, input: EntryInput) => salesApi.createEntry(cid, input));
async function submit(): Promise<void> {
  const payments = lines.value.filter((line) => line.method && line.amount).map((line) => ({ method_id: line.method!, amount: line.amount! }));
  if (!branch.value || !payments.length) {
    error.value = t("sales.entries.needPayment");
    return;
  }
  await create.mutateAsync({ branch_id: branch.value, kind: kind.value, payments, note: note.value.trim(), number: number.value.trim() });
  toast.success(t("sales.entries.saved"));
  open.value = false;
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('sales.entries.newTitle')" :description="t('sales.entries.newBody')" size="md">
    <div class="flex flex-col gap-4">
      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('sales.filter.branch')" required>
          <SelectBox v-model="branch" :options="branches" />
        </FormField>
        <FormField :label="t('sales.entries.kind')">
          <SegmentedControl v-model="kind" :options="kinds" block :aria-label="t('sales.entries.kind')" />
        </FormField>
      </div>
      <FormField :label="t('sales.entries.payments')" :error="error" required>
        <div class="flex flex-col gap-2">
          <div v-for="(line, index) in lines" :key="index" class="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_32px] items-center gap-2">
            <SelectBox v-model="line.method" :options="methods" :placeholder="t('sales.entries.method')" />
            <MoneyInput v-model="line.amount" @update:model-value="error = null" />
            <IconButton v-if="lines.length > 1" :icon="Trash2" :label="t('common.delete')" size="sm" @click="lines.splice(index, 1)" />
          </div>
          <div class="flex items-center justify-between">
            <UiButton variant="link" size="sm" :icon="Plus" @click="lines.push({ method: null, amount: null })">{{ t("sales.entries.addMethod") }}</UiButton>
            <span class="text-sm text-muted">{{ t("sales.entries.total") }} <MoneyText :value="total" class="font-semibold text-fg" /></span>
          </div>
        </div>
      </FormField>
      <div class="grid gap-4 sm:grid-cols-[160px_minmax(0,1fr)]">
        <FormField :label="t('sales.entries.number')" optional><TextInput v-model="number" :maxlength="32" /></FormField>
        <FormField :label="t('sales.entries.note')" optional><TextInput v-model="note" :maxlength="300" :placeholder="t('sales.entries.notePlaceholder')" /></FormField>
      </div>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="ReceiptText" :loading="create.isPending.value" @click="submit">{{ t("sales.entries.submit") }}</UiButton>
    </template>
  </UiDialog>
</template>
