<script setup lang="ts">
/**
 * Verify a closed shift. A manager may recount the till: the recount then decides the difference
 * and the ledger follows (shortage or surplus rebooked). Empty recount means "the cashier's count
 * stands". The shift's numbers are in view so nothing is verified blind.
 */
import { ShieldCheck } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { subtract } from "@/lib/decimal";

import { salesApi, useShiftWrite } from "../api";
import type { ShiftDetail } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ shift: ShiftDetail }>();

const { t } = useI18n();
const recount = ref<string | null>(null);
const note = ref("");
watch(open, (value) => {
  if (value) {
    recount.value = null;
    note.value = "";
  }
});

const verify = useShiftWrite((cid, vars: { id: number; recount_cash: string | null; note: string }) =>
  salesApi.verify(cid, vars.id, { recount_cash: vars.recount_cash, note: vars.note }),
);
const preview = computed(() => (recount.value && props.shift.expected_cash ? subtract(recount.value, props.shift.expected_cash) : props.shift.difference));

async function submit(): Promise<void> {
  await verify.mutateAsync({ id: props.shift.id, recount_cash: recount.value || null, note: note.value });
  toast.success(t("sales.verify.done", { code: props.shift.code }));
  open.value = false;
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('sales.verify.title', { code: shift.code })" :description="t('sales.verify.body')" size="sm">
    <div class="flex flex-col gap-4">
      <dl class="grid grid-cols-3 gap-2 rounded-[12px] bg-surface-2/70 p-3 text-center">
        <div>
          <dt class="text-[11px] text-muted">{{ t("sales.shift.expected") }}</dt>
          <dd class="mt-0.5 text-sm font-semibold text-fg"><MoneyText :value="shift.expected_cash" compact /></dd>
        </div>
        <div>
          <dt class="text-[11px] text-muted">{{ t("sales.shift.counted") }}</dt>
          <dd class="mt-0.5 text-sm font-semibold text-fg"><MoneyText :value="shift.cashier_counted" compact /></dd>
        </div>
        <div>
          <dt class="text-[11px] text-muted">{{ t("sales.shift.difference") }}</dt>
          <dd class="mt-0.5 text-sm font-semibold"><MoneyText :value="preview" sign="always" colored compact /></dd>
        </div>
      </dl>
      <FormField :label="t('sales.verify.recount')" :hint="t('sales.verify.recountHint')" optional>
        <MoneyInput v-model="recount" :placeholder="t('sales.verify.recountPlaceholder')" />
      </FormField>
      <FormField :label="t('sales.verify.note')" optional>
        <TextArea v-model="note" :rows="2" :maxlength="2000" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="ShieldCheck" :loading="verify.isPending.value" @click="submit">{{ t("sales.verify.submit") }}</UiButton>
    </template>
  </UiDialog>
</template>
