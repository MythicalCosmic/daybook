<script setup lang="ts">
/**
 * Leaving (plan §13.4 "How a termination runs"): requests to leave someone sent from the app wait
 * on the first tab with Agree and Decline; agreed last days count down with their handover list;
 * people who left keep their final payslip and what they handed over; withdrawn and declined
 * requests stay on the last tab. The leaving opens on `?termination=`; "Start a leaving" (and
 * `?new=1` from the palette) is for hr.terminate.
 */
import { CalendarClock, CircleCheck, DoorOpen, History, Inbox, LogOut, Plus, UserRoundMinus } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { lifecycleApi, useLeavingCounts, useLeavings, useLifecycleMutation } from "../api";
import AgreeDialog from "../components/AgreeDialog.vue";
import CountdownText from "../components/CountdownText.vue";
import LeavingDrawer from "../components/LeavingDrawer.vue";
import StartLeavingDialog from "../components/StartLeavingDialog.vue";
import { handoverPercent, LEAVING_KIND_TONES, LEAVING_TONES, leavingAccess, shortNotice } from "../lib";
import { LEAVING_TABS, type Leaving, type LeavingRow, type LeavingTab } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const today = useCompanyToday();
const confirm = useConfirm();
const access = computed(() => leavingAccess((perm) => company.can(perm)));

const tab = useRouteState<LeavingTab>("tab", rs.enum(LEAVING_TABS, "requested"));
const counts = useLeavingCounts();
// Opened without a tab and no request waits: the people leaving are what there is to see.
const tabChosen = typeof route.query.tab === "string";
watch(
  () => counts.data.value,
  (value) => {
    if (!value || tabChosen || tab.value !== "requested" || value.requested) return;
    if (value.agreed) tab.value = "agreed";
  },
  { once: true },
);
const table = useDataTable({ id: "lifecycle.leaving", url: true });
table.resetPageOn(() => [tab.value]);
const params = computed(() => ({ status: tab.value, ...table.params.value }));
const rows = useLeavings(params);
const skeleton = useDelayedPending(computed(() => rows.isPending.value));

const ICONS = { requested: Inbox, agreed: CalendarClock, completed: LogOut, closed: History } as const;
const tabs = computed(() =>
  LEAVING_TABS.map((value) => ({
    value,
    label: t(`lifecycle.leaving.tab.${value}`),
    icon: ICONS[value],
    count: value === "requested" || value === "agreed" ? counts.data.value?.[value] || undefined : undefined,
  })),
);

const columns = computed<TableColumn<LeavingRow>[]>(() => {
  const person: TableColumn<LeavingRow> = { id: "member", header: t("lifecycle.field.person"), minWidth: 220, sticky: true, hideable: false, value: (row) => row.member.name };
  const kind: TableColumn<LeavingRow> = { id: "kind", header: t("lifecycle.leaving.kind"), width: 170, value: (row) => t(`lifecycle.leavingKind.${row.kind}`) };
  if (tab.value === "completed") {
    return [
      person,
      kind,
      { id: "left_on", header: t("lifecycle.leaving.leftOnLabel"), width: 160, value: (row) => row.left_on ?? "" },
      { id: "handover", header: t("lifecycle.handover.title"), width: 190, value: (row) => row.handover.done },
    ];
  }
  if (tab.value === "closed") {
    return [
      person,
      kind,
      { id: "status", header: t("lifecycle.field.status"), width: 150, value: (row) => row.status },
      { id: "asked", header: t("lifecycle.leaving.askedFor"), width: 160, value: (row) => row.wished_last_day ?? "" },
    ];
  }
  return [
    person,
    kind,
    { id: "last_day", header: t("lifecycle.leaving.lastDay"), width: 210, value: (row) => row.last_day ?? "" },
    { id: "handover", header: t("lifecycle.handover.title"), width: 190, value: (row) => row.handover.done },
    { id: "notice", header: t("lifecycle.leaving.noticeLabel"), width: 184, numeric: true, value: (row) => row.notice_days ?? 0 },
  ];
});

const activeKey = computed(() => (typeof route.query.termination === "string" ? route.query.termination : null));
function open(row: { id: number }): void {
  void router.push({ query: { ...route.query, termination: String(row.id) } });
}

// Answering a request from its card: agree (the dialog, with the day they asked for) or decline.
const agreeing = ref<LeavingRow | null>(null);
const decline = useLifecycleMutation((cid, input: { id: number; reason: string }) => lifecycleApi.declineLeaving(cid, input.id, input.reason));
async function runDecline(row: LeavingRow): Promise<void> {
  const answer = await confirm({
    title: t("lifecycle.leaving.declineTitle"),
    message: t("lifecycle.leaving.declineBody", { name: row.member.name }),
    tone: "danger",
    reason: "required",
    reasonLabel: t("lifecycle.leaving.declineReason"),
    confirmLabel: t("lifecycle.leaving.decline"),
    icon: UserRoundMinus,
    onConfirm: (reason) => decline.mutateAsync({ id: row.id, reason }),
  });
  if (answer) toast.success(t("lifecycle.leaving.declined"));
}
function agreed(leaving: Leaving): void {
  open(leaving);
}

const starting = ref(false);
const newParam = useRouteState("new", rs.boolean(false));
watch(
  newParam,
  (value) => {
    if (!value) return;
    newParam.value = false;
    if (access.value.manage) starting.value = true;
  },
  { immediate: true },
);

const EMPTY_ICONS = { requested: Inbox, agreed: DoorOpen, completed: LogOut, closed: History } as const;
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader :title="t('lifecycle.nav.terminations')" :description="t('lifecycle.leaving.description')">
      <template v-if="access.manage" #actions>
        <UiButton variant="primary" :icon="Plus" @click="starting = true">{{ t("lifecycle.leaving.start") }}</UiButton>
      </template>
    </PageHeader>

    <div class="no-scrollbar max-w-full self-start overflow-x-auto">
      <SegmentedControl v-model="tab" :options="tabs" :aria-label="t('lifecycle.nav.terminations')" />
    </div>

    <!-- Requests: a card each, answered where they are -->
    <template v-if="tab === 'requested'">
      <div v-if="skeleton" class="flex flex-col gap-3">
        <SkeletonBlock v-for="n in 2" :key="n" height="132px" radius="14px" />
      </div>
      <ErrorState v-else-if="rows.isError.value" class="ui-card" :error="rows.error.value" :retry="() => rows.refetch()" />
      <div v-else-if="!rows.data.value?.results.length" class="ui-card">
        <EmptyState :icon="EMPTY_ICONS.requested" tone="success" :title="t('lifecycle.leaving.empty.requested')" :description="t('lifecycle.leaving.emptyBody.requested')" />
      </div>
      <TransitionGroup v-else tag="ul" name="lc-list" class="flex flex-col gap-3">
        <li
          v-for="row in rows.data.value!.results"
          :key="row.id"
          class="ui-card group flex cursor-pointer flex-col gap-4 p-4 transition-shadow hover:shadow-[var(--shadow-2)] sm:flex-row sm:items-center"
          data-leaving-request
          @click="open(row)"
        >
          <div class="flex min-w-0 flex-1 items-start gap-3">
            <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="44" />
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <p class="truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
                <StatusPill size="sm" :tone="LEAVING_TONES.requested" :label="t('lifecycle.leavingStatus.requested')" />
              </div>
              <p class="truncate text-sm text-muted">
                {{ [row.position, row.home_branch?.name].filter(Boolean).join(" · ") }}
              </p>
              <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
                <span class="inline-flex items-center gap-1.5 font-medium text-fg">
                  <CalendarClock :size="15" class="text-primary" aria-hidden="true" />
                  {{ t("lifecycle.leaving.askedDay", { date: fmt.day(row.wished_last_day!, "weekday") }) }}
                </span>
                <CountdownText :day="row.wished_last_day" :today="today" class="text-muted" />
                <StatusPill
                  v-if="row.notice_days !== null"
                  size="sm"
                  variant="outline"
                  :tone="shortNotice(row.notice_days) ? 'warning' : 'neutral'"
                  :label="t('lifecycle.leaving.notice', { n: row.notice_days }, row.notice_days)"
                />
              </div>
              <p class="mt-1.5 text-xs text-subtle">{{ t("lifecycle.leaving.byEmployee") }} · <RelativeTime :value="row.requested_at" /></p>
            </div>
          </div>
          <div v-if="access.manage && row.can_manage" class="flex shrink-0 items-center gap-2" @click.stop>
            <UiButton size="sm" variant="ghost" @click="runDecline(row)">{{ t("lifecycle.leaving.decline") }}</UiButton>
            <UiButton size="sm" variant="primary" :icon="CircleCheck" @click="agreeing = row">{{ t("lifecycle.leaving.agreeDay") }}</UiButton>
          </div>
        </li>
      </TransitionGroup>
    </template>

    <!-- Agreed, left, closed: a table -->
    <DataTable
      v-else
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
        <EmptyState :icon="EMPTY_ICONS[tab]" tone="neutral" :title="t(`lifecycle.leaving.empty.${tab}`)" :description="t(`lifecycle.leaving.emptyBody.${tab}`)" />
      </template>
      <template #cell-member="{ row }">
        <div class="flex min-w-0 items-center gap-2.5">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="30" />
          <div class="min-w-0">
            <p class="truncate text-base font-medium text-fg" :title="row.member.name">{{ row.member.name }}</p>
            <p class="truncate text-xs text-muted">{{ [row.position, row.home_branch?.name].filter(Boolean).join(" · ") }}</p>
          </div>
        </div>
      </template>
      <template #cell-kind="{ row }">
        <StatusPill size="sm" variant="outline" :tone="LEAVING_KIND_TONES[row.kind]" :label="t(`lifecycle.leavingKind.${row.kind}`)" />
      </template>
      <template #cell-last_day="{ row }">
        <div class="flex min-w-0 flex-col">
          <span class="text-sm font-medium tabular-nums text-fg">{{ row.last_day ? fmt.day(row.last_day, "weekday") : "—" }}</span>
          <span v-if="row.error" class="text-xs font-medium text-danger">{{ t("lifecycle.leaving.errorShort") }}</span>
          <CountdownText v-else :day="row.last_day" :today="today" class="text-xs text-muted" />
        </div>
      </template>
      <template #cell-left_on="{ row }">
        <span class="text-sm tabular-nums text-fg">{{ row.left_on ? fmt.day(row.left_on, "medium") : "—" }}</span>
      </template>
      <template #cell-handover="{ row }">
        <div v-if="row.handover.total" class="flex w-full max-w-[170px] flex-col gap-1">
          <ProgressBar :value="row.handover.done" :max="row.handover.total" size="xs" :tone="row.handover.done === row.handover.total ? 'success' : 'primary'" />
          <span class="text-xs tabular-nums text-muted">{{ t("lifecycle.handover.progress", { done: row.handover.done, total: row.handover.total }) }}</span>
        </div>
        <span v-else class="text-sm text-subtle">—</span>
      </template>
      <template #cell-notice="{ row }">
        <span :class="['text-sm tabular-nums', shortNotice(row.notice_days) ? 'font-medium text-warning' : 'text-muted']">
          {{ row.notice_days !== null ? t("lifecycle.leaving.noticeDays", { n: row.notice_days }, row.notice_days) : "—" }}
        </span>
      </template>
      <template #cell-status="{ row }">
        <StatusPill size="sm" variant="outline" :tone="LEAVING_TONES[row.status]" :label="t(`lifecycle.leavingStatus.${row.status}`)" />
      </template>
      <template #cell-asked="{ row }">
        <span class="text-sm tabular-nums text-muted">{{ row.wished_last_day ? fmt.day(row.wished_last_day, "medium") : "—" }}</span>
      </template>
      <template #card="{ row }">
        <div class="flex items-start gap-3">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="38" />
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <p class="min-w-0 flex-1 truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
              <StatusPill size="sm" variant="outline" :tone="LEAVING_TONES[row.status]" :label="t(`lifecycle.leavingStatus.${row.status}`)" />
            </div>
            <p class="truncate text-sm text-muted">{{ t(`lifecycle.leavingKind.${row.kind}`) }}</p>
            <p class="mt-1 text-sm tabular-nums text-fg">
              <template v-if="row.status === 'completed' && row.left_on">{{ t("lifecycle.leaving.leftOn", { date: fmt.day(row.left_on, "medium") }) }}</template>
              <template v-else-if="row.last_day">{{ fmt.day(row.last_day, "weekday") }} · <CountdownText :day="row.last_day" :today="today" /></template>
              <template v-else-if="row.wished_last_day">{{ t("lifecycle.leaving.askedDay", { date: fmt.day(row.wished_last_day, "medium") }) }}</template>
            </p>
            <div v-if="row.handover.total && row.status !== 'withdrawn' && row.status !== 'declined'" class="mt-2 flex items-center gap-2">
              <ProgressBar class="flex-1" :value="row.handover.done" :max="row.handover.total" size="xs" :tone="handoverPercent(row.handover) === 100 ? 'success' : 'primary'" />
              <span class="shrink-0 text-xs tabular-nums text-muted">{{ row.handover.done }}/{{ row.handover.total }}</span>
            </div>
          </div>
        </div>
      </template>
    </DataTable>

    <LeavingDrawer />
    <StartLeavingDialog v-model:open="starting" @saved="open" />
    <AgreeDialog v-if="agreeing" :leaving="agreeing" :open="!!agreeing" @update:open="(value) => !value && (agreeing = null)" @saved="agreed" />
  </div>
</template>

<style scoped>
.lc-list-move,
.lc-list-leave-active {
  transition: all 220ms var(--ease-out, ease);
}
.lc-list-leave-to {
  opacity: 0;
  transform: translateX(12px);
}
.lc-list-leave-active {
  position: absolute;
  width: 100%;
}
</style>
