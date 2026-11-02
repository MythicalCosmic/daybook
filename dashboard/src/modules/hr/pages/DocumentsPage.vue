<script setup lang="ts">
/**
 * Documents (plan §6.2 HR): every document with its expiry, filterable by state, kind and check;
 * chips for the ones expiring and expired; the drawer on `?document=`; "Upload" (`?upload=1` opens
 * it from the palette). The second tab is the compliance matrix: who lacks what their position
 * requires.
 */
import { CircleAlert, CircleCheck, FileText, FileWarning, Files, ListChecks, LockKeyhole, Paperclip, ShieldCheck, Tags, Upload } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDataTable } from "@/components/useDataTable";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useDocuments, useOverview } from "../api";
import ComplianceMatrix from "../components/ComplianceMatrix.vue";
import DaysChip from "../components/DaysChip.vue";
import DocumentDrawer from "../components/DocumentDrawer.vue";
import DocumentFormDrawer from "../components/DocumentFormDrawer.vue";
import RequiredDocumentsDrawer from "../components/RequiredDocumentsDrawer.vue";
import { documentParams, hrAccess, kindGroup, needsSensitive } from "../lib";
import { DOCUMENT_KINDS, type DocumentKind, type HrDocument } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const access = computed(() => hrAccess((perm) => company.can(perm)));

const view = useRouteState<"list" | "compliance">("view", rs.enum(["list", "compliance"] as const, "list"));
const search = useRouteState("q", rs.string(""));
const overview = useOverview();
const warnDays = computed(() => overview.data.value?.warn_days.documents ?? 30);

const defs = computed<FilterDef[]>(() => [
  {
    key: "state",
    label: t("hr.filter.state"),
    type: "select",
    icon: FileWarning,
    options: [
      { value: "expiring", label: t("hr.documentState.expiring") },
      { value: "expired", label: t("hr.documentState.expired") },
    ],
  },
  {
    key: "kind",
    label: t("hr.field.kind"),
    type: "multi",
    icon: Tags,
    options: DOCUMENT_KINDS.map((kind) => ({ value: kind, label: t(`hr.kind.${kind}`), group: t(`hr.kindGroup.${kindGroup(kind)}`) })),
  },
  { key: "verified", label: t("hr.filter.verified"), type: "boolean", icon: ShieldCheck, trueLabel: t("hr.document.verified"), falseLabel: t("hr.document.notVerified") },
]);
const filters = useUrlFilters(defs);
const table = useDataTable({ id: "hr.documents", url: true, ordering: "expires_on" });
table.resetPageOn(() => [filters.params.value, search.value]);

const params = computed(() => ({ ...documentParams(filters.values.value, search.value, warnDays.value), ...table.params.value }));
const documents = useDocuments(params, computed(() => view.value === "list"));
const filtered = computed(() => filters.active.value > 0 || !!search.value);

const counts = computed(() => overview.data.value?.documents ?? null);
const state = computed(() => {
  const value = filters.values.value.state;
  return typeof value === "string" ? value : null;
});
function toggleState(next: "expiring" | "expired"): void {
  filters.values.value = { ...filters.values.value, state: state.value === next ? null : next };
}

const tabs = computed(() => [
  { id: "list", label: t("hr.document.tabList"), icon: Files },
  { id: "compliance", label: t("hr.document.tabCompliance"), icon: ListChecks },
]);

const columns = computed<TableColumn<HrDocument>[]>(() => [
  { id: "member", header: t("hr.field.person"), minWidth: 200, sticky: true, hideable: false, value: (row) => row.member.name },
  { id: "kind", header: t("hr.field.kind"), minWidth: 180, value: (row) => t(`hr.kind.${row.kind}`) },
  { id: "number", header: t("hr.field.number"), width: 140, value: (row) => row.number },
  { id: "expires_on", header: t("hr.field.expiresOn"), width: 168, sortable: true, value: (row) => row.expires_on ?? "" },
  { id: "verified", header: t("hr.filter.verified"), width: 140, value: (row) => (row.verified_at ? "1" : "") },
  { id: "file", header: t("hr.field.file"), width: 64, align: "center", hideable: false, value: (row) => (row.file ? "1" : "") },
]);

function open(row: HrDocument): void {
  void router.push({ query: { ...route.query, document: String(row.id) } });
}
const activeKey = computed(() => (typeof route.query.document === "string" ? route.query.document : null));

// "Upload" opens from the palette too (?upload=1), also when the page is already open.
const uploading = ref(false);
/** The matrix's missing cell: upload for that person and kind. */
const uploadFor = ref<{ member: { id: number; name: string }; kind: DocumentKind } | null>(null);
function upload(prefill: { member: { id: number; name: string }; kind: DocumentKind } | null = null): void {
  uploadFor.value = prefill;
  uploading.value = true;
}
const uploadParam = useRouteState("upload", rs.boolean(false));
watch(
  uploadParam,
  (value) => {
    if (!value) return;
    uploadParam.value = false;
    if (access.value.manage) upload();
  },
  { immediate: true },
);
const editing = ref<HrDocument | null>(null);
const editOpen = computed({
  get: () => editing.value !== null,
  set: (value: boolean) => {
    if (!value) editing.value = null;
  },
});
const requiredOpen = ref(false);

function hiddenFile(row: HrDocument): boolean {
  return !row.file && needsSensitive(row.kind as DocumentKind) && !access.value.sensitive;
}
</script>

<template>
  <div>
    <PageHeader v-model:tab="view" :title="t('hr.nav.documents')" :description="t('hr.document.description')" :tabs="tabs">
      <template v-if="access.manage" #actions>
        <UiButton v-if="view === 'compliance'" :icon="ListChecks" @click="requiredOpen = true">{{ t("hr.required.button") }}</UiButton>
        <UiButton variant="primary" :icon="Upload" @click="upload()">{{ t("hr.document.upload") }}</UiButton>
      </template>
    </PageHeader>

    <template v-if="view === 'list'">
      <!-- The two chips that matter most, with their counts from the overview. -->
      <div v-if="counts && (counts.expiring || counts.expired)" class="mb-3 flex flex-wrap gap-2" role="group" :aria-label="t('hr.filter.state')">
        <button
          v-if="counts.expiring"
          type="button"
          :aria-pressed="state === 'expiring'"
          :class="[
            'pressable inline-flex h-9 items-center gap-2 rounded-full border px-3.5 text-sm font-semibold transition-colors',
            state === 'expiring' ? 'border-transparent bg-warning text-white dark:text-[#2a1c05]' : 'border-line bg-surface text-warning hover:bg-warning-soft',
          ]"
          @click="toggleState('expiring')"
        >
          <CircleAlert :size="15" aria-hidden="true" />{{ t("hr.documentState.expiring") }}<span class="tabular-nums opacity-80">{{ counts.expiring }}</span>
        </button>
        <button
          v-if="counts.expired"
          type="button"
          :aria-pressed="state === 'expired'"
          :class="[
            'pressable inline-flex h-9 items-center gap-2 rounded-full border px-3.5 text-sm font-semibold transition-colors',
            state === 'expired' ? 'border-transparent bg-danger text-white dark:text-[#2a0c06]' : 'border-line bg-surface text-danger hover:bg-danger-soft',
          ]"
          @click="toggleState('expired')"
        >
          <FileWarning :size="15" aria-hidden="true" />{{ t("hr.documentState.expired") }}<span class="tabular-nums opacity-80">{{ counts.expired }}</span>
        </button>
      </div>

      <DataTable
        :state="table"
        :columns="columns"
        :rows="documents.data.value?.results"
        :total="documents.data.value?.count"
        row-key="id"
        :loading="documents.isPending.value"
        :fetching="documents.isFetching.value"
        :error="documents.error.value"
        :retry="() => documents.refetch()"
        clickable
        :active-key="activeKey"
        :filtered="filtered"
        @row-click="open"
        @clear-filters="
          filters.clear();
          search = '';
        "
      >
        <template #toolbar>
          <FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable :search-placeholder="t('hr.document.search')" />
        </template>
        <template #empty>
          <EmptyState :icon="FileText" :title="filtered ? t('hr.empty.noMatch') : t('hr.document.emptyTitle')" :description="filtered ? t('hr.empty.noMatchBody') : t('hr.document.emptyBody')">
            <UiButton v-if="!filtered && access.manage" variant="primary" :icon="Upload" @click="upload()">{{ t("hr.document.upload") }}</UiButton>
          </EmptyState>
        </template>
        <template #cell-member="{ row }">
          <div class="flex min-w-0 items-center gap-2.5">
            <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="28" />
            <div class="min-w-0">
              <p class="truncate text-base font-medium text-fg" :title="row.member.name">{{ row.member.name }}</p>
              <p v-if="row.position" class="truncate text-xs text-muted">{{ row.position }}</p>
            </div>
          </div>
        </template>
        <template #cell-kind="{ row }">
          <div class="min-w-0">
            <p class="truncate text-sm text-fg">{{ t(`hr.kind.${row.kind}`) }}</p>
            <p v-if="row.title && row.title !== t(`hr.kind.${row.kind}`)" class="truncate text-xs text-muted" :title="row.title">{{ row.title }}</p>
          </div>
        </template>
        <template #cell-number="{ row }">
          <span v-if="row.number" class="truncate font-mono text-sm tabular-nums text-fg">{{ row.number }}</span>
          <span v-else class="text-sm text-subtle">—</span>
        </template>
        <template #cell-expires_on="{ row }">
          <div v-if="row.expires_on" class="flex min-w-0 flex-col items-start gap-0.5">
            <span class="text-sm text-fg">{{ fmt.day(row.expires_on, "medium") }}</span>
            <DaysChip :day="row.expires_on" :warn-days="warnDays" prefix="expires" />
          </div>
          <span v-else class="text-sm text-subtle">{{ t("hr.document.noExpiry") }}</span>
        </template>
        <template #cell-verified="{ row }">
          <StatusPill v-if="row.verified_at" tone="success" size="sm" :icon="CircleCheck" :dot="false" :label="t('hr.document.verified')" />
          <StatusPill v-else tone="neutral" size="sm" :label="t('hr.document.notVerified')" />
        </template>
        <template #cell-file="{ row }">
          <a v-if="row.file" :href="row.file" target="_blank" rel="noopener" class="pressable grid size-8 place-items-center rounded-button text-muted hover:bg-highlight hover:text-fg" :aria-label="t('hr.document.openFile')" @click.stop>
            <Paperclip :size="16" />
          </a>
          <LockKeyhole v-else-if="hiddenFile(row)" :size="15" class="text-subtle" :aria-label="t('hr.document.fileHidden')" />
        </template>
        <template #card="{ row }">
          <div class="flex items-start gap-3">
            <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="36" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
              <p class="truncate text-sm text-muted">{{ row.title && row.title !== t(`hr.kind.${row.kind}`) ? `${t(`hr.kind.${row.kind}`)} · ${row.title}` : t(`hr.kind.${row.kind}`) }}</p>
              <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
                <span v-if="row.expires_on" class="text-xs text-muted">{{ t("hr.document.expiresShort", { date: fmt.day(row.expires_on, "medium") }) }}</span>
                <DaysChip v-if="row.expires_on" :day="row.expires_on" :warn-days="warnDays" prefix="expires" />
                <StatusPill v-if="row.verified_at" tone="success" size="sm" :icon="CircleCheck" :dot="false" :label="t('hr.document.verified')" />
              </div>
            </div>
            <Paperclip v-if="row.file" :size="16" class="mt-1 shrink-0 text-subtle" aria-hidden="true" />
          </div>
        </template>
      </DataTable>
    </template>

    <ComplianceMatrix v-else :can-manage="access.manage" @upload="upload" @configure="requiredOpen = true" />

    <DocumentDrawer :warn-days="warnDays" @edit="editing = $event" />
    <DocumentFormDrawer v-model:open="uploading" :member="uploadFor?.member ?? null" :kind="uploadFor?.kind ?? null" />
    <DocumentFormDrawer v-model:open="editOpen" :document="editing" />
    <RequiredDocumentsDrawer v-if="access.manage" v-model:open="requiredOpen" />
  </div>
</template>
