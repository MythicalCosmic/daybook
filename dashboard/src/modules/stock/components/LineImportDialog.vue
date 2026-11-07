<script setup lang="ts">
/**
 * A distributor's invoice spreadsheet (XLSX or CSV) into a draft receipt's lines: upload, a dry
 * run that says row by row what will be added, what isn't in the catalogue (to add by hand) and
 * what is skipped, then "Add". Items are found by the distributor's own code, the barcode, then
 * the exact name; the column map is remembered for the distributor.
 */
import { FileSpreadsheet } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import FileDrop from "@/components/FileDrop.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { stockApi, useRefresh } from "../api";
import type { LineImportAction, LineImportResult } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ receiptId: number }>();
const emit = defineEmits<{ done: [result: LineImportResult] }>();

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();

const files = ref<File[]>([]);
const preview = ref<LineImportResult | null>(null);
const busy = ref(false);
const problem = ref<string | null>(null);

watch(open, (value) => {
  if (!value) return;
  files.value = [];
  preview.value = null;
  problem.value = null;
});

const shownRows = computed(() => (preview.value?.rows ?? []).slice(0, 200));
const TONES: Record<LineImportAction, "success" | "warning" | "neutral"> = { add: "success", unmatched: "warning", skip: "neutral" };

async function check(): Promise<void> {
  const file = files.value[0];
  if (!file) return;
  busy.value = true;
  problem.value = null;
  try {
    preview.value = await stockApi.importLines(company.currentId ?? 0, props.receiptId, file, { dryRun: true });
  } catch (error) {
    problem.value = isApiError(error) ? error.message : t("stock.import.failed");
  } finally {
    busy.value = false;
  }
}

async function run(): Promise<void> {
  const file = files.value[0];
  if (!file || !preview.value) return;
  busy.value = true;
  try {
    const result = await stockApi.importLines(company.currentId ?? 0, props.receiptId, file, { dryRun: false, mapping: preview.value.mapping });
    toast.success(t("stock.lineImport.doneToast", { n: result.added }));
    refresh();
    emit("done", result);
    open.value = false;
  } catch (error) {
    problem.value = isApiError(error) ? error.message : t("stock.import.failed");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('stock.lineImport.title')" :description="t('stock.lineImport.description')" size="xl">
    <div class="flex flex-col gap-4">
      <InlineAlert v-if="problem" tone="danger" size="sm">{{ problem }}</InlineAlert>
      <template v-if="!preview">
        <FileDrop v-model="files" accept=".xlsx,.csv" :max-files="1" :title="t('stock.import.dropTitle')" :hint="t('stock.import.dropHint')" data-testid="line-import-file" />
        <InlineAlert tone="neutral" size="sm" :icon="FileSpreadsheet">{{ t("stock.lineImport.columnsHint") }}</InlineAlert>
      </template>
      <template v-else>
        <p class="text-sm text-muted" data-testid="line-import-counts">
          {{ t("stock.lineImport.counts", { added: preview.added, unmatched: preview.unmatched, skipped: preview.skipped }) }}
        </p>
        <div class="max-h-[340px] overflow-auto rounded-[12px] border border-line">
          <table class="w-full text-sm" data-testid="line-import-rows">
            <thead class="sticky top-0 bg-surface-1 text-xs text-muted">
              <tr>
                <th class="px-3 py-2 text-start font-medium">{{ t("stock.import.row") }}</th>
                <th class="px-3 py-2 text-start font-medium">{{ t("stock.field.name") }}</th>
                <th class="px-3 py-2 text-start font-medium">{{ t("stock.import.action") }}</th>
                <th class="px-3 py-2 text-start font-medium">{{ t("stock.import.problems") }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              <tr v-for="row in shownRows" :key="row.row">
                <td class="px-3 py-1.5 tabular-nums text-muted">{{ row.row }}</td>
                <td class="px-3 py-1.5 text-fg">{{ row.name || "—" }}</td>
                <td class="px-3 py-1.5"><StatusPill :tone="TONES[row.action]" size="sm" :label="t(`stock.lineImport.act.${row.action}`)" /></td>
                <td class="px-3 py-1.5 text-xs text-danger">{{ row.errors.join("; ") }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton v-if="!preview" variant="primary" :loading="busy" :disabled="!files.length" data-testid="line-import-check" @click="check">{{ t("stock.import.check") }}</UiButton>
      <UiButton v-else variant="primary" :loading="busy" :disabled="!preview.added" data-testid="line-import-run" @click="run">{{ t("stock.lineImport.run", { n: preview.added }) }}</UiButton>
    </template>
  </UiDialog>
</template>
