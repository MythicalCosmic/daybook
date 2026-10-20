<script setup lang="ts">
/**
 * "New export": anything the person may export here (`exports/kinds/`), as Excel or CSV, optionally
 * also sent to them in Telegram (off by default; sensitive exporters get a warning, plan §3.5).
 * Tables export their filtered rows with their own Export button; this exports a whole list.
 */
import { Download, FileSpreadsheet } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import CheckBox from "@/components/CheckBox.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import type { SelectOption } from "@/components/options";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";

import { useCreateExport, useExporters } from "../api";

const open = defineModel<boolean>("open", { default: false });

const { t } = useI18n();
const exporters = useExporters(open);
const create = useCreateExport();

const kind = ref<string | null>(null);
const format = ref<"xlsx" | "csv">("xlsx");
const telegram = ref(false);

const list = computed(() => exporters.data.value ?? []);
const options = computed<SelectOption<string>[]>(() =>
  list.value.map((exporter) => ({ value: exporter.kind, label: exporter.label, description: exporter.sensitive ? t("exports.sensitive") : undefined })),
);
const chosen = computed(() => list.value.find((exporter) => exporter.kind === kind.value) ?? null);
const formats = computed(() =>
  (chosen.value?.formats ?? ["xlsx", "csv"]).filter((f): f is "xlsx" | "csv" => f === "xlsx" || f === "csv").map((value) => ({ value, label: t(`exports.format.${value}`) })),
);

// Each opening starts clean: the first exporter, Excel, not to Telegram.
watch(open, (isOpen) => {
  if (!isOpen) return;
  kind.value = list.value[0]?.kind ?? null;
  format.value = "xlsx";
  telegram.value = false;
});
watch(list, (items) => {
  if (open.value && !kind.value) kind.value = items[0]?.kind ?? null;
});
watch(formats, (items) => {
  if (items.length && !items.some((item) => item.value === format.value)) format.value = items[0]!.value;
});

async function submit(): Promise<void> {
  if (!chosen.value) return;
  try {
    await create.mutateAsync({ kind: chosen.value.kind, format: format.value, deliverTelegram: telegram.value });
    toast.success(t("exports.started", { name: chosen.value.label }), { description: t("exports.startedHint") });
    open.value = false;
  } catch {
    // The HTTP layer showed the server's reason (a missing permission, too many exports).
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('exports.dialog.title')" :description="t('exports.dialog.description')">
    <div v-if="exporters.isPending.value" class="flex flex-col gap-3">
      <SkeletonBlock height="36px" radius="6px" />
      <SkeletonBlock width="50%" height="32px" radius="8px" />
    </div>
    <ErrorState v-else-if="exporters.isError.value" compact :error="exporters.error.value" :retry="() => exporters.refetch()" />
    <EmptyState v-else-if="!list.length" size="sm" tone="neutral" :icon="FileSpreadsheet" :title="t('exports.dialog.none')" :description="t('exports.dialog.noneBody')" />
    <form v-else id="new-export" class="flex flex-col gap-4" @submit.prevent="submit">
      <FormField :label="t('exports.dialog.kind')" for="export-kind">
        <SelectBox id="export-kind" v-model="kind" :options="options" />
      </FormField>
      <FormField :label="t('exports.dialog.format')">
        <SegmentedControl v-model="format" :options="formats" :aria-label="t('exports.dialog.format')" />
      </FormField>
      <CheckBox v-model="telegram" :label="t('exports.dialog.telegram')" :description="t('exports.dialog.telegramHint')" />
      <InlineAlert v-if="chosen?.sensitive" tone="warning" size="sm" :description="t('exports.dialog.sensitive')" />
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="new-export" :icon="Download" :disabled="!chosen" :loading="create.isPending.value">{{ t("exports.dialog.submit") }}</UiButton>
    </template>
  </UiDialog>
</template>
