<script setup lang="ts">
/**
 * Team › Employees: everyone the terminals know, with their photo, job, location, where they are
 * today, their Face ID numbers and whether their Telegram is linked. Search and filters live in
 * the URL; a row opens the person's page. `?employee=new|<id>` opens the form, `?import=1` the
 * spreadsheet import (the palette's commands land there too).
 */
import { Download, ListFilter, ScanFace, Send, Upload, UserPlus, Users } from "@lucide/vue";
import { computed, defineAsyncComponent, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import BranchPicker from "@/components/BranchPicker.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { useDataTable } from "@/components/useDataTable";
import UserAvatar from "@/components/UserAvatar.vue";
import { formatPhone } from "@/lib/format";
import { useFormat } from "@/lib/useFormat";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useCan } from "@/lib/usePermission";
import { patchQuery, rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { exportEmployees, useDepartments, useEmployees, usePositions } from "../api";
import { branchNames } from "../components/team/team";
import { useTeamTabs } from "../components/team/tabs";
import TodayChip from "../components/team/TodayChip.vue";
import type { Employee, EmployeeParams } from "../types";

const EmployeeDrawer = defineAsyncComponent(() => import("../components/team/EmployeeDrawer.vue"));
const ImportDialog = defineAsyncComponent(() => import("../components/team/ImportDialog.vue"));

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const tabs = useTeamTabs();
const canManage = useCan("members.manage");
const { isPhone } = useBreakpoints();
/** Phones keep the search and the status in view; the other filters fold under one button. */
const filtersOpen = ref(false);

const search = useRouteState("q", rs.string(""));
const status = useRouteState("status", rs.enum(["active", "left", "all"] as const, "active"));
// The server filters by one location at a time.
const branchId = useRouteState("branch", rs.optionalNumber());
const department = useRouteState("department", rs.optionalNumber());
const position = useRouteState("position", rs.optionalNumber());
const telegram = useRouteState("telegram", rs.enum(["any", "1", "0"] as const, "any"));
const face = useRouteState("face", rs.enum(["any", "1", "0"] as const, "any"));
const importOpen = useRouteState("import", rs.boolean(false), { push: true });

const table = useDataTable({ id: "davomat.employees", pageSize: 100, pageSizes: [50, 100, 200, 500], url: true });
table.resetPageOn(() => [search.value, status.value, branchId.value, department.value, position.value, telegram.value, face.value]);

const params = computed<EmployeeParams>(() => ({
  search: search.value || undefined,
  status: status.value === "all" ? undefined : status.value,
  branch: branchId.value !== null ? [branchId.value] : company.branchFilter.length === 1 ? [...company.branchFilter] : undefined,
  department: department.value ?? undefined,
  position: position.value ?? undefined,
  linked: telegram.value === "any" ? undefined : telegram.value,
  face: face.value === "any" ? undefined : face.value,
  ...table.params.value,
}));
const query = useEmployees(params);
const positions = usePositions();
const departments = useDepartments();

const rows = computed(() => query.data.value?.results);
const total = computed(() => query.data.value?.count ?? 0);
const filtered = computed(() => Boolean(search.value || status.value !== "active" || branchId.value !== null || department.value || position.value || telegram.value !== "any" || face.value !== "any"));
const extraFilters = computed(() => [branchId.value !== null, department.value !== null, position.value !== null, face.value !== "any", telegram.value !== "any"].filter(Boolean).length);
const nobody = computed(() => query.data.value !== undefined && total.value === 0 && !filtered.value && !company.branchFilter.length);

const branches = computed(() => company.current?.branches ?? []);
const positionOptions = computed(() => (positions.data.value ?? []).filter((p) => p.is_active).map((p) => ({ value: p.id, label: p.name })));
const departmentOptions = computed(() => (departments.data.value ?? []).map((d) => ({ value: d.id, label: d.name })));
const telegramOptions = computed(() => [
  { value: "1" as const, label: t("davomat.team.filter.telegramLinked") },
  { value: "0" as const, label: t("davomat.team.filter.telegramNot") },
]);
const telegramModel = computed({ get: () => (telegram.value === "any" ? null : telegram.value), set: (value: "1" | "0" | null) => (telegram.value = value ?? "any") });
const faceOptions = computed(() => [
  { value: "0" as const, label: t("davomat.team.filter.faceNone") },
  { value: "1" as const, label: t("davomat.team.filter.faceSome") },
]);
const faceModel = computed({ get: () => (face.value === "any" ? null : face.value), set: (value: "1" | "0" | null) => (face.value = value ?? "any") });
const statusOptions = computed(() => [
  { value: "active" as const, label: t("davomat.team.filter.active") },
  { value: "left" as const, label: t("davomat.team.filter.left") },
  { value: "all" as const, label: t("davomat.team.filter.all") },
]);

function where(row: Employee): string {
  const names = branchNames(row.branch_ids, branches.value);
  if (names.length <= 2) return names.join(", ");
  return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
}

function job(row: Employee): string {
  return [row.position?.name, row.department?.name].filter(Boolean).join(" · ");
}

const columns = computed<TableColumn<Employee>[]>(() => [
  { id: "name", header: t("davomat.team.col.name"), minWidth: 260, sticky: true, hideable: false, value: (row) => row.full_name },
  { id: "job", header: t("davomat.team.col.job"), minWidth: 180, value: job },
  { id: "branch", header: t("davomat.team.col.branch"), minWidth: 150, value: where },
  { id: "today", header: t("davomat.team.col.today"), width: 176, value: (row) => row.today?.state ?? "" },
  { id: "face", header: t("davomat.team.col.face"), width: 160, value: (row) => row.face_numbers.join(" ") },
  { id: "telegram", header: t("davomat.team.col.telegram"), width: 118, value: (row) => (row.telegram_linked ? t("davomat.team.telegram.linked") : "") },
]);

function open(row: Employee): void {
  void router.push(`/c/${company.currentId}/team/${row.id}`);
}

function add(): void {
  patchQuery(router, { employee: "new" }, true);
}

function clearFilters(): void {
  search.value = "";
  status.value = "active";
  branchId.value = null;
  department.value = null;
  position.value = null;
  telegram.value = "any";
  face.value = "any";
}

const exporting = ref(false);
async function exportList(): Promise<void> {
  exporting.value = true;
  try {
    await exportEmployees(company.currentId ?? 0, { ...params.value, page: undefined, page_size: undefined });
  } catch {
    // The HTTP layer has shown why.
  } finally {
    exporting.value = false;
  }
}
</script>

<template>
  <div>
    <PageHeader :title="t('davomat.nav.team')" :description="t('davomat.team.description')" :tabs="tabs">
      <template #actions>
        <UiButton v-if="canManage" variant="secondary" :icon="Upload" data-open-import @click="importOpen = true">{{ t("davomat.team.import.open") }}</UiButton>
        <UiButton variant="secondary" :icon="Download" :loading="exporting" data-export @click="exportList">{{ t("common.export") }}</UiButton>
        <UiButton v-if="canManage" variant="primary" :icon="UserPlus" data-add-employee @click="add">{{ t("davomat.cmd.addEmployee") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="nobody" class="ui-card" data-team-empty>
      <EmptyState :icon="Users" size="lg" :title="t('davomat.team.empty.title')" :description="t('davomat.team.empty.body')">
        <div v-if="canManage" class="flex flex-wrap justify-center gap-2">
          <UiButton variant="primary" :icon="UserPlus" @click="add">{{ t("davomat.cmd.addEmployee") }}</UiButton>
          <UiButton variant="secondary" :icon="Upload" @click="importOpen = true">{{ t("davomat.team.import.open") }}</UiButton>
        </div>
      </EmptyState>
    </div>

    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="rows"
      :total="total"
      row-key="id"
      :loading="query.isPending.value"
      :fetching="query.isFetching.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      clickable
      :filtered="filtered"
      :empty-title="filtered ? t('davomat.team.emptyFiltered') : t('davomat.team.emptyHere')"
      :empty-icon="Users"
      @row-click="open"
      @clear-filters="clearFilters"
    >
      <template #toolbar>
        <TextInput v-model="search" :debounce="250" type="search" size="sm" class="w-full sm:w-60" :placeholder="t('davomat.team.filter.search')" clearable data-search />
        <SegmentedControl v-model="status" size="sm" :options="statusOptions" :aria-label="t('davomat.team.filter.status')" />
        <UiButton v-if="isPhone" size="sm" variant="secondary" :icon="ListFilter" :aria-expanded="filtersOpen" data-more-filters @click="filtersOpen = !filtersOpen">
          {{ t("common.filters") }}<template v-if="extraFilters"> · {{ extraFilters }}</template>
        </UiButton>
        <template v-if="!isPhone || filtersOpen">
        <BranchPicker v-if="branches.length > 1" v-model="branchId" size="sm" class="w-full sm:w-48" :branches="branches" :placeholder="t('davomat.team.filter.branch')" />
        <SelectBox v-if="departmentOptions.length" v-model="department" size="sm" class="w-full sm:w-44" :options="departmentOptions" clearable :placeholder="t('davomat.team.filter.department')" />
        <SelectBox v-if="positionOptions.length" v-model="position" size="sm" class="w-full sm:w-44" :options="positionOptions" clearable :placeholder="t('davomat.team.filter.position')" />
        <SelectBox v-model="faceModel" size="sm" class="w-full sm:w-44" :options="faceOptions" clearable :placeholder="t('davomat.team.filter.face')" />
        <SelectBox v-model="telegramModel" size="sm" class="w-full sm:w-40" :options="telegramOptions" clearable :placeholder="t('davomat.team.filter.telegram')" />
        </template>
      </template>
      <template #actions>
        <span v-if="query.data.value" class="hidden whitespace-nowrap text-sm tabular-nums text-muted md:inline" data-count>{{ t("davomat.team.count", { n: fmt.number(total) }, total) }}</span>
      </template>

      <template #cell-name="{ row }">
        <div class="flex min-w-0 items-center gap-3">
          <UserAvatar :name="row.full_name" :src="row.photo_url" :size="36" :status="row.today?.state === 'in' ? 'in' : undefined" />
          <span class="min-w-0">
            <span class="block truncate font-semibold text-fg">{{ row.full_name }}</span>
            <span v-if="row.source === 'terminal' && row.status === 'active'" class="flex items-center gap-1 truncate text-xs font-medium text-info" :title="t('davomat.team.fromTerminalHint')" data-from-terminal
              ><ScanFace :size="12" class="shrink-0" aria-hidden="true" />{{ t("davomat.team.fromTerminal") }}</span
            >
            <span v-else class="block truncate text-xs tabular-nums text-muted">{{ formatPhone(row.phone) || (row.is_user ? t("davomat.team.alsoUser") : "") }}</span>
          </span>
        </div>
      </template>
      <template #cell-job="{ row }">
        <span class="min-w-0">
          <span class="block truncate text-fg">{{ row.position?.name || "—" }}</span>
          <span v-if="row.department" class="block truncate text-xs text-muted">{{ row.department.name }}</span>
        </span>
      </template>
      <template #cell-branch="{ row }">
        <span class="block truncate text-fg">{{ where(row) || "—" }}</span>
      </template>
      <template #cell-today="{ row }">
        <TodayChip :today="row.today" :status="row.status" />
        <span v-if="!row.today && row.status === 'active'" class="text-subtle">—</span>
      </template>
      <template #cell-face="{ row }">
        <span v-if="row.face_numbers.length" class="flex min-w-0 items-center gap-1">
          <span class="ui-chip font-mono tabular-nums">{{ row.face_numbers[0] }}</span>
          <UiBadge v-if="row.face_numbers.length > 1" :title="row.face_numbers.join(', ')">+{{ row.face_numbers.length - 1 }}</UiBadge>
        </span>
        <span v-else class="text-sm text-warning">{{ t("davomat.team.noFace") }}</span>
      </template>
      <template #cell-telegram="{ row }">
        <span v-if="row.telegram_linked" class="inline-flex items-center gap-1.5 text-sm font-medium text-success"><Send :size="14" aria-hidden="true" />{{ t("davomat.team.telegram.linked") }}</span>
        <span v-else class="text-subtle">—</span>
      </template>

      <template #card="{ row }">
        <div class="flex items-center gap-3">
          <UserAvatar :name="row.full_name" :src="row.photo_url" :size="44" :status="row.today?.state === 'in' ? 'in' : undefined" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-base font-semibold text-fg">{{ row.full_name }}</p>
            <p class="truncate text-sm text-muted">{{ job(row) || where(row) || "—" }}</p>
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <TodayChip :today="row.today" :status="row.status" />
              <span v-if="row.face_numbers.length" class="ui-chip font-mono tabular-nums">{{ row.face_numbers[0] }}</span>
              <span v-else class="text-xs text-warning">{{ t("davomat.team.noFace") }}</span>
              <Send v-if="row.telegram_linked" :size="13" class="text-success" :aria-label="t('davomat.team.telegram.linked')" />
            </div>
          </div>
        </div>
      </template>
    </DataTable>

    <EmployeeDrawer />
    <ImportDialog v-if="canManage" v-model:open="importOpen" />
  </div>
</template>
