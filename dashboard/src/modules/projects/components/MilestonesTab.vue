<script setup lang="ts">
/**
 * The Milestones tab: the project's milestones in date order on a vertical track, each with its
 * cards done, a progress bar, the due date (overdue in red) and, for those who manage the project,
 * done / reopen, edit and delete.
 */
import { CheckCircle2, Ellipsis, Flag, Pencil, Plus, RotateCcw, Trash2 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { deleteMilestone, updateMilestone, useCompanyId, useMilestones, useRefreshProjects } from "../api";
import { daysBetween } from "../lib";
import type { Milestone, ProjectDetail } from "../types";
import MilestoneDialog from "./MilestoneDialog.vue";

const props = defineProps<{ project: ProjectDetail }>();

const { t } = useI18n();
const fmt = useFormat();
const confirm = useConfirm();
const companyId = useCompanyId();
const refresh = useRefreshProjects();
const query = useMilestones(() => props.project.id);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const dialog = ref(false);
const editing = ref<Milestone | null>(null);
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));

const milestones = computed(() => [...(query.data.value ?? [])].sort((a, b) => (a.due_on ?? "9999").localeCompare(b.due_on ?? "9999") || a.position - b.position));
const manage = computed(() => props.project.capabilities.manage);

function add(): void {
  editing.value = null;
  dialog.value = true;
}

async function toggle(m: Milestone): Promise<void> {
  const next = m.status === "done" ? "open" : "done";
  await updateMilestone(companyId.value, props.project.id, m.id, { status: next });
  toast.success(next === "done" ? t("projects.milestones.reached", { name: m.name }) : t("projects.milestones.reopened", { name: m.name }));
  void refresh();
}

async function remove(m: Milestone): Promise<void> {
  const answer = await confirm({ title: t("projects.milestones.deleteTitle", { name: m.name }), message: t("projects.milestones.deleteBody"), tone: "danger", confirmLabel: t("common.delete"), icon: Trash2 });
  if (!answer) return;
  await deleteMilestone(companyId.value, props.project.id, m.id);
  void refresh();
}

function menu(m: Milestone): MenuEntry[] {
  return [
    { label: m.status === "done" ? t("projects.milestones.reopen") : t("projects.milestones.markDone"), icon: m.status === "done" ? RotateCcw : CheckCircle2, onSelect: () => void toggle(m) },
    { label: t("common.edit"), icon: Pencil, onSelect: () => ((editing.value = m), (dialog.value = true)) },
    { type: "separator" },
    { label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => void remove(m) },
  ];
}

function dueText(m: Milestone): string {
  if (!m.due_on) return t("projects.milestones.noDate");
  if (m.status === "done") return fmt.day(m.due_on, "medium");
  const days = daysBetween(today.value, m.due_on);
  if (days < 0) return t("projects.milestones.lateBy", { n: -days });
  if (days === 0) return t("projects.milestones.dueToday");
  return t("projects.milestones.inDays", { n: days, day: fmt.day(m.due_on, "short") });
}
</script>

<template>
  <div class="mx-auto flex max-w-[880px] flex-col gap-4">
    <div class="flex items-center gap-3">
      <p class="flex-1 text-sm text-muted">{{ t("projects.milestones.intro") }}</p>
      <UiButton v-if="manage" variant="primary" :icon="Plus" @click="add">{{ t("projects.milestones.add") }}</UiButton>
    </div>
    <div v-if="skeleton" class="flex flex-col gap-3">
      <SkeletonBlock v-for="n in 4" :key="n" height="84px" radius="12px" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="query.data.value && !milestones.length" :icon="Flag" :title="t('projects.milestones.emptyTitle')" :description="t('projects.milestones.emptyBody')">
      <UiButton v-if="manage" variant="primary" :icon="Plus" @click="add">{{ t("projects.milestones.add") }}</UiButton>
    </EmptyState>
    <ol v-else class="relative flex flex-col gap-3 pl-8">
      <span class="absolute bottom-6 left-[11px] top-6 w-0.5 rounded-full bg-line" aria-hidden="true" />
      <li v-for="m in milestones" :key="m.id" class="relative">
        <span
          class="absolute -left-8 top-5 grid size-6 place-items-center rounded-full border-2"
          :class="m.status === 'done' ? 'border-success bg-success text-on-primary' : m.overdue ? 'border-danger bg-surface text-danger' : 'border-line-strong bg-surface text-muted'"
          aria-hidden="true"
        >
          <CheckCircle2 v-if="m.status === 'done'" :size="14" />
          <Flag v-else :size="12" />
        </span>
        <article class="ui-card flex flex-col gap-3 p-4 transition-colors" :class="m.overdue && 'border-danger/40'">
          <div class="flex items-start gap-3">
            <div class="min-w-0 flex-1">
              <h3 class="font-semibold" :class="m.status === 'done' ? 'text-muted line-through' : 'text-fg'">{{ m.name }}</h3>
              <p v-if="m.description" class="mt-0.5 text-sm text-muted">{{ m.description }}</p>
            </div>
            <span class="shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums" :class="m.status === 'done' ? 'bg-success-soft text-success' : m.overdue ? 'bg-danger-soft text-danger' : 'bg-surface-2 text-muted'">{{ dueText(m) }}</span>
            <DropdownMenu v-if="manage" :items="menu(m)">
              <template #trigger><IconButton :icon="Ellipsis" :label="t('common.more')" size="sm" /></template>
            </DropdownMenu>
          </div>
          <div class="flex items-center gap-3">
            <ProgressBar :value="m.percent" size="sm" class="flex-1" :tone="m.status === 'done' ? 'success' : m.overdue ? 'danger' : 'primary'" />
            <span class="w-24 text-right text-xs tabular-nums text-muted">{{ t("projects.milestones.cards", { done: m.done, total: m.total }) }}</span>
          </div>
        </article>
      </li>
    </ol>
    <MilestoneDialog v-model:open="dialog" :project-id="project.id" :milestone="editing" />
  </div>
</template>
