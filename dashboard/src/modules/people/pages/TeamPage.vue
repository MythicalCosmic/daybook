<script setup lang="ts">
/**
 * The team directory (plan §6.2 "Team"): everyone who works here with today's status, position,
 * role, branch, how their work goes and, with the permission, their salary. Saved views as tabs,
 * filters in the URL, a card list on phones; a row opens Person 360.
 */
import { BriefcaseBusiness, Building2, CircleDot, ShieldCheck, Smartphone, UserCheck, UserPlus, UserRoundX, Users } from "@lucide/vue";
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import DataTable from "@/components/DataTable.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import { branchToOption, useScopedBranches } from "@/components/pickers";
import ProgressBar from "@/components/ProgressBar.vue";
import SavedViewsTabs, { type ViewTab } from "@/components/SavedViewsTabs.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { counter, pulse } from "@/core/pulse";
import { formatPhone } from "@/lib/format";
import { useFormat } from "@/lib/useFormat";
import { usePermission } from "@/lib/usePermission";
import { rs, useRouteState } from "@/lib/useRouteState";
import { paramsDiffer, useSavedViews } from "@/lib/useSavedViews";
import { useCompanyStore } from "@/stores/company";

import { usePeople, usePositions, useRoles } from "../api";
import { rateTone, statusChip } from "../status";
import type { DirectoryStatus, Person } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const { can } = usePermission();

const STATUSES: DirectoryStatus[] = ["current", "active", "suspended", "former"];
const status = useRouteState<DirectoryStatus>("status", rs.enum(["current", "active", "suspended", "pending", "left", "blocked", "former"] as const, "current"));
const search = useRouteState("q", rs.string(""));

const positions = usePositions();
const roles = useRoles(computed(() => can(["roles.manage", "members.approve", "members.view"])));
const branches = useScopedBranches();

const defs = computed<FilterDef[]>(() => [
  {
    key: "position",
    label: t("people.col.position"),
    type: "multi",
    icon: BriefcaseBusiness,
    options: (positions.data.value ?? []).map((p) => ({ value: String(p.id), label: p.name })),
  },
  {
    key: "branch",
    label: t("people.col.branch"),
    type: "multi",
    icon: Building2,
    options: branches.value.map((b) => ({ ...branchToOption(b), value: String(b.id) })),
  },
  {
    key: "role",
    label: t("people.col.role"),
    type: "multi",
    icon: ShieldCheck,
    options: (roles.data.value ?? []).map((r) => ({ value: String(r.id), label: r.name })),
  },
  { key: "bot_blocked", label: t("people.filter.botBlocked"), type: "boolean", icon: Smartphone, trueLabel: t("people.filter.botBlockedYes") },
]);
const filters = useUrlFilters(defs);

// Joined and phone start hidden so the rest fits a laptop screen without sideways scrolling
// (both are one click away in the column picker, and on every Person 360).
const table = useDataTable({ id: "people.team", ordering: "name", pageSize: 50, url: true, hidden: ["phone", "joined"] });
const params = computed(() => ({
  ...filters.params.value,
  q: search.value || undefined,
  status: status.value,
  ...table.params.value,
}));
watch([() => filters.params.value, search, status], () => table.resetPage(), { deep: true });
const query = usePeople(params);
const rows = computed(() => query.data.value?.results ?? []);
const chips = computed(() => new Map(rows.value.map((row) => [row.id, statusChip(row, (d) => fmt.day(d, "short"))])));
const chip = (row: Person) => chips.value.get(row.id) ?? statusChip(row, (d) => fmt.day(d, "short"));
const chipLabel = (row: Person) => t(chip(row).key, chip(row).params ?? {});
const RATE_TEXT = { success: "text-success", warning: "text-warning", danger: "text-danger", neutral: "text-subtle" } as const;

// Numbers above the table.
const stats = useQuery({
  queryKey: computed(() => qk(company.currentId ?? 0, "people", "stats")),
  queryFn: ({ signal }) =>
    http.get<{ current: number; active: number; suspended: number; on_leave_today: number; joined_30d: number; left_30d: number; pending_requests: number; bot_blocked: number }>(
      ownerPath(company.currentId!, "people/stats/"),
      undefined,
      { signal },
    ),
  enabled: computed(() => company.currentId !== null),
  staleTime: 15_000,
});
const kpis = computed(() => {
  const s = stats.data.value;
  return [
    { id: "active", label: t("people.kpi.active"), value: s?.active, hint: t("people.kpi.activeHint") },
    { id: "leave", label: t("people.kpi.onLeave"), value: s?.on_leave_today, hint: t("people.kpi.onLeaveHint") },
    { id: "joined", label: t("people.kpi.joined"), value: s?.joined_30d, hint: t("people.kpi.joinedHint") },
    { id: "suspended", label: t("people.kpi.suspended"), value: s?.suspended, hint: t("people.kpi.suspendedHint") },
  ];
});
const pending = computed(() => counter("members.pending")(pulse.value) || stats.data.value?.pending_requests || 0);
/** Settings › Invite staff at its team links, for approvers (once the settings page exists). */
const addPeople = computed(() => {
  if (!can("members.approve")) return null;
  const path = `/c/${company.currentId}/settings/invite`;
  return router.resolve(path).name !== "company-not-found" ? `${path}#team-links` : null;
});

// Saved views: built-in statuses first, then the person's own and shared ones.
const views = useSavedViews("people");
const viewId = ref<ViewTab["id"]>(status.value);
const builtins = computed<ViewTab[]>(() =>
  STATUSES.map((value) => ({ id: value, name: t(`people.view.${value}`), builtin: true, count: value === "current" ? stats.data.value?.current : value === "suspended" ? stats.data.value?.suspended || undefined : undefined })),
);
const tabs = computed(() => [...builtins.value, ...views.tabs.value]);
const currentState = computed(() => ({ ...filters.params.value, status: status.value, q: search.value || undefined }));
const dirty = computed(() => {
  const saved = views.find(viewId.value);
  if (saved) return paramsDiffer(currentState.value, saved.state);
  return paramsDiffer({ ...filters.params.value, q: search.value || undefined }, {});
});
watch(viewId, (id) => {
  if (typeof id === "string" && (STATUSES as string[]).includes(id)) {
    status.value = id as DirectoryStatus;
    return;
  }
  const saved = views.find(id);
  if (!saved) return;
  const state = saved.state as Record<string, unknown>;
  status.value = (state.status as DirectoryStatus) ?? "current";
  search.value = (state.q as string) ?? "";
  const next: Record<string, unknown> = {};
  for (const def of defs.value) next[def.key] = state[def.key] ?? (def.type === "multi" ? [] : null);
  filters.values.value = next as never;
});

async function saveView(input: { name: string; shared: boolean }): Promise<void> {
  const view = await views.create.mutateAsync({ name: input.name, is_shared: input.shared, state: currentState.value });
  viewId.value = view.id;
  toast.success(t("people.view.saved", { name: input.name }));
}

// Columns: salary and attendance appear only when their module sent them; the last day only
// for people who left.
const formerView = computed(() => ["former", "left", "blocked"].includes(status.value));
const hasSalary = computed(() => rows.value.some((row) => row.fields?.salary !== undefined));
const hasAttendance = computed(() => rows.value.some((row) => row.fields?.attendance_30d !== undefined));
const columns = computed<TableColumn<Person>[]>(() => {
  const list: TableColumn<Person>[] = [
    { id: "person", header: t("people.col.person"), minWidth: 240, sticky: true, hideable: false, sortable: "name", value: (row) => row.name },
    { id: "status", header: t("people.col.status"), width: 190, value: (row) => chipLabel(row) },
    { id: "role", header: t("people.col.role"), width: 140, value: (row) => row.role?.name ?? "" },
    { id: "branch", header: t("people.col.branch"), width: 150, sortable: "branch", value: (row) => row.home_branch?.name ?? "" },
    { id: "on_time", header: t("people.col.onTime"), width: 150, hint: t("people.col.onTimeHint"), value: (row) => row.work.on_time_30d ?? "" },
    { id: "late_now", header: t("people.col.lateNow"), width: 112, numeric: true, value: (row) => row.work.late_now },
  ];
  if (hasAttendance.value) list.push({ id: "attendance", header: t("people.col.attendance"), width: 120, numeric: true, value: (row) => row.fields.attendance_30d ?? "" });
  if (hasSalary.value) list.push({ id: "salary", header: t("people.col.salary"), width: 150, numeric: true, value: (row) => row.fields.salary?.amount ?? "" });
  list.push({ id: "joined", header: t("people.col.joined"), width: 140, sortable: "joined", value: (row) => row.joined_on ?? "", format: (v) => (v ? fmt.day(String(v), "medium") : "—") });
  if (formerView.value) list.push({ id: "left", header: t("people.col.left"), width: 140, value: (row) => row.left_on ?? "", format: (v) => (v ? fmt.day(String(v), "medium") : "—") });
  list.push({ id: "phone", header: t("people.col.phone"), width: 150, value: (row) => formatPhone(row.phone) });
  return list;
});

const filtered = computed(() => filters.active.value > 0 || !!search.value);

function open(row: Person): void {
  void router.push(`/c/${company.currentId}/people/${row.id}`);
}

function clearAll(): void {
  filters.clear();
  search.value = "";
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader class="!mb-0" :title="t('people.team.title')" :description="t('people.team.description')">
      <template #actions>
        <UiButton v-if="addPeople" :to="addPeople" :icon="UserPlus" data-add-people>{{ t("people.team.addPeople") }}</UiButton>
        <UiButton v-if="can('members.approve')" :to="`/c/${company.currentId}/people/requests`" :icon="UserCheck" :variant="pending ? 'primary' : 'secondary'">
          {{ t("people.team.requests") }}
          <UiBadge v-if="pending" :count="pending" tone="neutral" variant="solid" />
        </UiButton>
      </template>
    </PageHeader>

    <KpiStrip :items="kpis" :loading="stats.isPending.value" :columns="4" phone="compact" />

    <div class="flex flex-col gap-3">
      <SavedViewsTabs
        v-model="viewId"
        :views="tabs"
        :dirty="dirty"
        @save="saveView"
        @update="(view) => views.update.mutate({ id: Number(view.id), state: currentState })"
        @rename="(view, name) => views.update.mutate({ id: Number(view.id), name })"
        @share="(view, shared) => views.update.mutate({ id: Number(view.id), is_shared: shared })"
        @delete="(view) => (views.remove.mutate(Number(view.id)), (viewId = 'current'))"
      />
      <DataTable
        :state="table"
        :columns="columns"
        :rows="rows"
        :total="query.data.value?.count"
        row-key="id"
        clickable
        :loading="query.isPending.value"
        :fetching="query.isFetching.value"
        :error="query.error.value"
        :retry="() => query.refetch()"
        :filtered="filtered"
        export-kind="members.people"
        :export-params="{ status, q: search || undefined }"
        csv-name="Team"
        :empty-title="t('people.team.emptyTitle')"
        :empty-description="t('people.team.emptyBody')"
        :empty-icon="Users"
        :row-class="(row) => (row.status === 'left' || row.status === 'blocked' ? 'opacity-70' : undefined)"
        @row-click="open"
        @clear-filters="clearAll"
      >
        <template #toolbar>
          <FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable :search-placeholder="t('people.team.search')" />
        </template>
        <template #cell-person="{ row }">
          <PersonCell
            :person="{ id: row.id, name: row.name, photo_url: row.photo_url }"
            :subtitle="row.position?.name ?? t('people.noPosition')"
            :status="chip(row).avatar"
            link
          />
        </template>
        <template #cell-status="{ row }">
          <StatusPill
            size="sm"
            :tone="chip(row).tone"
            :live="chip(row).live"
            :label="chipLabel(row)"
          />
        </template>
        <template #cell-role="{ row }">
          <span v-if="row.role" class="inline-flex items-center gap-1.5 text-sm text-fg">
            <ShieldCheck v-if="row.role.is_owner" :size="13" class="text-primary" aria-hidden="true" />{{ row.role.name }}
          </span>
          <span v-else class="text-subtle">—</span>
        </template>
        <template #cell-branch="{ row }">
          <span v-if="row.home_branch" class="text-sm text-fg">
            {{ row.home_branch.name }}
            <span v-if="row.branches.length > 1" class="text-xs text-subtle">+{{ row.branches.length - 1 }}</span>
          </span>
          <span v-else class="text-sm text-subtle">{{ t("people.noBranch") }}</span>
        </template>
        <template #cell-on_time="{ row }">
          <div v-if="row.work.on_time_30d !== null" class="flex min-w-0 items-center gap-2">
            <ProgressBar class="w-16" size="xs" :value="Number(row.work.on_time_30d)" :tone="rateTone(row.work.on_time_30d)" />
            <span class="text-sm tabular-nums text-fg">{{ fmt.percent(Number(row.work.on_time_30d), 1) }}</span>
          </div>
          <span v-else class="text-sm text-subtle">{{ t("people.noWork") }}</span>
        </template>
        <template #cell-late_now="{ row }">
          <span :class="['tabular-nums', row.work.late_now ? 'font-semibold text-danger' : 'text-subtle']">{{ row.work.late_now }}</span>
        </template>
        <template #cell-attendance="{ row }">
          <span class="tabular-nums">{{ row.fields.attendance_30d ? fmt.percent(Number(row.fields.attendance_30d), 1) : "—" }}</span>
        </template>
        <template #cell-salary="{ row }">
          <MoneyText v-if="row.fields.salary" :value="row.fields.salary.amount" :currency="row.fields.salary.currency" />
          <span v-else class="text-subtle">—</span>
        </template>
        <template #cell-phone="{ row }">
          <span class="flex items-center gap-1.5">
            <span class="truncate text-sm tabular-nums text-muted">{{ formatPhone(row.phone) || "—" }}</span>
            <UiTooltip v-if="row.bot_blocked" :content="t('people.botBlocked')">
              <UserRoundX :size="14" class="shrink-0 text-danger" :aria-label="t('people.botBlocked')" />
            </UiTooltip>
          </span>
        </template>
        <template #card="{ row }">
          <div class="flex items-start justify-between gap-3">
            <PersonCell
              :person="{ id: row.id, name: row.name, photo_url: row.photo_url }"
              :subtitle="[row.position?.name, row.home_branch?.name].filter(Boolean).join(' · ') || t('people.noPosition')"
              :status="chip(row).avatar"
              size="lg"
            />
            <StatusPill
              size="sm"
              :tone="chip(row).tone"
              :label="chipLabel(row)"
            />
          </div>
          <div class="mt-2.5 flex items-center gap-3 pl-[46px] text-xs text-muted">
            <span v-if="row.work.on_time_30d !== null" class="inline-flex items-center gap-1.5">
              <CircleDot :size="12" :class="RATE_TEXT[rateTone(row.work.on_time_30d)]" />{{ t("people.onTimeShort", { n: fmt.number(row.work.on_time_30d, 1) }) }}
            </span>
            <span v-if="row.work.late_now" class="font-semibold text-danger">{{ t("people.lateNow", { n: row.work.late_now }) }}</span>
            <span v-if="row.role" class="truncate">{{ row.role.name }}</span>
          </div>
        </template>
      </DataTable>
    </div>
  </div>
</template>
