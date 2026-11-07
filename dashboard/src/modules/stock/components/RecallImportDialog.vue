<script setup lang="ts">
/**
 * The regulator's list of rejected series (XLSX or CSV) into recalls: the list's title and date,
 * the file, then a dry run that says row by row what each series finds in stock, which medicines
 * the company doesn't carry, and which are already recalled; "Register" makes the recalls (each
 * found series leaves sale everywhere and its pharmacies get a task).
 */
import { FileSpreadsheet } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FileDrop from "@/components/FileDrop.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { stockApi, useRefresh } from "../api";
import type { RecallImportAction, RecallImportResult } from "../types";

const open = defineModel<boolean>("open", { default: false });

const { t } = useI18n();
const company = useCompanyStore();
const today = useCompanyToday();
const refresh = useRefresh();

const form = reactive({ source: "", receivedOn: "" });
const files = ref<File[]>([]);
const preview = ref<RecallImportResult | null>(null);
const busy = ref(false);
const problem = ref<string | null>(null);

watch(open, (value) => {
  if (!value) return;
  form.source = "";
  form.receivedOn = today.value;
  files.value = [];
  preview.value = null;
  problem.value = null;
});

const ready = computed(() => files.value.length > 0 && form.source.trim() !== "" && form.receivedOn !== "");
const shownRows = computed(() => (preview.value?.rows ?? []).filter((row) => row.action !== "skip").slice(0, 200));
const TONES: Record<RecallImportAction, "danger" | "neutral" | "info"> = { register: "danger", known: "info", not_carried: "neutral", skip: "neutral" };

async function send(dryRun: boolean): Promise<RecallImportResult | null> {
  const file = files.value[0];
  if (!file) return null;
  busy.value = true;
  problem.value = null;
  try {
    return await stockApi.importRecalls(company.currentId ?? 0, file, {
      dryRun,
      source: form.source.trim(),
      receivedOn: form.receivedOn,
      mapping: dryRun ? null : preview.value?.mapping,
    });
  } catch (error) {
    problem.value = isApiError(error) ? error.message : t("stock.import.failed");
    return null;
  } finally {
    busy.value = false;
  }
}

async function check(): Promise<void> {
  preview.value = await send(true);
}

async function run(): Promise<void> {
  const result = await send(false);
  if (!result) return;
  toast.success(t("stock.recallImport.doneToast", { n: result.registered }));
  refresh();
  open.value = false;
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('stock.recallImport.title')" :description="t('stock.recallImport.description')" size="xl">
    <div class="flex flex-col gap-4">
      <InlineAlert v-if="problem" tone="danger" size="sm">{{ problem }}</InlineAlert>
      <template v-if="!preview">
        <div class="grid gap-3 sm:grid-cols-[1fr_200px]">
          <FormField :label="t('stock.recallImport.source')" required>
            <TextInput v-model="form.source" :maxlength="200" :placeholder="t('stock.recallImport.sourceHint')" data-testid="recall-import-source" />
          </FormField>
          <FormField :label="t('stock.recallImport.receivedOn')" required>
            <DatePicker v-model="form.receivedOn" />
          </FormField>
        </div>
        <FileDrop v-model="files" accept=".xlsx,.csv" :max-files="1" :title="t('stock.import.dropTitle')" :hint="t('stock.import.dropHint')" data-testid="recall-import-file" />
        <InlineAlert tone="neutral" size="sm" :icon="FileSpreadsheet">{{ t("stock.recallImport.columnsHint") }}</InlineAlert>
      </template>
      <template v-else>
        <p class="text-sm text-muted" data-testid="recall-import-counts">
          {{ t("stock.recallImport.counts", { registered: preview.registered, found: preview.found, notCarried: preview.not_carried }) }}
        </p>
        <div class="max-h-[340px] overflow-auto rounded-[12px] border border-line">
          <table class="w-full text-sm" data-testid="recall-import-rows">
            <thead class="sticky top-0 bg-surface-1 text-xs text-muted">
              <tr>
                <th class="px-3 py-2 text-start font-medium">{{ t("stock.import.row") }}</th>
                <th class="px-3 py-2 text-start font-medium">{{ t("stock.field.name") }}</th>
                <th class="px-3 py-2 text-start font-medium">{{ t("stock.recallImport.series") }}</th>
                <th class="px-3 py-2 text-end font-medium">{{ t("stock.recallImport.found") }}</th>
                <th class="px-3 py-2 text-start font-medium">{{ t("stock.import.action") }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              <tr v-for="row in shownRows" :key="row.row">
                <td class="px-3 py-1.5 tabular-nums text-muted">{{ row.row }}</td>
                <td class="px-3 py-1.5 text-fg">{{ row.name || "—" }}</td>
                <td class="px-3 py-1.5 font-mono text-xs">{{ row.series }}</td>
                <td class="px-3 py-1.5 text-end tabular-nums">{{ row.found }}</td>
                <td class="px-3 py-1.5"><StatusPill :tone="TONES[row.action]" size="sm" :label="t(`stock.recallImport.act.${row.action}`)" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton v-if="!preview" variant="primary" :loading="busy" :disabled="!ready" data-testid="recall-import-check" @click="check">{{ t("stock.import.check") }}</UiButton>
      <UiButton v-else variant="danger" :loading="busy" :disabled="!preview.registered" data-testid="recall-import-run" @click="run">{{ t("stock.recallImport.run", { n: preview.registered }) }}</UiButton>
    </template>
  </UiDialog>
</template>
