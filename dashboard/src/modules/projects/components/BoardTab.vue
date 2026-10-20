<script setup lang="ts">
/**
 * The board (plan §13.3 "Board"): lists as columns with WIP limits, drag between and within lists
 * (optimistic, snaps back on refusal), quick add at the bottom of each list, list menus (rename,
 * limit, delete), and filters in the URL: search, people, labels, milestone, my cards, hide done.
 * Dropping an open card in Done completes it; a card that needs proof (or someone else's) opens
 * instead, so it can be finished properly.
 */
import { Ellipsis, Eye, EyeOff, ListPlus, Pencil, Plus, Search, Trash2, UserRound, X } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import KanbanBoard from "@/components/KanbanBoard.vue";
import type { KanbanColumn, KanbanMove } from "@/components/kanban";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useHotkey } from "@/core/hotkeys";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useSessionStore } from "@/stores/session";

import { deleteList, useBoard, useCompanyId, useMoveCard, useRefreshProjects } from "../api";
import { colorVar, dropPosition, tint } from "../lib";
import type { BoardList, Card, ProjectDetail } from "../types";
import BoardCard from "./BoardCard.vue";
import ListDialog from "./ListDialog.vue";
import QuickAddCard from "./QuickAddCard.vue";

const props = defineProps<{ project: ProjectDetail }>();

const { t } = useI18n();
const router = useRouter();
const session = useSessionStore();
const companyId = useCompanyId();
const confirm = useConfirm();
const refresh = useRefreshProjects();

const board = useBoard(() => props.project.id);
const move = useMoveCard(() => props.project.id);
const skeleton = useDelayedPending(computed(() => board.isPending.value));

const q = useRouteState("q", rs.string());
const people = useRouteState("person", rs.numberList());
const labels = useRouteState("label", rs.numberList());
const milestone = useRouteState("milestone", rs.optionalNumber());
const hideDone = useRouteState("hide_done", rs.boolean(false));
const mine = useRouteState("mine", rs.boolean(false));
const searchEl = ref<InstanceType<typeof TextInput> | null>(null);
const listDialog = ref(false);
const editingList = ref<BoardList | null>(null);

const caps = computed(() => board.data.value?.capabilities ?? props.project.capabilities);
const me = computed(() => session.me?.companies.find((c) => c.id === companyId.value)?.membership_id ?? null);
const doneList = computed(() => board.data.value?.lists.find((l) => l.is_done) ?? null);

const columns = computed<KanbanColumn[]>(() =>
  (board.data.value?.lists ?? [])
    .filter((list) => !(hideDone.value && list.is_done))
    .map((list) => ({ id: String(list.id), title: list.name, wipLimit: list.wip_limit, color: list.is_done ? "var(--c-success)" : undefined })),
);

const cards = computed<Card[]>(() => {
  const needle = q.value.trim().toLowerCase();
  return (board.data.value?.cards ?? [])
    .filter((card) => {
      if (needle && !`${card.key} ${card.title}`.toLowerCase().includes(needle)) return false;
      if (people.value.length && !(card.assignee && people.value.includes(card.assignee.id))) return false;
      if (labels.value.length && !labels.value.some((id) => card.label_ids.includes(id))) return false;
      if (milestone.value && card.milestone_id !== milestone.value) return false;
      if (mine.value && card.assignee?.id !== me.value) return false;
      return true;
    })
    .sort((a, b) => a.position - b.position || a.id - b.id);
});
const filtering = computed(() => !!q.value || people.value.length > 0 || labels.value.length > 0 || !!milestone.value || mine.value);

function canDrop(card: Card, _from: string, to: string): boolean {
  if (!card.can_move) return false;
  if (card.status === "done") return to === String(doneList.value?.id);
  return true;
}

async function onMove(event: KanbanMove<Card>): Promise<void> {
  const listId = Number(event.to);
  const position = dropPosition(event.before, event.after);
  try {
    const result = await move.mutateAsync({ card: event.item, listId, position });
    if (result.message) toast.success(result.message, { description: `${result.card.key} · ${result.card.title}` });
  } catch (error) {
    const code = isApiError(error) ? error.code : null;
    if (code === "needs_proof" || code === "needs_review") {
      toast.warning(isApiError(error) && error.detail ? error.detail : t("projects.board.needsProof"));
      openCard(event.item.id);
    } else {
      toast.error(isApiError(error) && error.detail ? error.detail : t("projects.board.moveFailed"));
    }
  }
}

function openCard(id: number): void {
  void router.replace({ query: { ...router.currentRoute.value.query, card: String(id) } });
}

function onBoardKey(event: KeyboardEvent): void {
  if (event.key !== "Enter") return;
  const el = event.target as HTMLElement | null;
  const key = el?.dataset.cardKey;
  if (key && el?.getAttribute("aria-pressed") !== "true") openCard(Number(key));
}

function togglePerson(id: number): void {
  people.value = people.value.includes(id) ? people.value.filter((p) => p !== id) : [...people.value, id];
}
function toggleLabel(id: number): void {
  labels.value = labels.value.includes(id) ? labels.value.filter((l) => l !== id) : [...labels.value, id];
}
function clearFilters(): void {
  q.value = "";
  people.value = [];
  labels.value = [];
  milestone.value = null;
  mine.value = false;
}

const milestoneOptions = computed(() => (board.data.value?.milestones ?? []).map((m) => ({ value: m.id, label: m.name })));

function listMenu(column: KanbanColumn): MenuEntry[] {
  const list = board.data.value?.lists.find((l) => String(l.id) === column.id);
  if (!list || !caps.value.manage) return [];
  return [
    { label: t("projects.list.edit"), icon: Pencil, description: list.wip_limit ? t("projects.list.wipNow", { n: list.wip_limit }) : t("projects.list.wipNone"), onSelect: () => editList(list) },
    ...(list.is_done ? [] : [{ type: "separator" as const }, { label: t("projects.list.delete"), icon: Trash2, danger: true, onSelect: () => void removeList(list.id, list.name) }]),
  ];
}

async function removeList(id: number, name: string): Promise<void> {
  const answer = await confirm({ title: t("projects.list.deleteTitle", { name }), message: t("projects.list.deleteBody"), tone: "danger", confirmLabel: t("projects.list.delete"), icon: Trash2 });
  if (!answer) return;
  await deleteList(companyId.value, props.project.id, id);
  toast.success(t("projects.list.deleted", { name }));
  void refresh();
}

function addList(): void {
  editingList.value = null;
  listDialog.value = true;
}

function editList(list: BoardList): void {
  editingList.value = list;
  listDialog.value = true;
}

useHotkey("/", () => searchEl.value?.$el?.querySelector("input")?.focus(), { description: "projects.keys.search", group: "page" });
useHotkey("m", () => (mine.value = !mine.value), { description: "projects.keys.mine", group: "page" });
</script>

<template>
  <section class="flex min-w-0 flex-col gap-3" @keydown="onBoardKey">
    <div class="flex flex-wrap items-center gap-2">
      <TextInput ref="searchEl" v-model="q" :icon="Search" size="sm" clearable :placeholder="t('projects.board.search')" class="w-full sm:w-56" />
      <div v-if="board.data.value?.people.length" class="flex items-center -space-x-1.5 rounded-full py-0.5 pl-0.5 pr-1">
        <UiTooltip v-for="person in board.data.value.people.slice(0, 8)" :key="person.id" :content="person.name">
          <button
            type="button"
            :aria-pressed="people.includes(person.id)"
            :aria-label="person.name"
            class="rounded-full ring-2 transition-transform hover:z-10 hover:-translate-y-0.5"
            :class="people.includes(person.id) ? 'z-10 ring-primary' : 'ring-surface'"
            @click="togglePerson(person.id)"
          >
            <UserAvatar :name="person.name" :src="person.photo_url" :size="26" />
          </button>
        </UiTooltip>
      </div>
      <UiButton size="sm" :variant="mine ? 'primary' : 'ghost'" :icon="UserRound" @click="mine = !mine">{{ t("projects.board.mine") }}</UiButton>
      <SelectBox v-if="milestoneOptions.length" v-model="milestone" :options="milestoneOptions" size="sm" clearable :placeholder="t('projects.board.milestone')" class="w-44" />
      <div v-if="board.data.value?.labels.length" class="flex flex-wrap items-center gap-1">
        <button
          v-for="label in board.data.value.labels"
          :key="label.id"
          type="button"
          :aria-pressed="labels.includes(label.id)"
          class="inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs font-semibold transition-colors"
          :style="labels.includes(label.id) ? { background: tint(label.color, 22), borderColor: colorVar(label.color), color: colorVar(label.color) } : undefined"
          :class="!labels.includes(label.id) && 'border-line text-muted hover:bg-highlight'"
          @click="toggleLabel(label.id)"
        >
          <span class="size-2 rounded-full" :style="{ background: colorVar(label.color) }" />{{ label.name }}
        </button>
      </div>
      <UiButton v-if="filtering" size="sm" variant="ghost" :icon="X" @click="clearFilters">{{ t("projects.board.clear") }}</UiButton>
      <span class="flex-1" />
      <UiButton size="sm" variant="ghost" :icon="hideDone ? Eye : EyeOff" @click="hideDone = !hideDone">{{ hideDone ? t("projects.board.showDone") : t("projects.board.hideDone") }}</UiButton>
      <UiButton v-if="caps.manage" size="sm" variant="secondary" :icon="ListPlus" @click="addList">{{ t("projects.list.add") }}</UiButton>
    </div>

    <div v-if="skeleton" class="flex gap-3 overflow-hidden">
      <div v-for="n in 5" :key="n" class="flex w-[288px] shrink-0 flex-col gap-2 rounded-[12px] bg-surface-2/60 p-3">
        <SkeletonBlock width="50%" height="14px" />
        <SkeletonBlock v-for="m in 4 - (n % 3)" :key="m" height="86px" radius="10px" />
      </div>
    </div>
    <ErrorState v-else-if="board.isError.value" :error="board.error.value" :retry="() => board.refetch()" />
    <template v-else-if="board.data.value">
      <EmptyState
        v-if="!board.data.value.cards.length && !caps.edit_cards"
        size="sm"
        tone="neutral"
        :title="t('projects.board.emptyTitle')"
        :description="t('projects.board.emptyReadOnly')"
      />
      <KanbanBoard
        :columns="columns"
        :items="cards"
        :item-key="(card: Card) => card.id"
        :column-of="(card: Card) => String(card.list_id)"
        :can-drop="canDrop"
        :disabled="!caps.edit_cards && !board.data.value.cards.some((c) => c.can_move)"
        height="calc(100dvh - 300px)"
        @move="onMove"
      >
        <template #card="{ item }">
          <div class="w-full" @click="openCard(item.id)">
            <BoardCard :card="item" :labels="board.data.value.labels" />
          </div>
        </template>
        <template #column-actions="{ column }">
          <DropdownMenu v-if="listMenu(column).length" :items="listMenu(column)" width="240px">
            <template #trigger><IconButton :icon="Ellipsis" :label="t('projects.list.menu', { name: column.title })" size="sm" /></template>
          </DropdownMenu>
        </template>
        <template v-if="caps.edit_cards" #quick-add="{ column, close }">
          <QuickAddCard :project="project" :list-id="Number(column.id)" :people="board.data.value.people" @close="close" />
        </template>
        <template #empty="{ column }">
          <span v-if="filtering">{{ t("projects.board.noMatch") }}</span>
          <span v-else-if="board.data.value.lists.find((l) => String(l.id) === column.id)?.is_done">{{ t("projects.board.dropDone") }}</span>
          <span v-else>{{ t("projects.board.emptyList") }}</span>
        </template>
      </KanbanBoard>
    </template>
    <ListDialog v-model:open="listDialog" :project-id="project.id" :list="editingList" />
    <p v-if="caps.edit_cards" class="hidden items-center gap-1.5 text-xs text-subtle md:flex">
      <Plus :size="12" />{{ t("projects.board.hint") }}
    </p>
  </section>
</template>
