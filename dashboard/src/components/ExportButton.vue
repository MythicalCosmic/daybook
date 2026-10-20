<script setup lang="ts">
/**
 * "Export" with its choices (plan §6.3): Excel or CSV built by the server from the current filters
 * (`kind` + `params`, needs `data.export`), "Also send to Telegram" (unchecked by default), a warning
 * when the exporter is sensitive (salaries, IDs), and "This page as CSV" when `pageCsv` is given.
 *
 *   <ExportButton kind="finance.transactions" :params="filters" :page-csv="() => ({ filename, columns, rows })" />
 */
import { ChevronDown, Download, FileSpreadsheet, FileText, Rows3 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { downloadFile, safeFilename, toCsv, type CsvColumn } from "@/lib/csv";
import { useExport, type ExportFormat } from "@/lib/useExport";
import { useCompanyStore } from "@/stores/company";

import CheckBox from "./CheckBox.vue";
import InlineAlert from "./InlineAlert.vue";
import UiButton from "./UiButton.vue";
import UiPopover from "./UiPopover.vue";

export interface PageCsv<Row = unknown> {
  filename: string;
  columns: CsvColumn<Row>[];
  rows: readonly Row[];
}

const props = withDefaults(
  defineProps<{
    kind?: string;
    params?: Record<string, unknown>;
    sensitive?: boolean;
    pageCsv?: () => PageCsv<never>;
    label?: string;
    size?: "sm" | "md";
    variant?: "secondary" | "ghost";
  }>(),
  { kind: undefined, params: () => ({}), sensitive: false, pageCsv: undefined, label: undefined, size: "md", variant: "secondary" },
);

const { t } = useI18n();
const company = useCompanyStore();
const exporter = useExport();
const open = ref(false);
const telegram = ref(false);

const canServer = computed(() => !!props.kind && company.can("data.export"));

async function server(format: ExportFormat): Promise<void> {
  if (!props.kind) return;
  open.value = false;
  await exporter.start({ kind: props.kind, format, params: props.params, deliverTelegram: telegram.value });
}

function page(): void {
  if (!props.pageCsv) return;
  const data = props.pageCsv();
  downloadFile(safeFilename(data.filename, "csv"), toCsv(data.columns as CsvColumn<unknown>[], data.rows as readonly unknown[]));
  open.value = false;
}
</script>

<template>
  <UiPopover v-if="canServer || pageCsv" v-model:open="open" width="288px" align="end" :padded="false">
    <template #trigger>
      <UiButton :size="size" :variant="variant" :icon="Download" :icon-right="ChevronDown" :loading="exporter.running.value">{{ label ?? t("common.export.title") }}</UiButton>
    </template>
    <div class="flex flex-col p-1.5">
      <template v-if="canServer">
        <button type="button" class="ui-option hover:bg-highlight" @click="server('xlsx')">
          <FileSpreadsheet :size="16" class="text-success" />
          <span class="min-w-0 flex-1">
            <span class="block font-medium">{{ t("common.export.excel") }}</span>
            <span class="block text-xs text-muted">{{ t("common.export.allRows") }}</span>
          </span>
        </button>
        <button type="button" class="ui-option hover:bg-highlight" @click="server('csv')">
          <FileText :size="16" class="text-muted" />
          <span class="min-w-0 flex-1">
            <span class="block font-medium">{{ t("common.export.csv") }}</span>
            <span class="block text-xs text-muted">{{ t("common.export.allRows") }}</span>
          </span>
        </button>
      </template>
      <button v-if="pageCsv" type="button" class="ui-option hover:bg-highlight" @click="page">
        <Rows3 :size="16" class="text-muted" />
        <span class="min-w-0 flex-1">
          <span class="block font-medium">{{ t("common.export.page") }}</span>
          <span class="block text-xs text-muted">{{ t("common.export.pageHint") }}</span>
        </span>
      </button>
      <div v-if="canServer" class="mx-1 mt-1 flex flex-col gap-2 border-t border-line px-1.5 pb-1 pt-2.5">
        <CheckBox v-model="telegram" size="sm" :label="t('common.export.telegramOpt')" />
        <InlineAlert v-if="sensitive" tone="warning" size="sm" :description="t('common.export.sensitive')" />
      </div>
    </div>
  </UiPopover>
</template>
