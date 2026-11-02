<script setup lang="ts">
/**
 * Suspensions (plan §13.4): who is suspended now, since when, until when (or until reinstated) and
 * why; "Suspend someone" and "Reinstate" for hr.suspend, each asking first. The server says why
 * when it refuses (the last owner can't be suspended). `?new=1` opens the dialog from the palette.
 */
import { CalendarClock, Pause, Play } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
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
import { lifecycleAccess } from "../lib";
import type { Suspension } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();
const confirm = useConfirm();
const access = computed(() => lifecycleAccess((perm) => company.can(perm)));

const table = useDataTable({ id: "lifecycle.suspensions" });
const suspensions = useSuspensions();

const columns = computed<TableColumn<Suspension>[]>(() => [
  { id: "member", header: t("lifecycle.field.person"), minWidth: 200, sticky: true, hideable: false, value: (row) => row.member.name },
  { id: "period", header: t("lifecycle.suspensions.period"), width: 270, value: (row) => row.until ?? "" },
  { id: "reason", header: t("lifecycle.suspend.reason"), minWidth: 220, value: (row) => row.reason },
  { id: "by", header: t("lifecycle.suspensions.by"), width: 150, value: (row) => row.by ?? "" },
  { id: "actions", header: "", width: 150, align: "end", hideable: false, value: () => "" },
]);

function untilText(row: Suspension): string {
  return row.until ? t("lifecycle.suspensions.until", { date: fmt.day(row.until, "medium") }) : t("lifecycle.suspensions.untilReinstated");
}
/** Days of the suspension still ahead, today included. */
function left(row: Suspension): number | null {
  return row.until ? Math.max(0, diffDays(today.value, row.until) + 1) : null;
}

const reinstate = useLifecycleMutation((cid, memberId: number) => lifecycleApi.reinstate(cid, memberId));
async function runReinstate(row: Suspension): Promise<void> {
  const answer = await confirm({
    title: t("lifecycle.reinstate.title", { name: row.member.name }),
    message: t("lifecycle.reinstate.body"),
    confirmLabel: t("lifecycle.reinstate.confirm"),
    icon: Play,
    onConfirm: () => reinstate.mutateAsync(row.member.id),
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
    <PageHeader :title="t('lifecycle.nav.suspensions')" :description="t('lifecycle.suspensions.description')">
      <template v-if="access.suspend" #actions>
        <UiButton variant="primary" :icon="Pause" @click="suspending = true">{{ t("lifecycle.suspend.button") }}</UiButton>
      </template>
    </PageHeader>

    <DataTable
      :state="table"
      :columns="columns"
      :rows="suspensions.data.value"
      :row-key="(row) => row.member.id"
      :loading="suspensions.isPending.value"
      :fetching="suspensions.isFetching.value"
      :error="suspensions.error.value"
      :retry="() => suspensions.refetch()"
      hide-pagination
      hide-toolbar
    >
      <template #empty>
        <EmptyState :icon="Play" tone="success" :title="t('lifecycle.suspensions.emptyNow')" :description="t('lifecycle.suspensions.emptyNowBody')" />
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
          <span class="text-sm tabular-nums text-fg">{{ untilText(row) }}</span>
          <span class="text-xs text-muted">
            <template v-if="row.since">{{ t("lifecycle.suspensions.since", { date: fmt.day(row.since.slice(0, 10), "medium") }) }}</template>
            <template v-if="left(row) !== null"> · {{ t("lifecycle.suspensions.daysLeft", { n: left(row) }, left(row)!) }}</template>
          </span>
        </div>
      </template>
      <template #cell-reason="{ row }"><span class="line-clamp-2 text-sm text-fg" :title="row.reason">{{ row.reason }}</span></template>
      <template #cell-by="{ row }"><span class="truncate text-sm text-muted">{{ row.by ?? "—" }}</span></template>
      <template #cell-actions="{ row }">
        <UiButton v-if="row.can_reinstate" size="sm" :icon="Play" @click.stop="runReinstate(row)">{{ t("lifecycle.reinstate.confirm") }}</UiButton>
      </template>
      <template #card="{ row }">
        <div class="flex flex-col gap-2.5">
          <div class="flex items-start gap-3">
            <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="36" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
              <p class="flex items-center gap-1.5 text-xs text-muted"><CalendarClock :size="13" aria-hidden="true" />{{ untilText(row) }}</p>
            </div>
          </div>
          <p class="line-clamp-3 rounded-[10px] bg-surface-2 px-3 py-2 text-sm text-fg">{{ row.reason }}</p>
          <UiButton v-if="row.can_reinstate" block class="h-10" :icon="Play" @click.stop="runReinstate(row)">{{ t("lifecycle.reinstate.confirm") }}</UiButton>
        </div>
      </template>
    </DataTable>

    <SuspendDialog v-model:open="suspending" />
  </div>
</template>
