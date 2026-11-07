<script setup lang="ts">
/**
 * Import the catalogue from a spreadsheet (XLSX or CSV): upload, then a dry run that says row by
 * row what would be created, updated or skipped (and why) with the columns it recognised, then the
 * import itself. Rows match the catalogue by barcode, then SKU. Nothing changes until "Import".
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
import WizardSteps from "@/components/WizardSteps.vue";
import { useCompanyStore } from "@/stores/company";

import { stockApi, useRefresh } from "../api";
import type { ImportResult } from "../types";

const open = defineModel<boolean>("open", { default: false });
const emit = defineEmits<{ done: [result: ImportResult] }>();

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();

const step = ref("upload");
const files = ref<File[]>([]);
const preview = ref<ImportResult | null>(null);
const result = ref<ImportResult | null>(null);
const busy = ref(false);
const problem = ref<string | null>(null);

watch(open, (value) => {
  if (!value) return;
  step.value = "upload";
  files.value = [];
  preview.value = null;
  result.value = null;
  problem.value = null;
});

const steps = computed(() => [
  { id: "upload", label: t("stock.import.stepUpload") },
  { id: "check", label: t("stock.import.stepCheck") },
  { id: "done", label: t("stock.import.stepDone") },
]);
const completed = computed(() => (step.value === "check" ? ["upload"] : step.value === "done" ? ["upload", "check"] : []));
const mapped = computed(() => Object.entries(preview.value?.mapping ?? {}));
const shownRows = computed(() => (preview.value?.rows ?? []).slice(0, 200));

function tone(action: string) {
  return action === "create" ? "success" : action === "update" ? "info" : "warning";
}

async function check(): Promise<void> {
  const file = files.value[0];
  if (!file) return;
  busy.value = true;
  problem.value = null;
  try {
    preview.value = await stockApi.importProducts(company.currentId ?? 0, file, { dryRun: true });
    step.value = "check";
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
    result.value = await stockApi.importProducts(company.currentId ?? 0, file, { dryRun: false, mapping: preview.value.mapping });
    step.value = "done";
    toast.success(t("stock.import.doneToast", { created: result.value.created, updated: result.value.updated }));
    refresh();
    emit("done", result.value);
  } catch (error) {
    problem.value = isApiError(error) ? error.message : t("stock.import.failed");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('stock.import.title')" :description="t('stock.import.description')" size="xl">
    <div class="flex flex-col gap-4">
      <WizardSteps v-model="step" :steps="steps" :completed="completed" />
      <InlineAlert v-if="problem" tone="danger" size="sm">{{ problem }}</InlineAlert>

      <template v-if="step === 'upload'">
        <FileDrop v-model="files" accept=".xlsx,.csv" :max-files="1" :title="t('stock.import.dropTitle')" :hint="t('stock.import.dropHint')" data-testid="import-file" />
        <InlineAlert tone="neutral" size="sm" :icon="FileSpreadsheet">{{ t("stock.import.columnsHint") }}</InlineAlert>
      </template>

      <template v-else-if="step === 'check' && preview">
        <div class="grid grid-cols-3 gap-3" data-testid="import-counts">
          <div class="rounded-[12px] bg-success-soft/60 p-3">
            <div class="text-xs text-muted">{{ t("stock.import.willCreate") }}</div>
            <div class="text-lg font-semibold tabular-nums text-fg">{{ preview.created }}</div>
          </div>
          <div class="rounded-[12px] bg-info-soft/60 p-3">
            <div class="text-xs text-muted">{{ t("stock.import.willUpdate") }}</div>
            <div class="text-lg font-semibold tabular-nums text-fg">{{ preview.updated }}</div>
          </div>
          <div class="rounded-[12px] bg-warning-soft/60 p-3">
            <div class="text-xs text-muted">{{ t("stock.import.willSkip") }}</div>
            <div class="text-lg font-semibold tabular-nums text-fg">{{ preview.skipped }}</div>
          </div>
        </div>
        <div>
          <h3 class="mb-1.5 text-sm font-semibold text-fg">{{ t("stock.import.columnsFound") }}</h3>
          <p class="flex flex-wrap gap-1.5 text-xs text-muted">
            <span v-for="[column, field] in mapped" :key="column" class="rounded-full bg-surface-2 px-2 py-0.5">{{ column }} → {{ t(`stock.importField.${field}`) }}</span>
          </p>
        </div>
        <div class="max-h-[340px] overflow-auto rounded-[12px] border border-line">
          <table class="w-full text-sm" data-testid="import-rows">
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
                <td class="px-3 py-1.5"><StatusPill :tone="tone(row.action)" size="sm" :label="t(`stock.import.act.${row.action}`)" /></td>
                <td class="px-3 py-1.5 text-xs text-danger">{{ row.errors.join("; ") }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="(preview.rows.length ?? 0) > shownRows.length" class="text-xs text-muted">{{ t("stock.import.moreRows", { n: preview.rows.length - shownRows.length }) }}</p>
      </template>

      <template v-else-if="step === 'done' && result">
        <InlineAlert tone="success" :title="t('stock.import.doneTitle')">
          {{ t("stock.import.doneBody", { created: result.created, updated: result.updated, skipped: result.skipped }) }}
        </InlineAlert>
      </template>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ step === "done" ? t("common.close") : t("common.cancel") }}</UiButton>
      <UiButton v-if="step === 'upload'" variant="primary" :disabled="!files.length" :loading="busy" data-testid="import-check" @click="check">{{ t("stock.import.check") }}</UiButton>
      <template v-else-if="step === 'check'">
        <UiButton variant="secondary" @click="step = 'upload'">{{ t("stock.import.back") }}</UiButton>
        <UiButton variant="primary" :disabled="!preview || preview.created + preview.updated === 0" :loading="busy" data-testid="import-run" @click="run">{{ t("stock.import.run") }}</UiButton>
      </template>
    </template>
  </UiDialog>
</template>
