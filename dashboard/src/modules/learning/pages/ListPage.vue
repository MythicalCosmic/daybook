<script setup lang="ts">
/**
 * One unchangeable list (O‘zgarmas ro‘yxat): its header (state, teacher, branch, who opened it and
 * when; the chain of lines checked; who sealed it, when, and the start of the seal), the grid of
 * topics × students where a teacher writes who studied what and on what day, every line in order
 * as a bound journal, and a print of it all. Lines are never edited or deleted: a mistake is taken
 * back by a correction, a new visible line with a reason. Sealing is final.
 */
import { CalendarPlus, Check, Ellipsis, GraduationCap, LayoutGrid, ListPlus, Lock, MapPin, NotebookPen, Pencil, Printer, ScrollText, ShieldAlert, ShieldCheck, Trash2, UserPlus } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { learningApi, useApplyList, useRefresh, useStudyList } from "../api";
import CellDialog from "../components/CellDialog.vue";
import ListDialog from "../components/ListDialog.vue";
import ListGrid from "../components/ListGrid.vue";
import ListJournal from "../components/ListJournal.vue";
import ListPrint from "../components/ListPrint.vue";
import RenameDialog, { type RenameTarget } from "../components/RenameDialog.vue";
import StudentsDialog from "../components/StudentsDialog.vue";
import TopicsDialog from "../components/TopicsDialog.vue";
import { cellsOf, LIST_STATE_TONES, progressOf, shortDigest } from "../lists";
import type { StudyListDetail, StudyStudent, StudyTopic } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const cid = useCompanyId();
const confirm = useConfirm();
const apply = useApplyList();
const refresh = useRefresh();

const id = computed(() => Number(route.params.listId));
const list = useStudyList(id);
const data = computed<StudyListDetail | undefined>(() => list.data.value);
const canManage = computed(() => company.can("learning.manage"));
/** Writing, correcting, adding, renaming, sealing: manage, and only while the list is open. */
const canWrite = computed(() => canManage.value && data.value?.state === "open");
const cells = computed(() => cellsOf(data.value?.marks ?? []));
const progress = computed(() => progressOf(data.value ?? { topics: [], students: [], marks: [] }));
const backTo = computed(() => `/c/${company.currentId}/learning/lists`);

const tab = ref<"grid" | "journal">("grid");
const tabs = computed(() => [
  { id: "grid", label: t("learning.lists.tabGrid"), icon: LayoutGrid },
  { id: "journal", label: t("learning.lists.tabJournal"), icon: ScrollText, count: data.value?.marks.length },
]);

// The header's actions ----------------------------------------------------------------------

const addingTopics = ref(false);
const addingStudents = ref(false);
const editingDetails = ref(false);

const moreItems = computed<MenuEntry[]>(() => [
  { label: t("learning.lists.editDetails"), icon: Pencil, onSelect: () => (editingDetails.value = true) },
  ...(data.value && !data.value.marks.length
    ? ([{ type: "separator" }, { label: t("learning.lists.delete"), icon: Trash2, danger: true, onSelect: () => void remove() }] as MenuEntry[])
    : []),
]);

function print(): void {
  window.print();
}

async function seal(): Promise<void> {
  const current = data.value;
  if (!current) return;
  const answer = await confirm({
    title: t("learning.lists.sealTitle"),
    message: t("learning.lists.sealBody"),
    confirmLabel: t("learning.lists.seal"),
    tone: "danger",
    icon: Lock,
    onConfirm: async () => {
      apply(await learningApi.seal(cid.value, current.id));
    },
  });
  if (answer) toast.success(t("learning.lists.sealDone"));
}

async function remove(): Promise<void> {
  const current = data.value;
  if (!current || current.marks.length) return;
  const answer = await confirm({
    title: t("learning.lists.deleteTitle"),
    message: t("learning.lists.deleteBody"),
    confirmLabel: t("learning.lists.delete"),
    tone: "danger",
    onConfirm: () => learningApi.deleteList(cid.value, current.id),
  });
  if (!answer) return;
  toast.success(t("learning.lists.deleted"));
  // Away first, so the refresh doesn't ask for the list that is gone.
  await router.push(backTo.value);
  refresh();
}

// Topics and students -----------------------------------------------------------------------

const renameOpen = ref(false);
const renameTarget = ref<RenameTarget | null>(null);
function editTopic(topic: StudyTopic): void {
  renameTarget.value = { kind: "topic", topic };
  renameOpen.value = true;
}
function editStudent(student: StudyStudent): void {
  renameTarget.value = { kind: "student", student };
  renameOpen.value = true;
}

async function removeTopic(topic: StudyTopic): Promise<void> {
  const answer = await confirm({
    title: t("learning.lists.topic.removeTitle", { n: topic.number }),
    message: t("learning.lists.topic.removeBody", { title: topic.title }),
    confirmLabel: t("learning.lists.topic.remove"),
    tone: "danger",
    onConfirm: async () => {
      apply(await learningApi.removeTopic(cid.value, id.value, topic.id));
    },
  });
  if (answer) toast.success(t("learning.lists.topic.removed"));
}

async function removeStudent(student: StudyStudent): Promise<void> {
  const answer = await confirm({
    title: t("learning.lists.student.removeTitle", { name: student.name }),
    message: t("learning.lists.student.removeBody"),
    confirmLabel: t("learning.lists.student.remove"),
    tone: "danger",
    onConfirm: async () => {
      apply(await learningApi.removeStudent(cid.value, id.value, student.id));
    },
  });
  if (answer) toast.success(t("learning.lists.student.removed"));
}

// A cell ------------------------------------------------------------------------------------

const cellOpen = ref(false);
const cellAt = ref({ topicId: 0, studentId: 0 });
function openCell(topicId: number, studentId: number): void {
  cellAt.value = { topicId, studentId };
  cellOpen.value = true;
}

const emptyGrid = computed(() => {
  const current = data.value;
  if (!current) return null;
  if (!current.topics.length && !current.students.length) return "both";
  if (!current.topics.length) return "topics";
  if (!current.students.length) return "students";
  return null;
});
</script>

<template>
  <div>
    <ErrorState v-if="list.isError.value" :error="list.error.value" :retry="() => list.refetch()" />
    <template v-else-if="!data">
      <SkeletonBlock height="16px" width="120px" class="mb-3" />
      <SkeletonBlock height="28px" width="min(420px, 80%)" class="mb-2" />
      <SkeletonBlock height="18px" width="min(560px, 90%)" class="mb-6" />
      <SkeletonBlock height="52px" radius="12px" class="mb-4" />
      <SkeletonBlock height="360px" radius="12px" />
    </template>
    <template v-else>
      <PageHeader
        v-model:tab="tab"
        :title="data.title"
        :description="data.description || undefined"
        clamp-description
        :back="backTo"
        :back-label="t('learning.nav.lists')"
        :tabs="tabs"
      >
        <template #actions>
          <UiButton variant="secondary" :icon="Printer" data-testid="list-print" @click="print">{{ t("learning.lists.print.button") }}</UiButton>
          <template v-if="canWrite">
            <UiButton variant="secondary" :icon="ListPlus" data-testid="list-add-topics" @click="addingTopics = true">{{ t("learning.lists.addTopics") }}</UiButton>
            <UiButton variant="secondary" :icon="UserPlus" data-testid="list-add-students" @click="addingStudents = true">{{ t("learning.lists.addStudents") }}</UiButton>
            <UiButton variant="primary" :icon="Lock" data-testid="list-seal" @click="seal">{{ t("learning.lists.seal") }}</UiButton>
            <DropdownMenu :items="moreItems" width="220px">
              <template #trigger>
                <IconButton :icon="Ellipsis" variant="secondary" :label="t('common.more')" data-testid="list-more" />
              </template>
            </DropdownMenu>
          </template>
        </template>
        <template #meta>
          <StatusPill :tone="LIST_STATE_TONES[data.state]" :icon="data.state === 'sealed' ? Lock : undefined" :label="t(`learning.lists.state.${data.state}`)" />
          <span v-if="data.teacher" class="inline-flex items-center gap-1.5 text-sm text-muted">
            <GraduationCap :size="15" class="text-subtle" aria-hidden="true" />{{ t("learning.lists.teacherIs", { name: data.teacher }) }}
          </span>
          <span v-if="data.branch" class="inline-flex items-center gap-1.5 text-sm text-muted">
            <MapPin :size="15" class="text-subtle" aria-hidden="true" />{{ data.branch.name }}
          </span>
          <span class="inline-flex items-center gap-1.5 text-sm text-muted">
            <CalendarPlus :size="15" class="text-subtle" aria-hidden="true" />{{
              data.created_by
                ? t("learning.lists.createdBy", { name: data.created_by, day: fmt.instant(data.created_at, "date") })
                : t("learning.lists.createdOn", { day: fmt.instant(data.created_at, "date") })
            }}
          </span>
        </template>
      </PageHeader>

      <InlineAlert v-if="!data.intact" tone="danger" :icon="ShieldAlert" :title="t('learning.lists.brokenTitle')" :description="t('learning.lists.brokenBody')" class="mb-3" />

      <!-- The integrity line, the seal and how much is studied. -->
      <div class="ui-card mb-4 flex flex-wrap items-center gap-x-6 gap-y-2.5 px-4 py-3" data-testid="list-integrity">
        <span v-if="data.intact" class="inline-flex items-center gap-2 text-sm font-medium text-success">
          <ShieldCheck :size="16" class="shrink-0" aria-hidden="true" />
          {{ data.marks.length ? t("learning.lists.intact", { n: data.marks.length }, data.marks.length) : t("learning.lists.intactEmpty") }}
        </span>
        <span v-else class="inline-flex items-center gap-2 text-sm font-semibold text-danger">
          <ShieldAlert :size="16" class="shrink-0" aria-hidden="true" />{{ t("learning.lists.brokenShort") }}
        </span>
        <span v-if="data.state === 'sealed'" class="inline-flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted" data-testid="list-seal-line">
          <Lock :size="15" class="shrink-0 text-accent-fg" aria-hidden="true" />
          <span>{{ t("learning.lists.sealedBy", { name: data.sealed_by || "—", day: data.sealed_at ? fmt.instant(data.sealed_at, "date") : "—" }) }}</span>
          <code class="rounded-[6px] bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-fg dark:bg-surface-3" :title="data.seal_digest">{{ shortDigest(data.seal_digest, 12) }}</code>
        </span>
        <div class="flex min-w-[min(100%,220px)] flex-1 items-center gap-2.5 sm:ml-auto sm:max-w-[340px]">
          <ProgressBar class="flex-1" size="sm" :value="progress.studied" :max="progress.cells || 1" tone="success" :label="t('learning.lists.col.progress')" />
          <span class="shrink-0 text-xs text-muted tabular-nums">{{ t("learning.lists.progress", { studied: progress.studied, cells: progress.cells, percent: progress.percent }) }}</span>
        </div>
      </div>

      <template v-if="tab === 'grid'">
        <div v-if="emptyGrid" class="ui-card">
          <EmptyState :icon="NotebookPen" size="sm" :title="t(`learning.lists.emptyGrid.${emptyGrid}`)" :description="t(`learning.lists.emptyGrid.${emptyGrid}Body`)">
            <template v-if="canWrite">
              <UiButton v-if="emptyGrid !== 'students'" variant="primary" :icon="ListPlus" @click="addingTopics = true">{{ t("learning.lists.addTopics") }}</UiButton>
              <UiButton v-if="emptyGrid !== 'topics'" :variant="emptyGrid === 'students' ? 'primary' : 'secondary'" :icon="UserPlus" @click="addingStudents = true">
                {{ t("learning.lists.addStudents") }}
              </UiButton>
            </template>
          </EmptyState>
        </div>
        <template v-else>
          <ListGrid
            :list="data"
            :cells="cells"
            :progress="progress"
            :can-write="canWrite"
            @open="openCell"
            @edit-topic="editTopic"
            @remove-topic="removeTopic"
            @edit-student="editStudent"
            @remove-student="removeStudent"
          />
          <div class="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted">
            <span class="inline-flex items-center gap-1.5">
              <span class="inline-grid h-4 w-5 place-items-center rounded-[4px] bg-success-soft text-success" aria-hidden="true"><Check :size="10" :stroke-width="3" /></span>
              {{ t("learning.lists.legend.studied") }}
            </span>
            <span class="inline-flex items-center gap-1.5">
              <span class="size-1.5 rounded-full bg-warning" aria-hidden="true" />
              {{ t("learning.lists.legend.corrected") }}
            </span>
            <span v-if="canWrite">{{ t("learning.lists.legend.write") }}</span>
          </div>
        </template>
      </template>
      <ListJournal v-else :list="data" />

      <CellDialog v-model:open="cellOpen" :list="data" :topic-id="cellAt.topicId" :student-id="cellAt.studentId" :can-write="canWrite" />
      <TopicsDialog v-if="canWrite" v-model:open="addingTopics" :list="data" />
      <StudentsDialog v-if="canWrite" v-model:open="addingStudents" :list="data" />
      <RenameDialog v-if="canWrite" v-model:open="renameOpen" :list-id="data.id" :target="renameTarget" />
      <ListDialog v-if="canWrite" v-model:open="editingDetails" :list="data" />
      <ListPrint :list="data" :cells="cells" :progress="progress" />
    </template>
  </div>
</template>
