<script setup lang="ts">
/**
 * Settings › Branches (plan §4.4): every shop with its address, hours, open days, check-in
 * circle, manager and people. A branch opens in a drawer (`?branch=12`, `?branch=new` to add one);
 * order is changed from each card's menu, closed branches sit at the bottom. Everyone with
 * dashboard access sees the branches in their scope; `company.settings` changes them.
 */
import { ArrowDown, ArrowUp, CircleDot, Clock, EllipsisVertical, MapPin, Pencil, Plus, Store, Users, Wallet } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DropdownMenu from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import PageSection from "@/components/PageSection.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCan } from "@/lib/usePermission";
import { patchQuery } from "@/lib/useRouteState";

import { useBranches, useBranchMutations } from "../api";
import BranchDrawer from "../components/BranchDrawer.vue";
import PanelHeader from "../components/PanelHeader.vue";
import type { Branch } from "../types";

const { t } = useI18n();
const router = useRouter();
const fmt = useFormat();
const branches = useBranches();
const mutations = useBranchMutations();
const canEdit = useCan("company.settings");
const showSkeleton = useDelayedPending(() => branches.isPending.value);

const open = computed(() => (branches.data.value ?? []).filter((b) => b.is_active));
const closed = computed(() => (branches.data.value ?? []).filter((b) => !b.is_active));

function edit(id: number | "new"): void {
  patchQuery(router, { branch: String(id) }, true);
}

const DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
function days(branch: Branch): string {
  const list = branch.open_weekdays;
  if (list.length === 7) return t("settings.branch.everyDay");
  if (list.length === 6 && !list.includes(6)) return t("settings.branch.monSat");
  if (list.length === 5 && !list.includes(5) && !list.includes(6)) return t("settings.branch.monFri");
  if (list.length === 0) return t("settings.branch.noDays");
  return list.map((d) => t(`settings.day.${DAY_KEYS[d]}`)).join(", ");
}

function move(branch: Branch, step: -1 | 1): void {
  const ids = open.value.map((b) => b.id);
  const index = ids.indexOf(branch.id);
  const target = index + step;
  if (target < 0 || target >= ids.length) return;
  [ids[index], ids[target]] = [ids[target]!, ids[index]!];
  void mutations.reorder.mutateAsync([...ids, ...closed.value.map((b) => b.id)]);
}

function menu(branch: Branch, index: number) {
  return [
    { label: t("common.edit"), icon: Pencil, onSelect: () => edit(branch.id) },
    { label: t("settings.branch.moveUp"), icon: ArrowUp, disabled: index === 0, onSelect: () => move(branch, -1) },
    { label: t("settings.branch.moveDown"), icon: ArrowDown, disabled: index === open.value.length - 1, onSelect: () => move(branch, 1) },
  ];
}
</script>

<template>
  <div>
    <PanelHeader :title="t('settings.panel.branches')" :description="t('settings.branches.description')">
      <template v-if="canEdit && branches.data.value?.length" #actions>
        <UiButton variant="primary" :icon="Plus" @click="edit('new')">{{ t("settings.branch.add") }}</UiButton>
      </template>
    </PanelHeader>

    <ErrorState v-if="branches.isError.value" :error="branches.error.value" :retry="() => branches.refetch()" :retrying="branches.isFetching.value" />

    <div v-else-if="showSkeleton || !branches.data.value" class="flex flex-col gap-3" aria-busy="true">
      <div v-for="n in 2" :key="n" class="ui-card flex gap-4 p-4">
        <SkeletonBlock width="44px" height="44px" radius="12px" />
        <div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="35%" height="16px" /><SkeletonBlock width="70%" /><SkeletonBlock width="50%" /></div>
      </div>
    </div>

    <EmptyState
      v-else-if="!branches.data.value.length"
      :title="t('settings.branches.emptyTitle')"
      :description="t('settings.branches.emptyBody')"
      :icon="Store"
    >
      <UiButton v-if="canEdit" variant="primary" :icon="Plus" @click="edit('new')">{{ t("settings.branch.add") }}</UiButton>
    </EmptyState>

    <div v-else class="flex flex-col gap-7">
      <TransitionGroup tag="ul" name="list" class="flex flex-col gap-3">
        <li
          v-for="(branch, index) in open"
          :key="branch.id"
          class="ui-card group relative flex cursor-pointer gap-4 p-4 transition-[border-color,box-shadow] duration-150 hover:border-line-strong hover:shadow-[var(--sh-raised)]"
          @click="edit(branch.id)"
        >
          <span class="grid size-11 shrink-0 place-items-center rounded-[12px] bg-accent-soft text-accent-fg">
            <Store :size="20" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <button type="button" class="truncate text-left text-md font-semibold text-fg hover:underline" @click.stop="edit(branch.id)">{{ branch.name }}</button>
              <UiBadge v-if="branch.code" tone="neutral" variant="outline" class="font-mono">{{ branch.code }}</UiBadge>
              <StatusPill v-if="!branch.latitude" tone="warning" size="sm" :label="t('settings.branch.noPlace')" />
            </div>
            <p class="mt-1 flex items-start gap-1.5 text-sm text-muted">
              <MapPin :size="14" class="mt-0.5 shrink-0" />
              <span class="min-w-0">{{ branch.address || t("settings.branch.noAddress") }}</span>
            </p>
            <div class="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5 text-sm text-muted">
              <span class="inline-flex items-center gap-1.5"><Clock :size="14" />
                <template v-if="branch.opens_at">{{ branch.opens_at }}–{{ branch.closes_at }} · </template>{{ days(branch) }}
              </span>
              <span class="inline-flex items-center gap-1.5"><Users :size="14" />{{ t("settings.branch.peopleCount", { n: branch.people }, branch.people) }}</span>
              <span v-if="branch.latitude" class="inline-flex items-center gap-1.5"><CircleDot :size="14" />{{ t("settings.branch.radiusShort", { m: branch.geofence_m }) }}</span>
              <span v-if="branch.cash_limit" class="inline-flex items-center gap-1.5"><Wallet :size="14" />{{ t("settings.branch.limitShort", { amount: fmt.money(branch.cash_limit) }) }}</span>
            </div>
            <p v-if="branch.manager" class="mt-2 text-sm text-fg">
              <span class="text-muted">{{ t("settings.branch.managerLabel") }}</span> {{ branch.manager.name }}
            </p>
          </div>
          <div v-if="canEdit" class="shrink-0" @click.stop>
            <DropdownMenu :items="menu(branch, index)">
              <template #trigger><IconButton :icon="EllipsisVertical" :label="t('settings.branch.actions')" size="sm" /></template>
            </DropdownMenu>
          </div>
        </li>
      </TransitionGroup>

      <PageSection v-if="closed.length" :title="t('settings.branches.closed')" :count="closed.length" collapsible id="settings-closed-branches">
        <ul class="flex flex-col gap-2">
          <li
            v-for="branch in closed"
            :key="branch.id"
            class="flex cursor-pointer items-center gap-3 rounded-[12px] border border-dashed border-line px-4 py-3 text-muted hover:border-line-strong"
            @click="edit(branch.id)"
          >
            <Store :size="16" />
            <span class="min-w-0 flex-1 truncate text-base">{{ branch.name }}</span>
            <StatusPill tone="neutral" size="sm" :label="t('settings.branch.closedLabel')" />
          </li>
        </ul>
      </PageSection>
    </div>

    <BranchDrawer :branches="branches.data.value ?? []" :loaded="!!branches.data.value" :can-edit="canEdit" />
  </div>
</template>

<style scoped>
.list-move {
  transition: transform var(--dur-drawer) var(--ease-out);
}
</style>
