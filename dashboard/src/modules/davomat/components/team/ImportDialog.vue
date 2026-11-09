<script setup lang="ts">
/**
 * Import employees from a spreadsheet (`?import=1`): drop a CSV or Excel file and see at once what
 * it would do (the server's dry run: how it read each column, and each row to create, update or
 * skip, with the reason a row can't be used), then import. Nothing is written before "Import".
 * The template has the columns the server reads, with an example row.
 */
import { ArrowRight, CircleAlert, CircleCheck, Download, FileSpreadsheet, RefreshCw, Upload } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import FileDrop from "@/components/FileDrop.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useFormat } from "@/lib/useFormat";

import { saveBlob, useRefresh } from "../../api";
import type { ImportResult, ImportRow } from "../../types";
import { IMPORT_COLUMNS, importTemplate, isImportColumn } from "./team";
import { useImport } from "./teamApi";

const open = defineModel<boolean>("open", { default: false });

const { t } = useI18n();
const fmt = useFormat();
const refresh = useRefresh();
const run = useImport();

const files = ref<File[]>([]);
const preview = ref<ImportResult | null>(null);
const done = ref<ImportResult | null>(null);
const failure = ref<string | null>(null);
const show = ref<"all" | "errors">("all");

const file = computed(() => files.value[0] ?? null);
const importable = computed(() => (preview.value ? preview.value.created + preview.value.updated : 0));
const withErrors = computed(() => (preview.value?.rows ?? []).filter((row) => row.errors.length > 0).length);
const rows = computed<ImportRow[]>(() => (preview.value?.rows ?? []).filter((row) => show.value === "all" || row.errors.length > 0));
/** How the server read the header row: each column and the field it became (or that it was left out). */
const read = computed(() =>
  (preview.value?.columns ?? []).map((header) => {
    const field = preview.value?.mapping[header];
    return { header, field: field && isImportColumn(field) ? t(`davomat.team.import.column.${field}`) : (field ?? null) };
  }),
);
const tones = { create: "success", update: "info", skip: "neutral" } as const;

function reset(): void {
  files.value = [];
  preview.value = null;
  done.value = null;
  failure.value = null;
  show.value = "all";
}

watch(open, (value) => {
  if (!value) reset();
});

function messageOf(error: unknown): string {
  if (isApiError(error)) {
    if (error.detail) return error.detail;
    const first = Object.values(error.fieldErrors)[0]?.[0];
    if (first) return first;
    if (error.isNetwork) return t("common.error.network");
  }
  return t("davomat.team.import.failed");
}

async function check(next: File | null): Promise<void> {
  preview.value = null;
  failure.value = null;
  if (!next) return;
  try {
    const result = await run.mutateAsync({ file: next, dryRun: true });
    if (file.value === next) preview.value = result;
  } catch (error) {
    if (file.value === next) failure.value = messageOf(error);
  }
}

watch(file, (next) => void check(next));

async function confirmImport(): Promise<void> {
  const chosen = file.value;
  if (!chosen) return;
  failure.value = null;
  try {
    done.value = await run.mutateAsync({ file: chosen, dryRun: false });
    refresh();
  } catch (error) {
    failure.value = messageOf(error);
  }
}

function template(): void {
  const example = [
    t("davomat.team.import.example.first"),
    t("davomat.team.import.example.last"),
    "+998901234567",
    t("davomat.team.import.example.position"),
    t("davomat.team.import.example.department"),
    t("davomat.team.import.example.branch"),
    "00000002",
    "2025-03-01",
  ];
  saveBlob(new Blob([importTemplate(example)], { type: "text/csv;charset=utf-8" }), "employees-template.csv");
}

const columnLabels = computed(() => IMPORT_COLUMNS.map((column) => t(`davomat.team.import.column.${column}`)));
</script>

<template>
  <UiDialog v-model:open="open" :title="t('davomat.team.import.title')" :description="t('davomat.team.import.description')" size="xl">
    <!-- Imported -->
    <div v-if="done" class="flex flex-col items-center py-8 text-center" data-import-done>
      <span class="grid size-14 place-items-center rounded-full bg-success-soft text-success"><CircleCheck :size="28" /></span>
      <p class="mt-4 text-md font-semibold text-fg">{{ t("davomat.team.import.doneTitle") }}</p>
      <p class="mt-1 max-w-[420px] text-sm text-muted">{{ t("davomat.team.import.doneBody", { created: fmt.number(done.created), updated: fmt.number(done.updated) }) }}</p>
      <p v-if="done.skipped" class="mt-1 text-sm text-muted">{{ t("davomat.team.import.doneSkipped", { n: fmt.number(done.skipped) }, done.skipped) }}</p>
    </div>

    <div v-else class="flex flex-col gap-4">
      <div class="grid gap-4 md:grid-cols-[minmax(0,1fr)_270px]">
        <FileDrop
          v-model="files"
          accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          :max-size="5 * 1024 * 1024"
          :title="t('davomat.team.import.drop')"
          :hint="t('davomat.team.import.dropHint')"
        />
        <aside class="flex flex-col gap-2 rounded-[12px] border border-line bg-surface-2/60 p-3.5">
          <p class="flex items-center gap-2 text-sm font-semibold text-fg"><FileSpreadsheet :size="16" class="text-primary" aria-hidden="true" />{{ t("davomat.team.import.columns") }}</p>
          <ul class="flex flex-wrap gap-1.5">
            <li v-for="label in columnLabels" :key="label" class="ui-chip">{{ label }}</li>
          </ul>
          <p class="text-xs text-muted">{{ t("davomat.team.import.columnsHint") }}</p>
          <UiButton class="mt-1 self-start" size="sm" variant="secondary" :icon="Download" @click="template">{{ t("davomat.team.import.template") }}</UiButton>
        </aside>
      </div>

      <InlineAlert v-if="failure" tone="danger" :description="failure">
        <template v-if="file" #actions>
          <UiButton size="sm" variant="secondary" :icon="RefreshCw" @click="check(file)">{{ t("common.retry") }}</UiButton>
        </template>
      </InlineAlert>

      <!-- Checking the file -->
      <div v-if="file && !preview && !failure" class="flex flex-col gap-2" aria-hidden="true" data-import-checking>
        <SkeletonBlock height="40px" radius="10px" />
        <SkeletonBlock v-for="n in 4" :key="n" height="34px" radius="8px" />
      </div>

      <!-- The dry run -->
      <template v-if="preview">
        <section v-if="read.length" class="flex flex-col gap-1.5" data-import-mapping>
          <p class="text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("davomat.team.import.readAs") }}</p>
          <ul class="flex flex-wrap gap-1.5">
            <li v-for="column in read" :key="column.header" :class="['ui-chip gap-1', !column.field && 'opacity-60']">
              <span class="font-mono">{{ column.header }}</span>
              <ArrowRight :size="11" class="text-subtle" aria-hidden="true" />
              <span :class="column.field ? 'text-fg' : 'text-subtle'">{{ column.field ?? t("davomat.team.import.notUsed") }}</span>
            </li>
          </ul>
        </section>

        <div class="flex flex-wrap items-center gap-2" data-import-summary>
          <StatusPill tone="success" :label="t('davomat.team.import.toCreate', { n: fmt.number(preview.created) }, preview.created)" />
          <StatusPill tone="info" :label="t('davomat.team.import.toUpdate', { n: fmt.number(preview.updated) }, preview.updated)" />
          <StatusPill v-if="preview.skipped" tone="neutral" :label="t('davomat.team.import.toSkip', { n: fmt.number(preview.skipped) }, preview.skipped)" />
          <StatusPill v-if="withErrors" tone="danger" :label="t('davomat.team.import.withErrors', { n: fmt.number(withErrors) }, withErrors)" />
          <span class="flex-1" />
          <SegmentedControl
            v-if="withErrors"
            v-model="show"
            size="sm"
            :options="[
              { value: 'all', label: t('davomat.team.import.showAll') },
              { value: 'errors', label: t('davomat.team.import.showErrors') },
            ]"
            :aria-label="t('davomat.team.import.show')"
          />
        </div>

        <div class="max-h-[44vh] overflow-auto rounded-[12px] border border-line" data-import-rows>
          <table class="w-full border-collapse text-sm">
            <thead class="sticky top-0 z-[1] bg-surface-2 text-left text-xs font-medium text-muted">
              <tr>
                <th class="w-16 px-3 py-2 font-medium">{{ t("davomat.team.import.row") }}</th>
                <th class="px-3 py-2 font-medium">{{ t("davomat.team.import.name") }}</th>
                <th class="w-36 px-3 py-2 font-medium">{{ t("davomat.team.import.result") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.row" :class="['border-t border-line align-top', row.errors.length && 'bg-danger-soft/40']" :data-import-row="row.row">
                <td class="px-3 py-2 tabular-nums text-subtle">{{ row.row }}</td>
                <td class="px-3 py-2">
                  <span class="block font-medium text-fg">{{ row.name || "—" }}</span>
                  <ul v-if="row.errors.length" class="mt-1 flex flex-col gap-0.5">
                    <li v-for="(error, index) in row.errors" :key="index" class="flex items-start gap-1 text-xs text-danger">
                      <CircleAlert :size="12" class="mt-0.5 shrink-0" aria-hidden="true" />{{ error }}
                    </li>
                  </ul>
                </td>
                <td class="px-3 py-2">
                  <StatusPill v-if="row.errors.length" size="sm" tone="danger" :label="t('davomat.team.import.action.error')" />
                  <StatusPill v-else size="sm" :tone="tones[row.action]" :label="t(`davomat.team.import.action.${row.action}`)" />
                </td>
              </tr>
              <tr v-if="!rows.length">
                <td colspan="3" class="px-3 py-8 text-center text-sm text-muted">{{ t("davomat.team.import.noRows") }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>

    <template #footer>
      <template v-if="done">
        <UiButton variant="primary" @click="open = false">{{ t("common.done") }}</UiButton>
      </template>
      <template v-else>
        <span v-if="withErrors" class="mr-auto hidden text-sm text-muted sm:block">{{ t("davomat.team.import.errorsHint") }}</span>
        <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :icon="Upload" :disabled="!preview || importable === 0" :loading="run.isPending.value && !!preview" data-import-confirm @click="confirmImport">
          {{ t("davomat.team.import.confirm", { n: fmt.number(importable) }, importable) }}
        </UiButton>
      </template>
    </template>
  </UiDialog>
</template>
