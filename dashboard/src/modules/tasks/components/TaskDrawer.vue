<script setup lang="ts">
/**
 * The task drawer, synced with `?task=` (plan §6.2): status, the right action buttons for the
 * caller, the proof photo with its lightbox, inline edits (assignee, deadline, priority, reward,
 * title and description), the checklist, how the bot chases it, and comments, the merged timeline
 * and the audited history in tabs. Other modules add buttons through `tasks.drawer.actions`.
 */
import { BellRing, Check, CircleCheck, Ellipsis, Flag, FolderKanban, Gift, Link2, MessageSquare, Pencil, Repeat, RotateCcw, Send, UserRoundCog, X } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRouter } from "vue-router";

import AuditTrail from "@/components/AuditTrail.vue";
import DatePicker from "@/components/DatePicker.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import IconButton from "@/components/IconButton.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import PersonCell from "@/components/PersonCell.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import ProofThumb from "@/components/ProofThumb.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UiPopover from "@/components/UiPopover.vue";
import { useConfirm } from "@/components/useConfirm";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { tasksApi, taskKeys, useRefreshTasks, useTaskDetail, useTaskMutation, useTaskOptions } from "../api";
import { cardKey, lateness, minutesBetween, zonedIso, zonedParts } from "../meta";
import type { TaskDetail, TaskPriority, TaskUpdateInput } from "../types";
import { PRIORITIES } from "../types";
import DueLabel from "./DueLabel.vue";
import TaskStatusPill from "./TaskStatusPill.vue";
import TaskTimeline from "./TaskTimeline.vue";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const router = useRouter();
const client = useQueryClient();
const confirm = useConfirm();
const refresh = useRefreshTasks();

const id = computed(() => {
  const raw = router.currentRoute.value.query.task;
  const value = Number(Array.isArray(raw) ? raw[0] : raw);
  return Number.isInteger(value) && value > 0 ? value : null;
});
const query = useTaskDetail(id);
const task = computed(() => query.data.value ?? null);
const options = useTaskOptions();
const can = (action: string) => !!task.value?.actions.includes(action as never);

const tab = ref<"comments" | "timeline" | "history">("comments");
watch(id, () => {
  tab.value = "comments";
  editing.value = false;
});

// Writes -------------------------------------------------------------------------------------
const update = useTaskMutation((cid, input: TaskUpdateInput) => tasksApi.update(cid, id.value!, input));
const confirmTask = useTaskMutation((cid, _: void) => tasksApi.confirm(cid, id.value!));
const sendBack = useTaskMutation((cid, reason: string) => tasksApi.sendBack(cid, id.value!, reason));
const cancel = useTaskMutation((cid, _: void) => tasksApi.cancel(cid, id.value!));
const reassign = useTaskMutation((cid, assignee: number) => tasksApi.reassign(cid, id.value!, assignee));
const busy = ref<string | null>(null);

async function run<T>(key: string, action: () => Promise<T>, done?: string): Promise<T | undefined> {
  busy.value = key;
  try {
    const result = await action();
    if (done) toast.success(done, { description: task.value?.title });
    return result;
  } catch {
    return undefined; // the HTTP layer showed why
  } finally {
    busy.value = null;
  }
}

async function onConfirm(): Promise<void> {
  await run("confirm", () => confirmTask.mutateAsync(), t("tasks.toast.confirmed"));
}

async function onSendBack(): Promise<void> {
  const answer = await confirm({
    title: t("tasks.sendBack.title"),
    message: task.value?.title,
    reason: "required",
    reasonLabel: t("tasks.sendBack.reason"),
    reasonPlaceholder: t("tasks.sendBack.placeholder"),
    confirmLabel: t("tasks.action.return"),
    tone: "danger",
  });
  if (answer) await run("return", () => sendBack.mutateAsync(answer.reason), t("tasks.toast.returned"));
}

async function onCancel(): Promise<void> {
  const answer = await confirm({ title: t("tasks.cancel.title"), message: t("tasks.cancel.body"), tone: "danger", confirmLabel: t("tasks.action.cancel") });
  if (answer) await run("cancel", () => cancel.mutateAsync(), t("tasks.toast.cancelled"));
}

async function onNudge(): Promise<void> {
  const current = task.value;
  if (!current) return;
  const result = await run("nudge", () => tasksApi.nudge(company.currentId!, current.id), t("tasks.toast.nudged", { name: current.assignee.name }));
  if (result) {
    client.setQueryData<TaskDetail>(taskKeys.detail(company.currentId!, current.id), { ...current, last_nudged_at: result.nudged_at });
    void refresh();
  }
}

// Reassign
const reassignOpen = ref(false);
const reassignTo = ref<number | null>(null);
const people = computed(() =>
  (options.data.value?.people ?? []).map((p) => ({ id: p.id, name: p.name, photo_url: p.photo_url, subtitle: [p.position, p.branch].filter(Boolean).join(" · ") })),
);
async function onReassign(): Promise<void> {
  if (!reassignTo.value) return;
  reassignOpen.value = false;
  const name = people.value.find((p) => p.id === reassignTo.value)?.name ?? "";
  await run("reassign", () => reassign.mutateAsync(reassignTo.value!), t("tasks.toast.reassigned", { name }));
  reassignTo.value = null;
}

// Inline edits
const dueOpen = ref(false);
const dueDay = ref<string | null>(null);
const dueTime = ref<string | null>("18:00");
watch(dueOpen, (open) => {
  if (!open || !task.value) return;
  const parts = task.value.due_at ? zonedParts(task.value.due_at, company.timezone) : { day: todayIn(company.timezone), time: "18:00" };
  dueDay.value = parts.day;
  dueTime.value = parts.time;
});
async function saveDue(clear = false): Promise<void> {
  dueOpen.value = false;
  const due_at = clear || !dueDay.value ? null : zonedIso(dueDay.value, dueTime.value ?? "18:00", company.timezone);
  await run("due", () => update.mutateAsync({ due_at }), t("tasks.toast.saved"));
}

const priority = computed({
  get: () => task.value?.priority ?? "normal",
  set: (value: TaskPriority) => {
    if (value !== task.value?.priority) void run("priority", () => update.mutateAsync({ priority: value }), t("tasks.toast.saved"));
  },
});
const priorityOptions = computed(() => PRIORITIES.map((value) => ({ value, label: t(`tasks.priority.${value}`) })));

const rewardOpen = ref(false);
const reward = ref<string | null>(null);
watch(rewardOpen, (open) => open && (reward.value = task.value?.reward ?? null));
async function saveReward(): Promise<void> {
  rewardOpen.value = false;
  await run("reward", () => update.mutateAsync({ reward: reward.value || null }), t("tasks.toast.saved"));
}

const editing = ref(false);
const title = ref("");
const description = ref("");
function startEditing(): void {
  title.value = task.value?.title ?? "";
  description.value = task.value?.description ?? "";
  editing.value = true;
}
async function saveText(): Promise<void> {
  if (!title.value.trim()) return;
  const saved = await run("text", () => update.mutateAsync({ title: title.value.trim(), description: description.value }), t("tasks.toast.saved"));
  if (saved) editing.value = false;
}

// Comments
const comment = ref("");
const sending = ref(false);
async function sendComment(): Promise<void> {
  const current = task.value;
  if (!current || !comment.value.trim()) return;
  sending.value = true;
  try {
    const created = await tasksApi.comment(company.currentId!, current.id, comment.value.trim());
    client.setQueryData<TaskDetail>(taskKeys.detail(company.currentId!, current.id), { ...current, comments: [...current.comments, created] });
    comment.value = "";
    void client.invalidateQueries({ queryKey: taskKeys.timeline(company.currentId!, current.id) });
  } catch {
    // shown by the HTTP layer
  } finally {
    sending.value = false;
  }
}

/** When finished work was handed in (waiting for a check counts), and how late, if it was. */
const finished = computed(() => {
  const current = task.value;
  if (!current?.completed_at || (current.status !== "done" && current.status !== "review")) return null;
  const minutes = current.due_at ? minutesBetween(current.due_at, current.completed_at) : 0;
  const words = { min: t("tasks.unit.min"), h: t("tasks.unit.h"), d: t("tasks.unit.d") };
  return { at: current.completed_at, late: minutes > 0 ? t("tasks.due.lateBy", { time: lateness(minutes, words) }) : null };
});

/** Under the title: the board card ("OPEN-14 · Chilonzor branch opening") or the kind, then the branch. */
const subtitle = computed(() => {
  const current = task.value;
  if (!current) return undefined;
  const kind = current.routine?.onboarding ? "onboarding" : current.routine ? "routine" : current.kind;
  const first = current.project ? `${cardKey(current.project)} · ${current.project.name}` : t(`tasks.kind.${kind}`);
  return [first, current.branch?.name].filter(Boolean).join(" · ");
});

const proofImages = computed(() => (task.value?.proof_photo ? [{ src: task.value.proof_photo, caption: task.value.title }] : []));
const checklistDone = computed(() => task.value?.checklist_items.filter((item) => item.is_done).length ?? 0);

const menu = computed<MenuEntry[]>(() => {
  const entries: MenuEntry[] = [{ label: t("tasks.action.copyLink"), icon: Link2, onSelect: copyLink }];
  if (can("cancel")) entries.push({ type: "separator" }, { label: t("tasks.action.cancel"), icon: X, danger: true, onSelect: onCancel });
  return entries;
});
function copyLink(): void {
  void navigator.clipboard?.writeText(window.location.href).then(() => toast.success(t("tasks.toast.linkCopied")));
}

const nudgedRecently = computed(() => {
  const at = task.value?.last_nudged_at;
  return !!at && Date.now() - new Date(at).getTime() < 10 * 60_000;
});

/**
 * What `tasks.drawer.actions` extensions get: the task's id and its routine's (`template_id`, null
 * for one-off work), e.g. knowledge's "How to do this" looks up pages linked to either.
 */
const slotContext = computed(() => ({
  task: { id: task.value?.id ?? null, template_id: task.value?.routine?.id ?? null },
  companyId: company.currentId,
}));

const reminderLine = computed(() => {
  const plan = task.value?.reminders;
  if (!plan) return null;
  const parts = [t("tasks.reminders.every", { n: plan.every_minutes })];
  parts.push(plan.max_reminders ? t("tasks.reminders.sentOf", { sent: plan.sent, max: plan.max_reminders }) : t("tasks.reminders.sent", { sent: plan.sent }));
  return parts.join(" · ");
});

const fieldLabels = computed(() => ({
  title: t("tasks.field.title"),
  description: t("tasks.field.description"),
  due_at: t("tasks.field.due_at"),
  priority: t("tasks.field.priority"),
  reward: t("tasks.field.reward"),
  assignee: t("tasks.field.assignee"),
  status: t("tasks.field.status"),
}));
const formatAudit = (field: string, value: unknown) => {
  if (field === "due_at" && typeof value === "string") return fmt.instant(value);
  if (field === "reward" && typeof value === "string") return fmt.money(value);
  if (field === "priority" && typeof value === "string") return t(`tasks.priority.${value}`);
  return null;
};
</script>

<template>
  <UiDrawer query-key="task" size="lg" :title="task?.title ?? t('tasks.drawer.loading')" :description="subtitle">
    <template #header-actions>
      <DropdownMenu v-if="task" :items="menu" align="end">
        <template #trigger><IconButton :icon="Ellipsis" :label="t('common.more')" /></template>
      </DropdownMenu>
    </template>

    <div v-if="query.isPending.value" class="flex flex-col gap-4 p-5">
      <SkeletonBlock width="40%" height="22px" />
      <SkeletonBlock height="180px" radius="12px" />
      <div v-for="n in 4" :key="n" class="flex gap-4"><SkeletonBlock width="30%" /><SkeletonBlock width="50%" /></div>
    </div>
    <ErrorState v-else-if="query.isError.value" class="m-5" :error="query.error.value" :retry="() => query.refetch()" />

    <div v-else-if="task" class="flex flex-col">
      <!-- Status and actions -->
      <section class="flex flex-col gap-3 border-b border-line px-5 py-4">
        <div class="flex flex-wrap items-center gap-2">
          <TaskStatusPill :status="task.status" :overdue="task.is_overdue" size="md" />
          <span v-if="task.priority === 'urgent' || task.priority === 'high'" :class="['inline-flex items-center gap-1 text-sm font-semibold', task.priority === 'urgent' ? 'text-danger' : 'text-warning']">
            <Flag :size="14" />{{ t(`tasks.priority.${task.priority}`) }}
          </span>
          <span v-if="task.reward" class="inline-flex items-center gap-1 rounded-full bg-success-soft px-2 py-0.5 text-sm font-semibold text-success"><Gift :size="13" /><MoneyText :value="task.reward" sign="always" /></span>
          <span class="flex-1" />
          <!-- Finished work says when it was finished (the deadline is in the details below). -->
          <span v-if="finished" class="inline-flex min-w-0 items-center gap-1 text-sm tabular-nums text-muted" :title="fmt.instant(finished.at, 'datetime')">
            <CircleCheck :size="13" class="shrink-0" aria-hidden="true" />
            <span class="truncate">{{ t("tasks.drawer.finishedAt", { time: fmt.instant(finished.at) }) }}</span>
            <span v-if="finished.late" class="shrink-0 text-xs font-semibold text-danger">· {{ finished.late }}</span>
          </span>
          <DueLabel v-else :due="task.due_at" :overdue="task.is_overdue" icon class="text-sm" />
        </div>
        <div class="flex flex-wrap items-center gap-2 empty:hidden">
          <UiButton v-if="can('confirm')" variant="primary" :icon="Check" :loading="busy === 'confirm'" @click="onConfirm">{{ t("tasks.action.confirm") }}</UiButton>
          <UiButton v-if="can('return')" :icon="RotateCcw" :loading="busy === 'return'" @click="onSendBack">{{ t("tasks.action.return") }}</UiButton>
          <UiPopover v-if="can('reassign')" v-model:open="reassignOpen" width="300px">
            <template #trigger><UiButton :icon="UserRoundCog" :loading="busy === 'reassign'">{{ t("tasks.action.reassign") }}</UiButton></template>
            <div class="flex flex-col gap-2">
              <p class="text-sm font-semibold text-fg">{{ t("tasks.reassign.title") }}</p>
              <p class="text-xs text-muted">{{ t("tasks.reassign.hint") }}</p>
              <PersonPicker v-model="reassignTo" :people="people" :exclude="[task.assignee.id]" size="sm" />
              <UiButton size="sm" variant="primary" :disabled="!reassignTo" @click="onReassign">{{ t("tasks.action.reassign") }}</UiButton>
            </div>
          </UiPopover>
          <UiButton v-if="can('nudge')" :icon="BellRing" :loading="busy === 'nudge'" :disabled="nudgedRecently" :title="nudgedRecently ? t('tasks.nudge.wait') : t('tasks.nudge.hint')" @click="onNudge">
            {{ nudgedRecently ? t("tasks.nudge.sent") : t("tasks.action.nudge") }}
          </UiButton>
          <ExtensionSlot name="tasks.drawer.actions" as="none" :context="slotContext" />
        </div>
      </section>

      <!-- Proof -->
      <section v-if="task.proof_photo || task.proof_text" class="flex flex-col gap-3 border-b border-line px-5 py-4">
        <h3 class="text-xs font-semibold uppercase tracking-[0.05em] text-subtle">{{ t("tasks.drawer.proof") }}</h3>
        <div v-if="task.proof_photo" class="aspect-[4/3] w-full max-w-[420px] overflow-hidden rounded-[12px] border border-line bg-surface-2">
          <ProofThumb :src="task.proof_photo" :images="proofImages" size="fill" :label="task.completed_at ? fmt.instant(task.completed_at, 'time') : undefined" />
        </div>
        <blockquote v-if="task.proof_text" class="rounded-[10px] border-l-[3px] border-primary bg-surface-2 px-3 py-2 text-sm text-fg">{{ task.proof_text }}</blockquote>
      </section>

      <!-- Details -->
      <section class="flex flex-col gap-3 border-b border-line px-5 py-4">
        <div v-if="editing" class="flex flex-col gap-2">
          <TextInput v-model="title" :maxlength="200" :placeholder="t('tasks.field.title')" autofocus />
          <TextArea v-model="description" :rows="3" :placeholder="t('tasks.create.descriptionPlaceholder')" @submit="saveText" />
          <div class="flex justify-end gap-2">
            <UiButton size="sm" variant="ghost" @click="editing = false">{{ t("common.cancel") }}</UiButton>
            <UiButton size="sm" variant="primary" :loading="busy === 'text'" :disabled="!title.trim()" @click="saveText">{{ t("common.save") }}</UiButton>
          </div>
        </div>
        <div v-else class="group/desc flex items-start gap-2">
          <p :class="['min-w-0 flex-1 whitespace-pre-line text-sm', task.description ? 'text-fg' : 'text-subtle']">{{ task.description || t("tasks.drawer.noDescription") }}</p>
          <IconButton v-if="can('edit')" :icon="Pencil" :label="t('tasks.action.edit')" size="sm" @click="startEditing" />
        </div>

        <dl class="grid grid-cols-[minmax(110px,auto)_1fr] items-center gap-x-4 gap-y-2.5 text-sm">
          <dt class="text-muted">{{ t("tasks.field.assignee") }}</dt>
          <dd class="min-w-0"><PersonCell :person="task.assignee" :subtitle="task.assignee.position" size="sm" link /></dd>

          <dt class="text-muted">{{ t("tasks.field.due_at") }}</dt>
          <dd class="flex min-w-0 items-center gap-2">
            <DueLabel :due="task.due_at" :overdue="task.is_overdue" />
            <UiPopover v-if="can('edit')" v-model:open="dueOpen" width="300px">
              <template #trigger><IconButton :icon="Pencil" :label="t('tasks.due.change')" size="sm" /></template>
              <div class="flex flex-col gap-2">
                <p class="text-sm font-semibold text-fg">{{ t("tasks.due.change") }}</p>
                <div class="grid grid-cols-[1fr_110px] gap-2">
                  <DatePicker v-model="dueDay" :min="todayIn(company.timezone)" size="sm" />
                  <TimePicker v-model="dueTime" :step="15" size="sm" />
                </div>
                <div class="flex justify-between gap-2">
                  <UiButton size="sm" variant="ghost" @click="saveDue(true)">{{ t("tasks.due.clear") }}</UiButton>
                  <UiButton size="sm" variant="primary" :disabled="!dueDay" @click="saveDue()">{{ t("common.save") }}</UiButton>
                </div>
              </div>
            </UiPopover>
          </dd>

          <dt class="text-muted">{{ t("tasks.field.priority") }}</dt>
          <dd class="min-w-0">
            <SelectBox v-if="can('edit')" v-model="priority" :options="priorityOptions" size="sm" class="w-40" />
            <span v-else>{{ t(`tasks.priority.${task.priority}`) }}</span>
          </dd>

          <template v-if="task.kind !== 'personal'">
            <dt class="text-muted">{{ t("tasks.field.reward") }}</dt>
            <dd class="flex min-w-0 items-center gap-2">
              <span v-if="task.reward" class="font-semibold text-success"><MoneyText :value="task.reward" sign="always" /></span>
              <span v-else class="text-subtle">{{ t("tasks.reward.none") }}</span>
              <UiPopover v-if="can('edit')" v-model:open="rewardOpen" width="280px">
                <template #trigger><IconButton :icon="Pencil" :label="t('tasks.reward.change')" size="sm" /></template>
                <div class="flex flex-col gap-2">
                  <p class="text-sm font-semibold text-fg">{{ t("tasks.reward.change") }}</p>
                  <p class="text-xs text-muted">{{ t("tasks.reward.hint") }}</p>
                  <MoneyInput v-model="reward" size="sm" />
                  <UiButton size="sm" variant="primary" @click="saveReward">{{ t("common.save") }}</UiButton>
                </div>
              </UiPopover>
            </dd>
          </template>

          <template v-if="task.branch">
            <dt class="text-muted">{{ t("tasks.field.branch") }}</dt>
            <dd class="min-w-0 truncate text-fg">{{ task.branch.name }}</dd>
          </template>
          <template v-if="task.project">
            <dt class="text-muted">{{ t("tasks.field.project") }}</dt>
            <dd class="min-w-0">
              <RouterLink :to="`/c/${company.currentId}/projects/${task.project.id}/board?card=${task.id}`" class="inline-flex min-w-0 items-center gap-1.5 text-primary hover:underline">
                <FolderKanban :size="13" class="shrink-0" aria-hidden="true" />
                <span class="shrink-0 font-mono text-xs font-semibold">{{ cardKey(task.project) }}</span>
                <span class="truncate">{{ task.project.name }}</span>
              </RouterLink>
            </dd>
          </template>
          <template v-if="task.routine">
            <dt class="text-muted">{{ t("tasks.field.routine") }}</dt>
            <dd class="min-w-0">
              <RouterLink :to="`/c/${company.currentId}/routines/${task.routine.id}`" class="inline-flex min-w-0 items-center gap-1 text-primary hover:underline">
                <Repeat :size="13" class="shrink-0" /><span class="truncate">{{ task.routine.title }}</span>
              </RouterLink>
            </dd>
          </template>
          <template v-if="task.created_by && task.kind !== 'personal'">
            <dt class="text-muted">{{ t("tasks.field.givenBy") }}</dt>
            <dd class="min-w-0"><PersonCell :person="task.created_by" size="sm" /></dd>
          </template>
          <template v-if="task.confirmed_by">
            <dt class="text-muted">{{ t("tasks.field.confirmedBy") }}</dt>
            <dd class="min-w-0 text-fg">{{ task.confirmed_by.name }} · <RelativeTime :value="task.confirmed_at" class="text-muted" /></dd>
          </template>
          <dt class="text-muted">{{ t("tasks.field.created") }}</dt>
          <dd class="min-w-0 text-muted"><RelativeTime :value="task.created_at" /></dd>
        </dl>
      </section>

      <!-- Checklist -->
      <section v-if="task.checklist_items.length" class="flex flex-col gap-2.5 border-b border-line px-5 py-4">
        <div class="flex items-center gap-3">
          <h3 class="text-xs font-semibold uppercase tracking-[0.05em] text-subtle">{{ t("tasks.drawer.checklist") }}</h3>
          <span class="text-xs font-semibold tabular-nums text-muted">{{ checklistDone }}/{{ task.checklist_items.length }}</span>
          <ProgressBar class="flex-1" :value="checklistDone" :max="task.checklist_items.length" :tone="checklistDone === task.checklist_items.length ? 'success' : 'primary'" />
        </div>
        <ul class="flex flex-col gap-1.5">
          <li v-for="item in task.checklist_items" :key="item.id" class="flex items-start gap-2 text-sm">
            <span :class="['mt-0.5 grid size-4 shrink-0 place-items-center rounded-[4px] border', item.is_done ? 'border-success bg-success text-on-primary' : 'border-line-strong']" aria-hidden="true">
              <Check v-if="item.is_done" :size="11" :stroke-width="3" />
            </span>
            <span :class="item.is_done ? 'text-muted line-through' : 'text-fg'">{{ item.text }}</span>
          </li>
        </ul>
      </section>

      <!-- Reminders -->
      <section v-if="task.reminders && task.status !== 'done' && task.status !== 'cancelled'" class="flex flex-col gap-1.5 border-b border-line px-5 py-4">
        <h3 class="text-xs font-semibold uppercase tracking-[0.05em] text-subtle">{{ t("tasks.drawer.reminders") }}</h3>
        <p class="text-sm text-fg">
          <BellRing :size="13" class="mr-1 inline text-muted" />{{ task.reminders.policy.name }} · {{ reminderLine }}
        </p>
        <p v-if="task.reminders.next_at" class="text-xs text-muted">{{ t("tasks.reminders.next", { time: fmt.relative(task.reminders.next_at) }) }}</p>
        <p v-if="task.reminders.escalated_at" class="text-xs font-medium text-danger">
          {{ t("tasks.reminders.escalated", { names: task.reminders.escalate_to.map((p) => p.name).join(", ") || "—", time: fmt.relative(task.reminders.escalated_at) }) }}
        </p>
        <p v-else-if="task.reminders.escalate_after" class="text-xs text-muted">
          {{ t("tasks.reminders.willEscalate", { n: task.reminders.escalate_after, names: task.reminders.escalate_to.map((p) => p.name).join(", ") || "—" }) }}
        </p>
      </section>

      <!-- Comments, timeline, history -->
      <section class="flex flex-col gap-3 px-5 py-4">
        <SegmentedControl
          v-model="tab"
          size="sm"
          :options="[
            { value: 'comments', label: t('tasks.drawer.comments'), icon: MessageSquare, count: task.comments.length || undefined },
            { value: 'timeline', label: t('tasks.drawer.timeline') },
            { value: 'history', label: t('tasks.drawer.history') },
          ]"
        />
        <div v-if="tab === 'comments'" class="flex flex-col gap-3">
          <EmptyState v-if="!task.comments.length" size="sm" tone="neutral" :icon="MessageSquare" :title="t('tasks.comments.empty')" :description="t('tasks.comments.emptyBody')" />
          <ul v-else class="flex flex-col gap-3">
            <li v-for="item in task.comments" :key="item.id" class="flex gap-2.5">
              <UserAvatar :name="item.author?.name ?? t('tasks.timeline.system')" :src="item.author?.photo_url" :size="28" class="mt-0.5 shrink-0" />
              <div class="min-w-0 flex-1 rounded-[10px] bg-surface-2 px-3 py-2">
                <p class="flex items-center gap-2 text-xs text-muted"><span class="font-semibold text-fg">{{ item.author?.name ?? t("tasks.timeline.system") }}</span><RelativeTime :value="item.created_at" /></p>
                <p class="mt-0.5 whitespace-pre-line text-sm text-fg">{{ item.text }}</p>
              </div>
            </li>
          </ul>
          <form class="flex items-end gap-2" @submit.prevent="sendComment">
            <TextArea v-model="comment" :rows="1" :max-rows="6" :placeholder="t('tasks.comments.placeholder')" class="flex-1" @submit="sendComment" />
            <IconButton :icon="Send" :label="t('tasks.comments.send')" variant="primary" type="submit" :loading="sending" :disabled="!comment.trim()" />
          </form>
        </div>
        <TaskTimeline v-else-if="tab === 'timeline'" :task-id="task.id" />
        <AuditTrail v-else target-type="task" :target-id="task.id" :field-labels="fieldLabels" :format-value="formatAudit" />
      </section>
    </div>
  </UiDrawer>
</template>
