<script setup lang="ts">
/**
 * Team › Locations: every branch, office or site from one screen, each as a card: its address and
 * hours, how many people work there, who is in the building now out of those expected today, and
 * its Face ID terminals with their status. Add, change, close and reopen a location here (with
 * `company.settings`).
 */
import { Clock3, MapPin, MoreHorizontal, Pencil, Plus, RotateCcw, ScanFace, Store, Users, XCircle } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCan } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";

import { activateBranch, deactivateBranch, useBranches, useRefresh } from "../api";
import { useBoard, useTerminalStatus } from "../components/overview/overviewApi";
import BranchDialog from "../components/team/BranchDialog.vue";
import { useTeamTabs } from "../components/team/tabs";
import { DEVICE_DOTS } from "../components/team/team";
import { branchesOf } from "../components/team/teamApi";
import type { Branch } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const tabs = useTeamTabs();
const confirm = useConfirm();
const refresh = useRefresh();
const canEdit = useCan("company.settings");
const canSeeToday = useCan("attendance.view");

const branches = useBranches();
const board = useBoard(() => []);
const terminals = useTerminalStatus();
const skeleton = useDelayedPending(computed(() => branches.isPending.value));

const ordered = computed(() => [...(branches.data.value ?? [])].sort((a, b) => a.order - b.order || a.name.localeCompare(b.name)));
const open = computed(() => ordered.value.filter((b) => b.is_active));
const closed = computed(() => ordered.value.filter((b) => !b.is_active));
const today = computed(() => new Map(branchesOf(board.data.value).map((row) => [row.id, row])));
const devices = computed(() => {
  const map = new Map<number, NonNullable<typeof terminals.data.value>["devices"]>();
  for (const device of terminals.data.value?.devices ?? []) map.set(device.branch.id, [...(map.get(device.branch.id) ?? []), device]);
  return map;
});

const dialog = ref(false);
const editing = ref<Branch | null>(null);

function add(): void {
  editing.value = null;
  dialog.value = true;
}

function edit(branch: Branch): void {
  editing.value = branch;
  dialog.value = true;
}

async function close(branch: Branch): Promise<void> {
  const answer = await confirm({ title: t("davomat.branches.closeTitle", { name: branch.name }), message: t("davomat.branches.closeBody"), confirmLabel: t("davomat.branches.close"), tone: "danger", icon: XCircle });
  if (!answer) return;
  await deactivateBranch(company.currentId ?? 0, branch.id);
  toast.success(t("davomat.branches.closed", { name: branch.name }));
  refresh();
}

async function reopen(branch: Branch): Promise<void> {
  await activateBranch(company.currentId ?? 0, branch.id);
  toast.success(t("davomat.branches.reopened", { name: branch.name }));
  refresh();
}

function menu(branch: Branch): MenuEntry[] {
  return [
    { label: t("common.edit"), icon: Pencil, onSelect: () => edit(branch) },
    { type: "separator" },
    { label: t("davomat.branches.close"), icon: XCircle, danger: true, onSelect: () => void close(branch) },
  ];
}

function hours(branch: Branch): string {
  if (branch.open_24h) return t("davomat.branches.allDay");
  if (branch.opens_at && branch.closes_at) return `${branch.opens_at.slice(0, 5)}–${branch.closes_at.slice(0, 5)}`;
  return "";
}

function share(branchId: number): number {
  const row = today.value.get(branchId);
  return row && row.rostered > 0 ? Math.min(100, Math.round((row.checked_in / row.rostered) * 100)) : 0;
}
</script>

<template>
  <div>
    <PageHeader :title="t('davomat.nav.team')" :description="t('davomat.branches.description')" :tabs="tabs">
      <template v-if="canEdit" #actions>
        <UiButton variant="primary" :icon="Plus" data-add-branch @click="add">{{ t("davomat.branches.add") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="skeleton" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-hidden="true">
      <SkeletonBlock v-for="n in 3" :key="n" height="220px" radius="12px" />
    </div>
    <ErrorState v-else-if="branches.isError.value" class="ui-card" :error="branches.error.value" :retry="() => branches.refetch()" />
    <div v-else-if="branches.data.value && !open.length && !closed.length" class="ui-card">
      <EmptyState :icon="Store" :title="t('davomat.branches.empty.title')" :description="t('davomat.branches.empty.body')">
        <UiButton v-if="canEdit" variant="primary" :icon="Plus" @click="add">{{ t("davomat.branches.add") }}</UiButton>
      </EmptyState>
    </div>

    <template v-else>
      <ul class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <li v-for="branch in open" :key="branch.id" class="ui-card flex flex-col overflow-hidden transition-shadow duration-200 hover:shadow-[var(--sh-raised)]" :data-branch="branch.id">
          <div class="flex items-start gap-3 p-4 pb-3">
            <span class="grid size-10 shrink-0 place-items-center rounded-[12px] bg-accent-soft text-accent-fg"><MapPin :size="18" aria-hidden="true" /></span>
            <div class="min-w-0 flex-1">
              <p class="flex items-center gap-2">
                <span class="truncate text-md font-semibold text-fg">{{ branch.name }}</span>
                <span v-if="branch.code" class="ui-chip shrink-0 font-mono uppercase">{{ branch.code }}</span>
              </p>
              <p class="truncate text-sm text-muted">{{ branch.address || t("davomat.branches.noAddress") }}</p>
              <p v-if="hours(branch)" class="mt-0.5 flex items-center gap-1 text-xs tabular-nums text-subtle"><Clock3 :size="12" aria-hidden="true" />{{ hours(branch) }}</p>
            </div>
            <DropdownMenu v-if="canEdit" :items="menu(branch)" width="200px">
              <template #trigger>
                <IconButton :icon="MoreHorizontal" :label="t('common.more')" size="sm" />
              </template>
            </DropdownMenu>
          </div>

          <dl class="grid grid-cols-2 gap-px border-y border-line bg-line">
            <RouterLink :to="`/c/${company.currentId}/team?branch=${branch.id}`" class="group flex flex-col gap-0.5 bg-surface px-4 py-3 hover:bg-surface-2/60">
              <dt class="flex items-center gap-1.5 text-xs font-medium text-muted"><Users :size="12" aria-hidden="true" />{{ t("davomat.branches.people") }}</dt>
              <dd class="text-xl font-semibold leading-7 tabular-nums text-fg group-hover:text-primary">{{ fmt.number(branch.people) }}</dd>
            </RouterLink>
            <div class="flex flex-col gap-0.5 bg-surface px-4 py-3">
              <dt class="text-xs font-medium text-muted">{{ t("davomat.branches.inNow") }}</dt>
              <dd v-if="canSeeToday && today.get(branch.id)" class="flex items-baseline gap-1">
                <span class="text-xl font-semibold leading-7 tabular-nums text-fg">{{ fmt.number(today.get(branch.id)!.checked_in) }}</span>
                <span class="text-sm tabular-nums text-muted">/ {{ fmt.number(today.get(branch.id)!.rostered) }}</span>
              </dd>
              <dd v-else class="text-xl font-semibold leading-7 text-subtle">—</dd>
              <dd v-if="canSeeToday && today.get(branch.id)?.rostered" class="mt-1 h-1 overflow-hidden rounded-full bg-surface-3" aria-hidden="true">
                <span class="block h-full rounded-full bg-success transition-[width] duration-500 ease-out" :style="{ width: `${share(branch.id)}%` }" />
              </dd>
            </div>
          </dl>

          <div class="flex flex-1 flex-col gap-1.5 px-4 py-3">
            <p class="flex items-center gap-1.5 text-xs font-medium text-muted"><ScanFace :size="12" aria-hidden="true" />{{ t("davomat.branches.terminals") }}</p>
            <ul v-if="devices.get(branch.id)?.length" class="flex flex-col gap-1">
              <li v-for="device in devices.get(branch.id)" :key="device.id" class="flex items-center gap-2 text-sm">
                <span class="size-2 shrink-0 rounded-full" :class="device.status === 'online' && 'live-dot'" :style="{ background: DEVICE_DOTS[device.status], color: DEVICE_DOTS[device.status] }" aria-hidden="true" />
                <span class="min-w-0 flex-1 truncate text-fg">{{ device.name }}</span>
                <span class="shrink-0 text-xs text-muted">{{ t(`davomat.branches.device.${device.status}`) }}</span>
              </li>
            </ul>
            <RouterLink v-else :to="`/c/${company.currentId}/faceid/terminals?add=1`" class="text-sm font-medium text-primary hover:underline">{{ t("davomat.branches.addTerminal") }}</RouterLink>
          </div>
        </li>
      </ul>

      <section v-if="closed.length" class="mt-8 flex flex-col gap-2" data-closed-branches>
        <h2 class="px-1 text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("davomat.branches.closedTitle") }}</h2>
        <ul class="ui-card divide-y divide-line">
          <li v-for="branch in closed" :key="branch.id" class="flex items-center gap-3 px-4 py-2.5">
            <MapPin :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
            <span class="min-w-0 flex-1 truncate text-base text-muted">{{ branch.name }}</span>
            <UiButton v-if="canEdit" size="sm" variant="ghost" :icon="RotateCcw" @click="reopen(branch)">{{ t("davomat.branches.reopen") }}</UiButton>
          </li>
        </ul>
      </section>
    </template>

    <BranchDialog v-if="canEdit" v-model:open="dialog" :branch="editing" />
  </div>
</template>

<style scoped>
.live-dot {
  animation: breathe 2.4s ease-in-out infinite;
}
</style>
