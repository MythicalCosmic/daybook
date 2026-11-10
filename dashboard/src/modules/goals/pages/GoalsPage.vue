<script setup lang="ts">
/**
 * Maqsadlar (v11): the business goals ("1.5 bln revenue this quarter, a third pharmacy, staff
 * turnover under 10 %"), each measured from the company's own data. Tabs for active, done and
 * archived goals; a line of how many are on track, at risk and off track; the cards, worst first;
 * the drawer of one goal (`?goal=`); and for owners the dialog that sets or changes one.
 */
import { Archive, ArchiveRestore, Pencil, Plus, Target, Trash2 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import type { MenuEntry } from "@/components/menuTypes";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { rs, useRouteState } from "@/lib/useRouteState";

import { goalsApi, sortGoals, STATE_TONES, stateCounts, useGoals, useGoalWrite, type Goal, type Tab } from "../api";
import GoalCard from "../components/GoalCard.vue";
import GoalDialog from "../components/GoalDialog.vue";
import GoalDrawer from "../components/GoalDrawer.vue";

const { t } = useI18n();
const confirm = useConfirm();
const tab = useRouteState("status", rs.enum(["active", "done", "archived"] as const, "active"));
const goalParam = useRouteState("goal", rs.optionalNumber());
const list = useGoals(tab);
const data = computed(() => list.data.value);
const skeleton = useDelayedPending(computed(() => list.isPending.value));
const goals = computed(() => sortGoals(data.value?.goals ?? []));
const counts = computed(() => (tab.value === "active" ? stateCounts(goals.value) : []));
const today = computed(() => data.value?.today ?? new Date().toISOString().slice(0, 10));

const tabModel = computed({
  get: () => tab.value as string,
  set: (value: string) => (tab.value = (["active", "done", "archived"].includes(value) ? value : "active") as Tab),
});
const tabs = computed(() => [
  { id: "active", label: t("goals.tab.active"), count: data.value?.counts.active || undefined },
  { id: "done", label: t("goals.tab.done"), count: data.value?.counts.done || undefined },
  { id: "archived", label: t("goals.tab.archived"), count: data.value?.counts.archived || undefined },
]);

const creating = ref(false);
const editing = ref<Goal | null>(null);
const editOpen = computed({
  get: () => editing.value !== null,
  set: (value: boolean) => {
    if (!value) editing.value = null;
  },
});

const archive = useGoalWrite((cid: number, id: number) => goalsApi.archive(cid, id));
const restore = useGoalWrite((cid: number, id: number) => goalsApi.restore(cid, id));
const remove = useGoalWrite((cid: number, id: number) => goalsApi.remove(cid, id));

async function archiveGoal(goal: Goal): Promise<void> {
  await archive.mutateAsync(goal.id);
  toast.success(t("goals.archived", { title: goal.title }));
}
async function restoreGoal(goal: Goal): Promise<void> {
  await restore.mutateAsync(goal.id);
  toast.success(t("goals.restored", { title: goal.title }));
}
async function removeGoal(goal: Goal): Promise<void> {
  const answer = await confirm({ title: t("goals.deleteTitle", { title: goal.title }), message: t("goals.deleteBody"), tone: "danger", confirmLabel: t("common.delete") });
  if (!answer) return;
  await remove.mutateAsync(goal.id);
  if (goalParam.value === goal.id) goalParam.value = null;
  toast.success(t("goals.deleted"));
}
function edit(goal: Goal): void {
  goalParam.value = null;
  editing.value = goal;
}
function menu(goal: Goal): MenuEntry[] {
  if (!goal.can_edit) return [];
  if (goal.status === "archived") {
    return [
      { label: t("goals.restore"), icon: ArchiveRestore, onSelect: () => void restoreGoal(goal) },
      { label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => void removeGoal(goal) },
    ];
  }
  return [
    { label: t("common.edit"), icon: Pencil, onSelect: () => edit(goal) },
    { label: t("goals.archive"), icon: Archive, onSelect: () => void archiveGoal(goal) },
    { type: "separator" },
    { label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => void removeGoal(goal) },
  ];
}
const examples = computed(() => [t("goals.example.revenue"), t("goals.example.branches"), t("goals.example.turnover")]);
</script>

<template>
  <div>
    <PageHeader v-model:tab="tabModel" :title="t('goals.title')" :description="t('goals.description')" :tabs="tabs">
      <template #actions>
        <UiButton v-if="data?.can_manage" variant="primary" :icon="Plus" data-new-goal @click="creating = true">{{ t("goals.new") }}</UiButton>
      </template>
    </PageHeader>

    <ErrorState v-if="list.isError.value" :error="list.error.value" :retry="() => list.refetch()" />

    <div v-else-if="skeleton || !data" class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-busy="true">
      <SkeletonBlock v-for="n in 6" :key="n" height="236px" radius="16px" />
    </div>

    <div v-else-if="!goals.length" class="ui-card">
      <EmptyState
        :icon="Target"
        size="lg"
        :title="tab === 'active' ? t('goals.emptyTitle') : tab === 'done' ? t('goals.emptyDone') : t('goals.emptyArchived')"
        :description="tab === 'active' ? t('goals.emptyBody') : undefined"
      >
        <template v-if="tab === 'active'">
          <ul class="mb-4 flex flex-wrap justify-center gap-2">
            <li v-for="example in examples" :key="example" class="rounded-full border border-line bg-surface-2/60 px-3 py-1 text-sm text-muted">{{ example }}</li>
          </ul>
          <UiButton v-if="data.can_manage" variant="primary" :icon="Plus" @click="creating = true">{{ t("goals.new") }}</UiButton>
        </template>
      </EmptyState>
    </div>

    <template v-else>
      <div v-if="counts.length" class="mb-4 flex flex-wrap items-center gap-2" data-state-counts>
        <StatusPill v-for="row in counts" :key="row.state" :tone="STATE_TONES[row.state]" :label="t(`goals.countState.${row.state}`, { n: row.count }, row.count)" dot />
      </div>
      <TransitionGroup tag="div" name="list" class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <GoalCard v-for="goal in goals" :key="goal.id" :goal="goal" :menu="menu(goal)" @open="goalParam = goal.id" />
      </TransitionGroup>
    </template>

    <GoalDrawer @edit="edit" @archive="archiveGoal" @restore="restoreGoal" @remove="removeGoal" />
    <GoalDialog v-model:open="creating" :today="today" />
    <GoalDialog v-model:open="editOpen" :today="today" :goal="editing" />
  </div>
</template>
