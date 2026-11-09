<script setup lang="ts">
/**
 * "Left the company" on a day: from then on the terminals' scans of this person no longer count,
 * their history stays. "Returned" (on their page) brings them back.
 */
import { UserMinus } from "@lucide/vue";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyToday } from "@/stores/company";

import type { Employee } from "../../types";
import { useLeave } from "./teamApi";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ employee: Employee }>();

const { t } = useI18n();
const today = useCompanyToday();
const leave = useLeave();
const day = ref<string | null>(today.value);

watch(open, (value) => {
  if (value) day.value = today.value;
});

async function confirm(): Promise<void> {
  if (!day.value) return;
  await leave.mutateAsync({ id: props.employee.id, date: day.value });
  toast.success(t("davomat.team.leave.done", { name: props.employee.full_name }));
  open.value = false;
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('davomat.team.leave.title', { name: employee.full_name })" :description="t('davomat.team.leave.description')" size="sm">
    <FormField :label="t('davomat.team.leave.date')">
      <DatePicker v-model="day" />
    </FormField>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="danger" :icon="UserMinus" :disabled="!day" :loading="leave.isPending.value" data-confirm-leave @click="confirm">{{ t("davomat.team.leave.confirm") }}</UiButton>
    </template>
  </UiDialog>
</template>
