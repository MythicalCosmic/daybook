<script setup lang="ts">
/**
 * A card in detail, open on any tab with `?card=<task id>`: status and key, inline title, list,
 * assignee, deadline, start, priority, milestone and labels, the proof, the description, the
 * checklist, recent comments and the time logged (start a timer or log time). Finishing, checking
 * and commenting happen in Tasks (one click away), where the task's own rules live.
 */
import { AlarmClock, CalendarRange, CheckCircle2, CircleDashed, ExternalLink, Flag, Image, Layers, MessageSquare, Pencil, Play, Plus, Square, Tag, Timer, UserRound, X } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DatePicker from "@/components/DatePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import ImageLightbox from "@/components/ImageLightbox.vue";
import MarkdownView from "@/components/MarkdownView.vue";
import MultiSelect from "@/components/MultiSelect.vue";
import PersonCell from "@/components/PersonCell.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { moveCard, startTimer, stopTimer, updateCard, useCard, useCompanyId, useRefreshProjects, useTimers } from "../api";
import { colorVar, hhmm, TASK_TONE, tint } from "../lib";
import type { CardDetail, ProjectDetail, TaskPriority } from "../types";
import LogTimeDialog from "./LogTimeDialog.vue";

const props = defineProps<{ project: ProjectDetail }>();

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const companyId = useCompanyId();
const refresh = useRefreshProjects();

const taskId = computed(() => Number(route.query.card) || null);
const query = useCard(() => props.project.id, taskId);
const card = computed<CardDetail | null>(() => query.data.value ?? null);
const caps = computed(() => props.project.capabilities);
const canEditBoard = computed(() => caps.value.edit_cards);
const canEditTask = computed(() => !!card.value?.can_edit_task && card.value.status !== "done" && card.value.status !== "cancelled");

const title = ref("");
const editingTitle = ref(false);
const description = ref("");
const editingDescription = ref(false);
const logging = ref(false);
const lightbox = ref(false);
const saving = ref(false);

watch(card, (value) => {
  if (!value) return;
  title.value = value.title;
  description.value = value.description;
});
function close(): void {
  const { card: _card, ...rest } = route.query;
  void router.replace({ query: rest });
}

watch(taskId, () => {
  editingTitle.value = false;
  editingDescription.value = false;
});

async function save(body: Parameters<typeof updateCard>[3], message?: string): Promise<void> {
  if (!card.value) return;
  saving.value = true;
  try {
    await updateCard(companyId.value, props.project.id, card.value.id, body);
    if (message) toast.success(message);
    await query.refetch();
    void refresh();
  } finally {
    saving.value = false;
  }
}

async function saveTitle(): Promise<void> {
  editingTitle.value = false;
  if (card.value && title.value.trim() && title.value.trim() !== card.value.title) await save({ title: title.value.trim() });
}

async function saveDescription(): Promise<void> {
  editingDescription.value = false;
  if (card.value && description.value !== card.value.description) await save({ description: description.value });
}

const listOptions = computed(() => props.project.lists.map((l) => ({ value: l.id, label: l.name })));
const milestoneOptions = computed(() => props.project.milestones.map((m) => ({ value: m.id, label: m.name })));
const labelOptions = computed(() => props.project.labels.map((l) => ({ value: l.id, label: l.name, color: colorVar(l.color) })));
const priorityOptions = computed(() => (["low", "normal", "high", "urgent"] as const).map((p) => ({ value: p, label: t(`projects.priority.task.${p}`) })));

const listId = computed({
  get: () => card.value?.list_id ?? null,
  set: (value: number | null) => void changeList(value),
});
async function changeList(value: number | null): Promise<void> {
  if (!card.value || value === null || value === card.value.list_id) return;
  try {
    // A position after everything already in the list (positions are floats, about 1024 apart).
    const result = await moveCard(companyId.value, props.project.id, card.value.id, value, Date.now() / 1000);
    toast.success(result.message || t("projects.drawer.moved", { list: props.project.lists.find((l) => l.id === value)?.name ?? "" }));
    await query.refetch();
    void refresh();
  } catch (error) {
    const detail = (error as { detail?: string } | null)?.detail;
    toast.warning(detail ?? t("projects.board.moveFailed"));
  }
}

const milestone = computed({
  get: () => card.value?.milestone_id ?? null,
  set: (value: number | null) => void save({ milestone: value }),
});
const labelIds = computed({
  get: () => card.value?.label_ids ?? [],
  set: (value: number[]) => void save({ label_ids: value }),
});
const priority = computed({
  get: () => (card.value?.priority ?? "normal") as TaskPriority,
  set: (value: TaskPriority | null) => value && void save({ priority: value }),
});
const startOn = computed({
  get: () => card.value?.start_on ?? null,
  set: (value: string | null) => void save({ start_on: value }),
});
const dueDay = computed({
  get: () => (card.value?.due_at ? card.value.due_at.slice(0, 10) : null),
  set: (value: string | null) => {
    if (!value || !card.value) return;
    const time = card.value.due_at ? card.value.due_at.slice(10) : "T18:00:00+05:00";
    void save({ due_at: `${value}${time}` });
  },
});

const checklistDone = computed(() => card.value?.checklist.filter((i) => i.is_done).length ?? 0);
const tasksLink = computed(() => (card.value ? `/c/${company.currentId}/tasks?task=${card.value.id}` : ""));

const timers = useTimers();
const timerRunning = computed(() => !!card.value && (timers.data.value ?? []).some((timer) => timer.person.id === company.current?.membership_id && timer.task?.id === card.value?.id));
async function toggleTimer(): Promise<void> {
  if (!card.value) return;
  try {
    if (timerRunning.value) {
      const entry = await stopTimer(companyId.value);
      toast.success(entry ? t("projects.time.logged", { time: hhmm(entry.minutes) }) : t("projects.time.stopped"));
    } else {
      await startTimer(companyId.value, { task: card.value.id });
      toast.success(t("projects.time.started", { key: card.value.key }));
    }
    await Promise.all([query.refetch(), timers.refetch()]);
    void refresh();
  } catch {
    // The HTTP layer showed why.
  }
}
</script>

<template>
  <UiDrawer query-key="card" size="lg" :title="card?.title ?? t('projects.drawer.title')" hide-header>
    <div class="flex h-full min-h-0 flex-col">
      <div v-if="query.isPending.value" class="flex flex-col gap-4 p-6">
        <SkeletonBlock width="30%" height="12px" />
        <SkeletonBlock width="80%" height="24px" />
        <div class="grid grid-cols-2 gap-3"><SkeletonBlock v-for="n in 6" :key="n" height="52px" radius="10px" /></div>
        <SkeletonBlock height="120px" radius="10px" />
      </div>
      <ErrorState v-else-if="query.isError.value" class="m-6" :error="query.error.value" :retry="() => query.refetch()" />
      <template v-else-if="card">
        <header class="flex flex-col gap-2 border-b border-line px-6 pb-4 pt-5">
          <div class="flex flex-wrap items-center gap-2">
            <span class="rounded-[6px] border border-line bg-surface-2 px-1.5 py-0.5 font-mono text-xs font-semibold text-muted">{{ card.key }}</span>
            <StatusPill size="sm" :tone="TASK_TONE[card.status]" :label="t(`projects.taskStatus.${card.status}`)" />
            <span v-if="card.overdue" class="inline-flex items-center gap-1 text-xs font-semibold text-danger"><AlarmClock :size="13" />{{ t("projects.drawer.overdue") }}</span>
            <span class="flex-1" />
            <IconButton :icon="X" :label="t('projects.drawer.close')" size="sm" @click="close" />
          </div>
          <TextInput v-if="editingTitle" v-model="title" autofocus :maxlength="200" @enter="saveTitle" @blur="saveTitle" />
          <h2 v-else class="group flex items-start gap-2 text-lg font-semibold leading-snug text-fg">
            <span class="min-w-0 flex-1">{{ card.title }}</span>
            <button v-if="canEditTask" type="button" class="mt-1 rounded-[6px] p-1 text-subtle opacity-0 transition-opacity hover:bg-highlight hover:text-fg focus:opacity-100 group-hover:opacity-100" :aria-label="t('projects.drawer.editTitle')" @click="editingTitle = true">
              <Pencil :size="14" />
            </button>
          </h2>
          <p class="text-xs text-muted">
            {{ t("projects.drawer.created", { who: card.created_by?.name ?? "—" }) }} · <RelativeTime :value="card.created_at" />
          </p>
        </header>

        <div class="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <dl class="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
            <div class="field">
              <dt><Layers :size="14" />{{ t("projects.drawer.list") }}</dt>
              <dd><SelectBox v-model="listId" :options="listOptions" size="sm" :disabled="!card.can_move" /></dd>
            </div>
            <div class="field">
              <dt><UserRound :size="14" />{{ t("projects.drawer.assignee") }}</dt>
              <dd class="min-h-8 py-1"><PersonCell :person="card.assignee" size="sm" /></dd>
            </div>
            <div class="field">
              <dt><AlarmClock :size="14" />{{ t("projects.drawer.due") }}</dt>
              <dd><DatePicker v-model="dueDay" size="sm" :disabled="!canEditTask" :placeholder="t('projects.drawer.noDue')" /></dd>
            </div>
            <div class="field">
              <dt><CalendarRange :size="14" />{{ t("projects.drawer.start") }}</dt>
              <dd><DatePicker v-model="startOn" size="sm" clearable :disabled="!canEditBoard && card.assignee?.id !== company.current?.membership_id" :placeholder="t('projects.drawer.noStart')" /></dd>
            </div>
            <div class="field">
              <dt><Flag :size="14" />{{ t("projects.drawer.milestone") }}</dt>
              <dd><SelectBox v-model="milestone" :options="milestoneOptions" size="sm" clearable :disabled="!canEditBoard" :placeholder="t('projects.drawer.noMilestone')" /></dd>
            </div>
            <div class="field">
              <dt><CircleDashed :size="14" />{{ t("projects.drawer.priority") }}</dt>
              <dd><SelectBox v-model="priority" :options="priorityOptions" size="sm" :disabled="!canEditTask" /></dd>
            </div>
            <div class="field sm:col-span-2">
              <dt><Tag :size="14" />{{ t("projects.drawer.labels") }}</dt>
              <dd>
                <MultiSelect v-if="canEditBoard" v-model="labelIds" :options="labelOptions" size="sm" :placeholder="t('projects.drawer.noLabels')" />
                <div v-else class="flex flex-wrap gap-1 py-1">
                  <span v-for="id in card.label_ids" :key="id" class="rounded-full px-2 py-0.5 text-[11px] font-semibold" :style="{ background: tint(project.labels.find((l) => l.id === id)?.color, 18), color: colorVar(project.labels.find((l) => l.id === id)?.color) }">{{ project.labels.find((l) => l.id === id)?.name }}</span>
                  <span v-if="!card.label_ids.length" class="text-sm text-subtle">{{ t("projects.drawer.noLabels") }}</span>
                </div>
              </dd>
            </div>
          </dl>

          <section v-if="card.proof !== 'none'" class="mt-6">
            <h3 class="section-title"><Image :size="14" />{{ t("projects.drawer.proof") }}</h3>
            <button v-if="card.proof_photo" type="button" class="mt-2 block overflow-hidden rounded-[10px] border border-line" @click="lightbox = true">
              <img :src="card.proof_thumb ?? card.proof_photo" alt="" class="max-h-56 w-full object-cover" />
            </button>
            <p v-if="card.proof_text" class="mt-2 rounded-[10px] bg-surface-2 p-3 text-sm text-fg">{{ card.proof_text }}</p>
            <p v-if="!card.proof_photo && !card.proof_text" class="mt-1 text-sm text-muted">{{ t(`projects.drawer.proofNeeded.${card.proof}`) }}</p>
            <ImageLightbox v-if="card.proof_photo" v-model:open="lightbox" :images="[{ src: card.proof_photo, alt: card.title }]" />
          </section>

          <section class="mt-6">
            <div class="flex items-center gap-2">
              <h3 class="section-title flex-1">{{ t("projects.drawer.description") }}</h3>
              <UiButton v-if="canEditTask && !editingDescription" size="sm" variant="ghost" :icon="Pencil" @click="editingDescription = true">{{ t("common.edit") }}</UiButton>
            </div>
            <div v-if="editingDescription" class="mt-2 flex flex-col gap-2">
              <TextArea v-model="description" :rows="5" autofocus :placeholder="t('projects.drawer.descriptionPlaceholder')" />
              <div class="flex gap-2"><UiButton size="sm" variant="primary" :loading="saving" @click="saveDescription">{{ t("common.save") }}</UiButton><UiButton size="sm" variant="ghost" @click="editingDescription = false; description = card.description">{{ t("common.cancel") }}</UiButton></div>
            </div>
            <MarkdownView v-else-if="card.description" :source="card.description" size="sm" class="mt-2" />
            <p v-else class="mt-1 text-sm text-subtle">{{ t("projects.drawer.noDescription") }}</p>
          </section>

          <section v-if="card.checklist.length" class="mt-6">
            <div class="flex items-center gap-3">
              <h3 class="section-title">{{ t("projects.drawer.checklist") }}</h3>
              <ProgressBar :value="checklistDone" :max="card.checklist.length" size="xs" class="flex-1" tone="success" />
              <span class="text-xs tabular-nums text-muted">{{ checklistDone }}/{{ card.checklist.length }}</span>
            </div>
            <ul class="mt-2 flex flex-col gap-1">
              <li v-for="item in card.checklist" :key="item.id" class="flex items-center gap-2 text-sm" :class="item.is_done ? 'text-muted line-through' : 'text-fg'">
                <CheckCircle2 v-if="item.is_done" :size="15" class="shrink-0 text-success" />
                <Square v-else :size="15" class="shrink-0 text-subtle" />
                {{ item.text }}
              </li>
            </ul>
          </section>

          <section class="mt-6">
            <div class="flex items-center gap-2">
              <h3 class="section-title flex-1"><Timer :size="14" />{{ t("projects.drawer.time", { time: hhmm(card.minutes) }) }}</h3>
              <UiButton size="sm" variant="ghost" :icon="Plus" @click="logging = true">{{ t("projects.time.log") }}</UiButton>
              <UiButton v-if="(card.status !== 'done' && card.status !== 'cancelled' || timerRunning) && (card.assignee?.id === company.current?.membership_id || canEditBoard)" size="sm" :variant="timerRunning ? 'primary' : 'secondary'" :icon="timerRunning ? Square : Play" @click="toggleTimer">
                {{ timerRunning ? t("projects.time.stop") : t("projects.time.start") }}
              </UiButton>
            </div>
            <ul v-if="card.time.length" class="mt-2 divide-y divide-line rounded-[10px] border border-line">
              <li v-for="entry in card.time.slice(0, 6)" :key="entry.id" class="flex items-center gap-3 px-3 py-2 text-sm">
                <UserAvatar :name="entry.person.name" :src="entry.person.photo_url" :size="22" />
                <span class="min-w-0 flex-1 truncate text-fg">{{ entry.person.name }}<span v-if="entry.note" class="text-muted"> · {{ entry.note }}</span></span>
                <span class="text-xs text-muted">{{ fmt.day(entry.day, "short") }}</span>
                <span class="w-12 text-right font-semibold tabular-nums text-fg">{{ hhmm(entry.minutes) }}</span>
              </li>
            </ul>
            <p v-else class="mt-1 text-sm text-subtle">{{ t("projects.drawer.noTime") }}</p>
          </section>

          <section class="mt-6">
            <h3 class="section-title"><MessageSquare :size="14" />{{ t("projects.drawer.comments") }}</h3>
            <ul v-if="card.recent_comments.length" class="mt-2 flex flex-col gap-3">
              <li v-for="comment in card.recent_comments" :key="comment.id" class="flex gap-2.5">
                <UserAvatar :name="comment.author?.name ?? '—'" :src="comment.author?.photo_url" :size="26" />
                <div class="min-w-0 flex-1 rounded-[10px] bg-surface-2 px-3 py-2">
                  <p class="text-xs text-muted"><span class="font-semibold text-fg">{{ comment.author?.name }}</span> · <RelativeTime :value="comment.created_at" /></p>
                  <p class="mt-0.5 whitespace-pre-line text-sm text-fg">{{ comment.text }}</p>
                </div>
              </li>
            </ul>
            <EmptyState v-else size="sm" tone="neutral" :title="t('projects.drawer.noComments')" />
          </section>
        </div>

        <footer class="flex shrink-0 flex-wrap items-center gap-2 border-t border-line bg-canvas/60 px-6 py-3">
          <span class="text-xs text-muted">{{ t("projects.drawer.tasksHint") }}</span>
          <span class="flex-1" />
          <UiButton :to="tasksLink" variant="secondary" size="sm" :icon-right="ExternalLink">{{ t("projects.drawer.openTask") }}</UiButton>
        </footer>
        <LogTimeDialog v-model:open="logging" :project="project" :task-id="card.id" :task-key="card.key" @saved="() => query.refetch()" />
      </template>
    </div>
  </UiDrawer>
</template>

<style scoped>
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.field dt {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--c-muted);
}
.section-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
  font-weight: 650;
  color: var(--c-text);
}
</style>
