<script setup lang="ts">
/**
 * Close a shift the cashier left open (they went home, the phone died). A reason is required; the
 * cash may be counted now, or later through a correction: until then no difference is booked.
 */
import { LockKeyhole } from "@lucide/vue";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";

import { salesApi, useShiftWrite } from "../api";
import type { ShiftDetail } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ shift: ShiftDetail }>();

const { t } = useI18n();
const reason = ref("");
const counted = ref<string | null>(null);
const reasonError = ref<string | null>(null);
watch(open, (value) => {
  if (value) {
    reason.value = "";
    counted.value = null;
    reasonError.value = null;
  }
});

const close = useShiftWrite((cid, vars: { id: number; reason: string; counted_cash: string | null }) =>
  salesApi.forceClose(cid, vars.id, { reason: vars.reason, counted_cash: vars.counted_cash }),
);

async function submit(): Promise<void> {
  if (!reason.value.trim()) {
    reasonError.value = t("sales.correct.reasonRequired");
    return;
  }
  await close.mutateAsync({ id: props.shift.id, reason: reason.value.trim(), counted_cash: counted.value || null });
  toast.success(t("sales.force.done", { code: props.shift.code }));
  open.value = false;
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('sales.force.title', { code: shift.code })" :description="t('sales.force.body', { name: shift.cashier.name })" size="sm">
    <div class="flex flex-col gap-4">
      <InlineAlert tone="warning" size="sm" :description="t('sales.force.hint')" />
      <FormField :label="t('sales.correct.reason')" :error="reasonError" required>
        <TextInput v-model="reason" :maxlength="300" :placeholder="t('sales.force.reasonPlaceholder')" @update:model-value="reasonError = null" />
      </FormField>
      <FormField :label="t('sales.force.counted')" :hint="t('sales.force.countedHint')" optional>
        <MoneyInput v-model="counted" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="danger" :icon="LockKeyhole" :loading="close.isPending.value" @click="submit">{{ t("sales.force.submit") }}</UiButton>
    </template>
  </UiDialog>
</template>
