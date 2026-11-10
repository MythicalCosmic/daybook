<script setup lang="ts">
/**
 * Job changes (plan §13.4 `JobChange`): new positions, branches, departments and pay from a day.
 * Proposals wait on the first tab (also in Needs you) with Approve and Reject for whoever may decide
 * them; approved ones count down to their day, then apply by themselves and show in the person's
 * history; rejected and cancelled ones stay on the last tab. The change opens on `?change=`;
 * "Propose a change" (and `?new=1` from the palette) is for hr.manage.
 */
import { CalendarClock, CircleCheck, History, Inbox, Plus, Shuffle } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import ApproveRejectButtons from "@/components/ApproveRejectButtons.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { lifecycleApi, useChangeCounts, useChanges, useLifecycleMutation } from "../api";
import ChangeDrawer from "../components/ChangeDrawer.vue";
import ChangeLines from "../components/ChangeLines.vue";
import CountdownText from "../components/CountdownText.vue";
import ProposeChangeDialog from "../components/ProposeChangeDialog.vue";
import { CHANGE_TONES, changeAccess } from "../lib";
import { CHANGE_TABS, type ChangeTab, type JobChange } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const today = useCompanyToday();
const access = computed(() => changeAccess((perm) => company.can(perm)));

const tab = useRouteState<ChangeTab>("tab", rs.enum(CHANGE_TABS, "proposed"));
const counts = useChangeCounts();
// Opened without a tab and nothing waits for approval: the changes to come are what there is to see.
const tabChosen = typeof route.query.tab === "string";
watch(
  () => counts.data.value,
  (value) => {
    if (!value || tabChosen || tab.value !== "proposed" || value.proposed) return;
    if (value.upcoming) tab.value = "upcoming";
  },
  { once: true },
);
const table = useDataTable({ id: "lifecycle.changes", url: true });
table.resetPageOn(() => [tab.value]);
const params = computed(() => ({ status: tab.value, ...table.params.value }));
const rows = useChanges(params);

const ICONS = { proposed: Inbox, upcoming: CalendarClock, applied: CircleCheck, closed: History } as const;
const tabs = computed(() =>
  CHANGE_TABS.map((value) => ({
    value,
    label: t(`lifecycle.changes.tab.${value}`),
    icon: ICONS[value],
    count: value === "proposed" || value === "upcoming" ? counts.data.value?.[value] || undefined : undefined,
  })),
);

const columns = computed<TableColumn<JobChange>[]>(() => {
  const list: TableColumn<JobChange>[] = [
    { id: "member", header: t("lifecycle.field.person"), minWidth: 220, sticky: true, hideable: false, value: (row) => row.member.name },
    { id: "what", header: t("lifecycle.changes.what"), minWidth: 300, value: (row) => row.parts.join(",") },
    { id: "effective_on", header: t("lifecycle.changes.fromLabel"), width: 170, value: (row) => row.effective_on },
  ];
  if (tab.value === "proposed") {
    list.push({ id: "proposed_by", header: t("lifecycle.changes.proposedByLabel"), width: 170, value: (row) => row.proposed_by?.name ?? "" });
    list.push({ id: "actions", header: "", width: 120, align: "end", hideable: false, value: () => "" });
  } else {
    list.push({ id: "status", header: t("lifecycle.field.status"), width: 150, value: (row) => row.status });
  }
  return list;
});

const activeKey = computed(() => (typeof route.query.change === "string" ? route.query.change : null));
function open(row: { id: number }): void {
  void router.push({ query: { ...route.query, change: String(row.id) } });
}

const approve = useLifecycleMutation((cid, id: number) => lifecycleApi.approveChange(cid, id));
const reject = useLifecycleMutation((cid, input: { id: number; reason: string }) => lifecycleApi.rejectChange(cid, input.id, input.reason));
async function runApprove(row: JobChange): Promise<void> {
  const done = await approve.mutateAsync(row.id);
  toast.success(done.status === "applied" ? t("lifecycle.changes.appliedNow", { name: row.member.name }) : t("lifecycle.changes.approved", { name: row.member.name }));
}
async function runReject(row: JobChange, reason: string): Promise<void> {
  await reject.mutateAsync({ id: row.id, reason });
  toast.success(t("lifecycle.changes.rejected", { name: row.member.name }));
}

const proposing = ref(false);
const newParam = useRouteState("new", rs.boolean(false));
watch(
  newParam,
  (value) => {
    if (!value) return;
    newParam.value = false;
    if (access.value.propose) proposing.value = true;
  },
  { immediate: true },
);
const EMPTY_ICONS = { proposed: Inbox, upcoming: CalendarClock, applied: Shuffle, closed: History } as const;
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader :title="t('lifecycle.nav.changes')" :description="t('lifecycle.changes.description')">
      <template v-if="access.propose" #actions>
        <UiButton variant="primary" :icon="Plus" @click="proposing = true">{{ t("lifecycle.changes.propose") }}</UiButton>
      </template>
    </PageHeader>

    <div class="no-scrollbar max-w-full self-start overflow-x-auto">
      <SegmentedControl v-model="tab" :options="tabs" :aria-label="t('lifecycle.nav.changes')" />
    </div>

    <DataTable
      :state="table"
      :columns="columns"
      :rows="rows.data.value?.results"
      :total="rows.data.value?.count"
      row-key="id"
      :loading="rows.isPending.value"
      :fetching="rows.isFetching.value"
      :error="rows.error.value"
      :retry="() => rows.refetch()"
      clickable
      hide-toolbar
      :active-key="activeKey"
      @row-click="open"
    >
      <template #empty>
        <EmptyState :icon="EMPTY_ICONS[tab]" :tone="tab === 'proposed' ? 'success' : 'neutral'" :title="t(`lifecycle.changes.empty.${tab}`)" :description="t(`lifecycle.changes.emptyBody.${tab}`)">
          <UiButton v-if="tab === 'proposed' && access.propose" :icon="Plus" @click="proposing = true">{{ t("lifecycle.changes.propose") }}</UiButton>
        </EmptyState>
      </template>
      <template #cell-member="{ row }">
        <div class="flex min-w-0 items-center gap-2.5">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="30" />
          <div class="min-w-0">
            <p class="truncate text-base font-medium text-fg" :title="row.member.name">{{ row.member.name }}</p>
            <p class="truncate text-xs text-muted">{{ [row.position_now, row.home_branch?.name].filter(Boolean).join(" · ") }}</p>
          </div>
        </div>
      </template>
      <template #cell-what="{ row }">
        <ChangeLines :change="row" dense />
      </template>
      <template #cell-effective_on="{ row }">
        <div class="flex min-w-0 flex-col">
          <span class="text-sm font-medium tabular-nums text-fg">{{ fmt.day(row.effective_on, "medium") }}</span>
          <CountdownText v-if="row.status === 'approved' || row.status === 'proposed'" :day="row.effective_on" :today="today" class="text-xs text-muted" />
        </div>
      </template>
      <template #cell-proposed_by="{ row }">
        <div class="flex min-w-0 flex-col">
          <span class="truncate text-sm text-fg">{{ row.proposed_by?.name ?? "—" }}</span>
          <RelativeTime class="text-xs text-subtle" :value="row.created_at" />
        </div>
      </template>
      <template #cell-status="{ row }">
        <div class="flex min-w-0 flex-col items-start gap-0.5">
          <StatusPill size="sm" variant="outline" :tone="row.error ? 'danger' : CHANGE_TONES[row.status]" :label="row.error ? t('lifecycle.changes.notApplied') : t(`lifecycle.changeStatus.${row.status}`)" />
        </div>
      </template>
      <template #cell-actions="{ row }">
        <div @click.stop>
          <ApproveRejectButtons
            v-if="row.can.decide"
            compact
            :on-approve="() => runApprove(row)"
            :on-reject="(reason: string) => runReject(row, reason)"
            :reject-title="t('lifecycle.changes.rejectTitle')"
          />
        </div>
      </template>
      <template #card="{ row }">
        <div class="flex flex-col gap-2.5">
          <div class="flex items-start gap-3">
            <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="38" />
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <p class="min-w-0 flex-1 truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
                <StatusPill size="sm" variant="outline" :tone="CHANGE_TONES[row.status]" :label="t(`lifecycle.changeStatus.${row.status}`)" />
              </div>
              <p class="text-sm tabular-nums text-muted">{{ t("lifecycle.changes.from", { date: fmt.day(row.effective_on, "medium") }) }}</p>
            </div>
          </div>
          <ChangeLines :change="row" dense />
          <div v-if="row.can.decide" @click.stop>
            <ApproveRejectButtons :on-approve="() => runApprove(row)" :on-reject="(reason: string) => runReject(row, reason)" :reject-title="t('lifecycle.changes.rejectTitle')" />
          </div>
        </div>
      </template>
    </DataTable>

    <ChangeDrawer />
    <ProposeChangeDialog v-model:open="proposing" @saved="open" />
  </div>
</template>
