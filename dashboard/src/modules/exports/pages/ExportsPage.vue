<script setup lang="ts">
/**
 * My exports (plan §6.1 "exports", W0 list; N adds scheduled reports): every file the person asked
 * for in this company over the last 7 days, building ones refreshing on their own. "Download" asks
 * for a fresh signed link first (links last 10 minutes); a failed or expired export can be made
 * again in one click.
 */
import { Download, FileSpreadsheet, FileText, Plus, RotateCw, Send, ShieldAlert } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import type { ExportJob } from "@/api/types";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import StatusPill, { type StatusTone } from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { downloadExport } from "@/lib/useExport";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { useCompanyStore } from "@/stores/company";

import { getExport, isBuilding, useCreateExport, useExports } from "../api";
import NewExportDialog from "../components/NewExportDialog.vue";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const now = useNow();

const table = useDataTable({ id: "exports.list", pageSize: 25, pageSizes: [25, 50, 100], url: true });
const query = useExports(computed(() => ({ page: table.page.value, page_size: table.pageSize.value })));
const rows = computed(() => query.data.value?.results ?? []);
const creating = ref(false);
const again = useCreateExport();
const downloading = ref<number | null>(null);

const TONES: Record<ExportJob["status"], StatusTone> = { pending: "info", running: "info", ready: "success", failed: "danger" };

const expired = (job: ExportJob) => new Date(job.expires_at).getTime() <= now.value;

function paramsText(job: ExportJob): string {
  return Object.entries(job.params ?? {})
    .filter(([, value]) => value !== null && value !== "" && !(Array.isArray(value) && !value.length))
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
    .join(" · ");
}

async function download(job: ExportJob): Promise<void> {
  downloading.value = job.id;
  try {
    // The list's link may be older than its 10 minutes: ask for a fresh one.
    const fresh = await getExport(company.currentId ?? 0, job.id);
    if (fresh.file_url) downloadExport(fresh);
    else toast.error(t("exports.gone"));
  } catch {
    // Shown by the HTTP layer only for writes; say it here.
    toast.error(t("exports.gone"));
  } finally {
    downloading.value = null;
  }
}

async function exportAgain(job: ExportJob): Promise<void> {
  try {
    await again.mutateAsync({ kind: job.kind, format: job.format === "csv" ? "csv" : "xlsx", params: job.params, deliverTelegram: false });
    toast.success(t("exports.started", { name: job.label }), { description: t("exports.startedHint") });
  } catch {
    // The HTTP layer showed why.
  }
}

const columns = computed<TableColumn<ExportJob>[]>(() => [
  { id: "file", header: t("exports.col.file"), minWidth: 260, hideable: false, value: (row) => row.label, csv: (row) => row.file_name ?? row.label },
  { id: "status", header: t("exports.col.status"), width: 150, value: (row) => t(`exports.status.${row.status}`) },
  { id: "rows", header: t("exports.col.rows"), width: 100, numeric: true, value: (row) => row.rows },
  { id: "created_at", header: t("exports.col.created"), width: 150, value: (row) => row.created_at },
  { id: "expires_at", header: t("exports.col.expires"), width: 150, value: (row) => row.expires_at },
  { id: "actions", header: "", width: 150, align: "end", hideable: false, value: () => null, csv: () => "" },
]);
</script>

<template>
  <div>
    <PageHeader :title="t('exports.title')" :description="t('exports.description')">
      <template #actions>
        <UiButton variant="primary" :icon="Plus" @click="creating = true">{{ t("exports.new") }}</UiButton>
      </template>
    </PageHeader>

    <!-- None yet: the reason and the way to make one, without an empty table and its column picker. -->
    <div v-if="query.data.value?.count === 0" class="ui-card" data-exports-empty>
      <EmptyState :icon="FileSpreadsheet" :title="t('exports.empty.title')" :description="t('exports.empty.body')">
        <UiButton variant="secondary" :icon="Plus" @click="creating = true">{{ t("exports.new") }}</UiButton>
      </EmptyState>
    </div>
    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="rows"
      :total="query.data.value?.count"
      row-key="id"
      :loading="query.isPending.value"
      :fetching="query.isFetching.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      :empty-title="t('exports.empty.title')"
      :empty-description="t('exports.empty.body')"
      :empty-icon="FileSpreadsheet"
      :caption="t('exports.title')"
    >
      <template #cell-file="{ row }">
        <div class="flex min-w-0 items-center gap-3 py-1">
          <span :class="['grid size-8 shrink-0 place-items-center rounded-[8px]', row.format === 'csv' ? 'bg-surface-2 text-muted' : 'bg-success-soft text-success']" aria-hidden="true">
            <FileText v-if="row.format === 'csv'" :size="16" />
            <FileSpreadsheet v-else :size="16" />
          </span>
          <div class="min-w-0">
            <p class="flex min-w-0 items-center gap-1.5">
              <span class="truncate font-semibold text-fg">{{ row.label }}</span>
              <UiBadge variant="outline" class="uppercase">{{ row.format }}</UiBadge>
              <UiTooltip v-if="row.sensitive" :content="t('exports.sensitiveHint')">
                <ShieldAlert :size="14" class="shrink-0 text-warning" :aria-label="t('exports.sensitive')" />
              </UiTooltip>
              <UiTooltip v-if="row.deliver_telegram" :content="t('exports.telegram')">
                <Send :size="13" class="shrink-0 text-info" :aria-label="t('exports.telegram')" />
              </UiTooltip>
            </p>
            <p class="truncate text-xs text-muted">{{ paramsText(row) || row.file_name || t("exports.wholeList") }}</p>
          </div>
        </div>
      </template>
      <template #cell-status="{ row }">
        <UiTooltip :content="row.error" :disabled="!row.error">
          <StatusPill size="sm" :tone="TONES[row.status]" :live="isBuilding(row)" :label="t(`exports.status.${row.status}`)" />
        </UiTooltip>
      </template>
      <template #cell-rows="{ row }">
        <span class="tabular-nums">{{ row.rows === null ? "—" : fmt.number(row.rows) }}</span>
      </template>
      <template #cell-created_at="{ row }"><RelativeTime :value="row.created_at" class="text-muted" /></template>
      <template #cell-expires_at="{ row }">
        <span :class="expired(row) ? 'text-subtle line-through' : 'text-muted'">{{ fmt.instant(row.expires_at, "short") }}</span>
      </template>
      <template #cell-actions="{ row }">
        <div class="flex justify-end gap-1.5">
          <UiButton v-if="row.status === 'ready' && !expired(row)" size="sm" :icon="Download" :loading="downloading === row.id" @click.stop="download(row)">{{ t("exports.download") }}</UiButton>
          <UiButton v-else-if="row.status === 'failed' || expired(row)" size="sm" variant="ghost" :icon="RotateCw" :loading="again.isPending.value && again.variables.value?.kind === row.kind" @click.stop="exportAgain(row)">{{ t("exports.again") }}</UiButton>
        </div>
      </template>

      <template #card="{ row }">
        <div class="flex items-start gap-3">
          <span :class="['grid size-9 shrink-0 place-items-center rounded-[9px]', row.format === 'csv' ? 'bg-surface-2 text-muted' : 'bg-success-soft text-success']" aria-hidden="true">
            <FileText v-if="row.format === 'csv'" :size="17" />
            <FileSpreadsheet v-else :size="17" />
          </span>
          <div class="min-w-0 flex-1">
            <p class="flex items-center gap-1.5">
              <span class="truncate font-semibold text-fg">{{ row.label }}</span>
              <UiBadge variant="outline" class="uppercase">{{ row.format }}</UiBadge>
            </p>
            <p class="mt-0.5 truncate text-xs text-muted">{{ paramsText(row) || t("exports.wholeList") }}</p>
            <div class="mt-2 flex flex-wrap items-center gap-2">
              <StatusPill size="sm" :tone="TONES[row.status]" :live="isBuilding(row)" :label="t(`exports.status.${row.status}`)" />
              <RelativeTime :value="row.created_at" class="text-xs text-subtle" />
              <span v-if="row.rows !== null" class="text-xs text-subtle">· {{ t("exports.rowsCount", { n: fmt.number(row.rows) }) }}</span>
            </div>
            <p v-if="row.error" class="mt-1.5 text-xs text-danger">{{ row.error }}</p>
          </div>
          <UiButton v-if="row.status === 'ready' && !expired(row)" size="sm" :icon="Download" :loading="downloading === row.id" :aria-label="t('exports.download')" @click.stop="download(row)" />
          <UiButton v-else-if="row.status === 'failed' || expired(row)" size="sm" variant="ghost" :icon="RotateCw" :aria-label="t('exports.again')" @click.stop="exportAgain(row)" />
        </div>
      </template>
    </DataTable>

    <NewExportDialog v-model:open="creating" />
  </div>
</template>
