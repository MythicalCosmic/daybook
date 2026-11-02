<script setup lang="ts">
/**
 * Suspensions (plan §13.4): who is suspended, since when, until when (or until reinstated) and why;
 * "Suspend someone" and "Reinstate" for hr.suspend, each asking first. History keeps the ended ones.
 * The server says why when it refuses (the last owner can't be suspended).
 */
import { CalendarClock, History, Pause, Play } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import FilterBar from "@/components/FilterBar.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { diffDays } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { lifecycleApi, useLifecycleMutation, useSuspensions } from "../api";
import SuspendDialog from "../components/SuspendDialog.vue";
import { lifecycleAccess, SUSPENSION_TONES, suspensionParams, type SuspensionView } from "../lib";
import type { Suspension } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();
const confirm = useConfirm();
const access = computed(() => lifecycleAccess((perm) => company.can(perm)));

const view = useRouteState<SuspensionView>("view", rs.enum(["now", "history"] as const, "now"));
const search = useRouteState("q", rs.string(""));
const table = useDataTable({ id: "lifecycle.suspensions", url: true });
table.resetPageOn(() => [view.value, search.value]);
const params = computed(() => ({ ...suspensionParams(view.value, search.value), ...table.params.value }));
const suspensions = useSuspensions(params);
const filters = ref({});

const tabs = computed(() => [
  { id: "now", label: t("lifecycle.suspensions.now"), icon: Pause },
  { id: "history", label: t("lifecycle.suspensions.history"), icon: History },
]);

const columns = computed<TableColumn<Suspension>[]>(() => [
  { id: "member", header: t("lifecycle.field.person"), minWidth: 200, sticky: true, hideable: false, value: (row) => row.member.name },
  { id: "period", header: t("lifecycle.suspensions.period"), width: 230, value: (row) => row.starts_on },
  { id: "reason", header: t("lifecycle.suspend.reason"), minWidth: 220, value: (row) => row.reason },
  { id: "by", header: t("lifecycle.suspensions.by"), width: 160, value: (row) => row.created_by ?? "" },
  { id: "actions", header: "", width: 150, align: "end", hideable: false, value: () => "" },
]);

function until(row: Suspension): string {
  return row.ends_on ? t("lifecycle.suspensions.until", { date: fmt.day(row.ends_on, "medium") }) : t("lifecycle.suspensions.untilReinstated");
}
function left(row: Suspension): number | null {
  return row.ends_on && row.status === "active" ? diffDays(today.value, row.ends_on) + 1 : null;
}

const reinstate = useLifecycleMutation((cid, id: number) => lifecycleApi.reinstate(cid, id));
async function runReinstate(row: Suspension): Promise<void> {
  const answer = await confirm({
    title: t("lifecycle.reinstate.title", { name: row.member.name }),
    message: t("lifecycle.reinstate.body"),
    confirmLabel: t("lifecycle.reinstate.confirm"),
    icon: Play,
    onConfirm: () => reinstate.mutateAsync(row.id),
  });
  if (answer) toast.success(t("lifecycle.reinstate.done", { name: row.member.name }));
}

const suspending = ref(false);
const newParam = useRouteState("new", rs.boolean(false));
watch(
  newParam,
  (value) => {
    if (!value) return;
    newParam.value = false;
    if (access.value.suspend) suspending.value = true;
  },
  { immediate: true },
);
</script>

<template>
  <div>
    <PageHeader v-model:tab="view" :title="t('lifecycle.nav.suspensions')" :description="t('lifecycle.suspensions.description')" :tabs="tabs">
      <template v-if="access.suspend" #actions>
        <UiButton variant="primary" :icon="Pause" @click="suspending = true">{{ t("lifecycle.suspend.button") }}</UiButton>
      </template>
    </PageHeader>

    <DataTable
      :state="table"
      :columns="columns"
      :rows="suspensions.data.value?.results"
      :total="suspensions.data.value?.count"
      row-key="id"
      :loading="suspensions.isPending.value"
      :fetching="suspensions.isFetching.value"
      :error="suspensions.error.value"
      :retry="() => suspensions.refetch()"
      :filtered="!!search"
      @clear-filters="search = ''"
    >
      <template #toolbar>
        <FilterBar v-model="filters" v-model:search="search" :defs="[]" searchable :search-placeholder="t('lifecycle.suspensions.search')" />
      </template>
      <template #empty>
        <EmptyState
          :icon="view === 'now' ? Play : History"
          :tone="view === 'now' && !search ? 'success' : 'neutral'"
          :title="search ? t('lifecycle.empty.noMatch') : view === 'now' ? t('lifecycle.suspensions.emptyNow') : t('lifecycle.suspensions.emptyHistory')"
          :description="search ? t('lifecycle.empty.noMatchBody') : view === 'now' ? t('lifecycle.suspensions.emptyNowBody') : t('lifecycle.suspensions.emptyHistoryBody')"
        />
      </template>
      <template #cell-member="{ row }">
        <RouterLink :to="`/c/${company.currentId}/people/${row.member.id}`" class="flex min-w-0 items-center gap-2.5 hover:text-primary">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="28" />
          <div class="min-w-0">
            <p class="truncate text-base font-medium text-fg" :title="row.member.name">{{ row.member.name }}</p>
            <p v-if="row.position" class="truncate text-xs text-muted">{{ row.position }}</p>
          </div>
        </RouterLink>
      </template>
      <template #cell-period="{ row }">
        <div class="flex min-w-0 flex-col items-start gap-0.5">
          <span class="text-sm tabular-nums text-fg">{{ t("lifecycle.suspensions.since", { date: fmt.day(row.starts_on, "medium") }) }}</span>
          <span class="text-xs text-muted">{{ until(row) }}<template v-if="left(row) !== null"> · {{ t("lifecycle.suspensions.daysLeft", { n: left(row) }, left(row)!) }}</template></span>
        </div>
      </template>
      <template #cell-reason="{ row }"><span class="line-clamp-2 text-sm text-fg" :title="row.reason">{{ row.reason }}</span></template>
      <template #cell-by="{ row }"><span class="truncate text-sm text-muted">{{ row.created_by ?? "—" }}</span></template>
      <template #cell-actions="{ row }">
        <UiButton v-if="access.suspend && (row.status === 'active' || row.status === 'scheduled')" size="sm" :icon="Play" @click.stop="runReinstate(row)">{{ t("lifecycle.reinstate.confirm") }}</UiButton>
        <StatusPill v-else :tone="SUSPENSION_TONES[row.status]" size="sm" :label="t(`lifecycle.suspensionStatus.${row.status}`)" />
      </template>
      <template #card="{ row }">
        <div class="flex flex-col gap-2.5">
          <div class="flex items-start gap-3">
            <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="36" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
              <p class="flex items-center gap-1.5 text-xs text-muted"><CalendarClock :size="13" aria-hidden="true" />{{ t("lifecycle.suspensions.since", { date: fmt.day(row.starts_on, "short") }) }} · {{ until(row) }}</p>
            </div>
            <StatusPill :tone="SUSPENSION_TONES[row.status]" size="sm" :label="t(`lifecycle.suspensionStatus.${row.status}`)" />
          </div>
          <p class="line-clamp-3 rounded-[10px] bg-surface-2 px-3 py-2 text-sm text-fg">{{ row.reason }}</p>
          <UiButton v-if="access.suspend && (row.status === 'active' || row.status === 'scheduled')" block class="h-10" :icon="Play" @click.stop="runReinstate(row)">{{ t("lifecycle.reinstate.confirm") }}</UiButton>
        </div>
      </template>
    </DataTable>

    <SuspendDialog v-model:open="suspending" />
  </div>
</template>
