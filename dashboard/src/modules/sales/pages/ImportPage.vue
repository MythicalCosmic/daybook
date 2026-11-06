<script setup lang="ts">
/**
 * Import (plan §14.7): the sale lines of the pharmacy's own cash-register program, for true
 * stock, margins and the legal price check. Three tabs in the URL (`?tab=`): the files (upload one
 * through a saved profile, then its results), the match list (item codes the catalogue doesn't
 * know yet) and the profiles (one per cash-register program, with its column map). Imported
 * receipts are line facts, never money: the tills' totals stay the sales figures.
 */
import { FileSpreadsheet, ListChecks, Settings2, Upload } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import FileDrop from "@/components/FileDrop.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { salesApi, useImports, useOptions, useProfiles, useSalesMutation } from "../api";
import ImportDrawer from "../components/ImportDrawer.vue";
import MatchList from "../components/MatchList.vue";
import ProfileDrawer from "../components/ProfileDrawer.vue";
import { importTone } from "../format";
import type { ImportProfile, SalesImport } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const options = useOptions();
const profiles = useProfiles();

const TABS = ["files", "match", "profiles"] as const;
const tab = useRouteState<(typeof TABS)[number]>("tab", rs.enum(TABS, "files"));
const opened = useRouteState<number | null>("import", rs.optionalNumber());
const editing = ref<ImportProfile | null>(null);
const creating = ref(false);

const on = computed(() => options.data.value?.settings.sales_lines === "import");
const loaded = computed(() => !!options.data.value);
const tabs = computed(() => [
  { value: "files" as const, label: t("sales.import.tab.files") },
  { value: "match" as const, label: t("sales.import.tab.match") },
  { value: "profiles" as const, label: t("sales.import.tab.profiles") },
]);
const active = computed(() => (profiles.data.value ?? []).filter((p) => p.is_active));

// Upload ------------------------------------------------------------------------------------
const profileId = ref<number | null>(null);
const files = ref<File[]>([]);
watch(
  active,
  (rows) => {
    if (!profileId.value || !rows.some((p) => p.id === profileId.value)) profileId.value = rows[0]?.id ?? null;
  },
  { immediate: true },
);
const accept = computed(() => (active.value.find((p) => p.id === profileId.value)?.file_kind === "xlsx" ? ".xlsx" : ".csv,.txt"));
const upload = useSalesMutation((cid, vars: { profile: number; file: File }) => salesApi.upload(cid, vars.profile, vars.file));
async function send(): Promise<void> {
  const chosen = files.value[0];
  if (!profileId.value || !chosen) return;
  const made = await upload.mutateAsync({ profile: profileId.value, file: chosen });
  files.value = [];
  toast.success(t("sales.import.uploaded"));
  opened.value = made.id;
}

// Files -------------------------------------------------------------------------------------
const table = useDataTable({ id: "sales.imports", url: "f_" });
const imports = useImports(computed(() => ({ ...table.params.value })));
const columns = computed<TableColumn<SalesImport>[]>(() => [
  { id: "created_at", header: t("sales.import.col.when"), width: 150, format: (v) => fmt.instant(String(v), "short") },
  { id: "profile", header: t("sales.import.col.profile"), minWidth: 160, value: (row) => row.profile.name },
  { id: "days", header: t("sales.import.col.days"), width: 170, value: (row) => days(row) },
  { id: "status", header: t("sales.import.col.status"), width: 120 },
  { id: "receipts", header: t("sales.import.col.receipts"), numeric: true, width: 100 },
  { id: "matched", header: t("sales.import.col.matched"), numeric: true, width: 100 },
  { id: "unmatched", header: t("sales.import.col.unmatched"), numeric: true, width: 110 },
  { id: "duplicates", header: t("sales.import.col.duplicates"), numeric: true, width: 110 },
  { id: "breaches", header: t("sales.import.col.breaches"), numeric: true, width: 120 },
]);
function days(row: SalesImport): string {
  if (!row.first_day) return "—";
  if (row.first_day === row.last_day || !row.last_day) return fmt.day(row.first_day);
  return `${fmt.day(row.first_day)} – ${fmt.day(row.last_day)}`;
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader :title="t('sales.import.title')" :description="t('sales.import.description')" class="!mb-0">
      <template v-if="on" #actions>
        <UiButton variant="secondary" :icon="Settings2" @click="creating = true">{{ t("sales.import.newProfile") }}</UiButton>
      </template>
    </PageHeader>

    <EmptyState v-if="loaded && !on" :icon="FileSpreadsheet" :title="t('sales.import.offTitle')" :description="t('sales.import.offBody')">
      <UiButton v-if="company.can('sales.manage')" variant="primary" :to="`/c/${company.currentId}/settings/sales`">{{ t("sales.import.offAction") }}</UiButton>
    </EmptyState>

    <template v-else-if="on">
      <SegmentedControl v-model="tab" :options="tabs" :aria-label="t('sales.import.title')" />

      <template v-if="tab === 'files'">
        <PageSection variant="card" :title="t('sales.import.uploadTitle')" :description="t('sales.import.uploadHint')">
          <EmptyState v-if="profiles.data.value && !active.length" size="sm" :icon="Settings2" :title="t('sales.import.noProfileTitle')" :description="t('sales.import.noProfileBody')">
            <UiButton variant="primary" :icon="Settings2" @click="creating = true">{{ t("sales.import.newProfile") }}</UiButton>
          </EmptyState>
          <div v-else class="grid gap-4 md:grid-cols-[minmax(0,240px)_minmax(0,1fr)_auto] md:items-end">
            <FormField :label="t('sales.import.profile')" required>
              <SelectBox v-model="profileId" :options="active.map((p) => ({ value: p.id, label: p.name, description: p.branch?.name ?? t('sales.import.branchColumn') }))" />
            </FormField>
            <FormField :label="t('sales.import.file')" required>
              <FileDrop v-model="files" :accept="accept" :max-size="20 * 1024 * 1024" compact :title="t('sales.import.drop')" />
            </FormField>
            <UiButton variant="primary" :icon="Upload" :disabled="!profileId || !files.length" :loading="upload.isPending.value" @click="send">{{ t("sales.import.send") }}</UiButton>
          </div>
        </PageSection>
        <DataTable
          :state="table"
          :columns="columns"
          :rows="imports.data.value?.results"
          :total="imports.data.value?.count"
          row-key="id"
          clickable
          :loading="imports.isPending.value"
          :fetching="imports.isFetching.value"
          :error="imports.error.value"
          :retry="() => imports.refetch()"
          :empty-title="t('sales.import.emptyTitle')"
          :empty-description="t('sales.import.emptyBody')"
          :empty-icon="FileSpreadsheet"
          csv-name="sale-line-imports"
          @row-click="(row: SalesImport) => (opened = row.id)"
        >
          <template #cell-status="{ row }">
            <StatusPill size="sm" :tone="importTone(row.status)" :label="t(`sales.import.status.${row.status}`)" :live="row.status === 'processing'" />
          </template>
          <template #cell-unmatched="{ row }">
            <span :class="row.unmatched ? 'font-semibold text-warning' : 'text-muted'">{{ fmt.number(row.unmatched) }}</span>
          </template>
          <template #cell-breaches="{ row }">
            <span :class="row.breaches ? 'font-semibold text-danger' : 'text-muted'">{{ fmt.number(row.breaches) }}</span>
          </template>
          <template #card="{ row }">
            <div class="flex items-center justify-between gap-3">
              <div class="min-w-0">
                <p class="truncate text-sm font-semibold text-fg">{{ row.profile.name }} · {{ days(row) }}</p>
                <p class="truncate text-xs text-muted">{{ t("sales.import.cardLine", { receipts: row.receipts, matched: row.matched, unmatched: row.unmatched }) }}</p>
              </div>
              <StatusPill size="sm" :tone="importTone(row.status)" :label="t(`sales.import.status.${row.status}`)" />
            </div>
          </template>
        </DataTable>
      </template>

      <MatchList v-else-if="tab === 'match'" />

      <template v-else>
        <InlineAlert tone="info" size="sm" :description="t('sales.import.profilesHint')" />
        <div class="grid gap-3 md:grid-cols-2">
          <button
            v-for="profile in profiles.data.value ?? []"
            :key="profile.id"
            type="button"
            class="flex items-start gap-3 rounded-xl border border-line bg-surface p-4 text-start transition hover:border-line-strong focus-visible:outline-2 focus-visible:outline-primary"
            @click="editing = profile"
          >
            <ListChecks :size="18" class="mt-0.5 shrink-0 text-subtle" />
            <span class="min-w-0 flex-1">
              <span class="flex items-center gap-2">
                <span class="truncate font-semibold text-fg">{{ profile.name }}</span>
                <StatusPill v-if="!profile.is_active" size="sm" tone="neutral" :label="t('sales.import.archived')" />
              </span>
              <span class="mt-0.5 block text-sm text-muted">
                {{ [profile.file_kind.toUpperCase(), profile.branch?.name ?? t("sales.import.branchColumn"), t("sales.import.mapped", { n: Object.keys(profile.columns).length }, Object.keys(profile.columns).length)].join(" · ") }}
              </span>
              <span v-if="profile.last_import" class="mt-0.5 block text-xs text-subtle">{{ t("sales.import.lastFile", { when: fmt.instant(profile.last_import.created_at, "short") }) }}</span>
            </span>
          </button>
        </div>
        <EmptyState v-if="profiles.data.value && !profiles.data.value.length" :icon="Settings2" :title="t('sales.import.noProfileTitle')" :description="t('sales.import.noProfileBody')">
          <UiButton variant="primary" :icon="Settings2" @click="creating = true">{{ t("sales.import.newProfile") }}</UiButton>
        </EmptyState>
      </template>
    </template>

    <ImportDrawer :import-id="opened" @close="opened = null" />
    <ProfileDrawer :open="creating || !!editing" :profile="editing" @close="(creating = false), (editing = null)" />
  </div>
</template>
