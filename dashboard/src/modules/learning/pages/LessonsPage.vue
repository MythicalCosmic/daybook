<script setup lang="ts">
/**
 * Lessons: every video lesson with its source, length, topics and how many watched it (in the
 * viewer's branches). `?new=1` asks for a title and opens the editor.
 */
import { MonitorPlay, Plus, Video as VideoIcon } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useDataTable } from "@/components/useDataTable";
import { rs, useRouteState } from "@/lib/useRouteState";
import { topicColor } from "@/modules/knowledge/topics";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { learningApi, useLessons, useRefresh, useTopics } from "../api";
import { clock, STATUS_TONES, VIDEO_TONES } from "../lib";
import type { LessonRow, LessonSource, Status } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const cid = useCompanyId();
const router = useRouter();
const refresh = useRefresh();

const search = useRouteState("q", rs.string(""));
const status = useRouteState("status", rs.string(""));
const topic = useRouteState("topic", rs.string(""));
const creating = useRouteState("new", rs.boolean(false));
const canManage = computed(() => company.can("learning.manage"));
const params = computed(() => ({ q: search.value || undefined, status: status.value || undefined, topic: topic.value || undefined }));
const lessons = useLessons(params);
const topics = useTopics();
const table = useDataTable({ id: "learning.lessons", pageSize: 100 });

const statusOptions = computed(() => [
  { value: "" as const, label: t("learning.courses.live") },
  ...(["draft", "published", "archived"] as const).map((value) => ({ value, label: t(`learning.status.${value}`) })),
]);
const statusModel = computed({ get: () => status.value as "" | Status, set: (value: "" | Status) => (status.value = value) });
const topicOptions = computed(() => (topics.data.value ?? []).map((row) => ({ value: String(row.id), label: row.name, color: topicColor(row.color) })));
const topicModel = computed({ get: () => topic.value || null, set: (value: string | null) => (topic.value = value ?? "") });

const columns = computed<TableColumn<LessonRow>[]>(() => [
  { id: "title", header: t("learning.col.lesson"), minWidth: 260, sticky: true },
  { id: "status", header: t("learning.col.status"), width: 130 },
  { id: "duration_seconds", header: t("learning.col.length"), numeric: true, width: 100 },
  { id: "topics", header: t("learning.col.topics"), minWidth: 180, value: (row) => row.topics.map((item) => item.name).join(", ") },
  { id: "viewers", header: t("learning.col.watched"), width: 150, value: (row) => row.viewers.watched },
]);
const filtered = computed(() => Boolean(search.value || status.value || topic.value));

const title = ref("");
const source = ref<LessonSource>("upload");
const busy = ref(false);
watch(creating, (value) => {
  if (value) {
    title.value = "";
    source.value = "upload";
  }
});
const sources = computed(() => [
  { value: "upload" as const, label: t("learning.lesson.upload"), icon: VideoIcon },
  { value: "youtube" as const, label: "YouTube", icon: MonitorPlay },
]);
async function create(): Promise<void> {
  if (!title.value.trim()) return;
  busy.value = true;
  try {
    const lesson = await learningApi.createLesson(cid.value, { title: title.value.trim(), source: source.value });
    refresh();
    creating.value = false;
    void router.push(`/c/${company.currentId}/learning/lessons/${lesson.id}`);
  } finally {
    busy.value = false;
  }
}

function open(row: LessonRow): void {
  void router.push(`/c/${company.currentId}/learning/lessons/${row.id}`);
}
</script>

<template>
  <div>
    <PageHeader :title="t('learning.nav.lessons')" :description="t('learning.lessons.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="creating = true">{{ t("learning.lessons.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="lessons.data.value && !lessons.data.value.length && !filtered" class="ui-card">
      <EmptyState :icon="VideoIcon" :title="t('learning.lessons.emptyTitle')" :description="t('learning.lessons.emptyBody')">
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="creating = true">{{ t("learning.lessons.new") }}</UiButton>
      </EmptyState>
    </div>
    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="lessons.data.value"
      :total="lessons.data.value?.length"
      row-key="id"
      :loading="lessons.isPending.value"
      :fetching="lessons.isFetching.value"
      :error="lessons.error.value"
      :retry="() => lessons.refetch()"
      clickable
      :filtered="filtered"
      csv-name="lessons"
      @row-click="open"
      @clear-filters="
        search = '';
        status = '';
        topic = '';
      "
    >
      <template #toolbar>
        <div class="flex flex-wrap items-center gap-2">
          <TextInput v-model="search" :debounce="300" type="search" size="sm" class="w-full sm:w-64" :placeholder="t('learning.lessons.search')" clearable />
          <SegmentedControl v-model="statusModel" :options="statusOptions" size="sm" />
          <SelectBox v-model="topicModel" size="sm" class="w-52" :options="topicOptions" clearable :placeholder="t('learning.lessons.anyTopic')" />
        </div>
      </template>
      <template #cell-title="{ row }">
        <div class="flex min-w-0 items-center gap-2.5">
          <span class="grid size-8 shrink-0 place-items-center rounded-[8px] bg-surface-2 text-muted">
            <MonitorPlay v-if="row.source === 'youtube'" :size="16" aria-hidden="true" />
            <VideoIcon v-else :size="16" aria-hidden="true" />
          </span>
          <span class="min-w-0">
            <span class="block truncate font-medium text-fg">{{ row.emoji ? `${row.emoji} ` : "" }}{{ row.title }}</span>
            <StatusPill v-if="row.video_state && row.video_state !== 'ready'" size="sm" variant="plain" :tone="VIDEO_TONES[row.video_state]" :label="t(`learning.video.${row.video_state}`)" />
          </span>
        </div>
      </template>
      <template #cell-status="{ row }">
        <StatusPill :tone="STATUS_TONES[row.status]" :label="t(`learning.status.${row.status}`)" size="sm" />
      </template>
      <template #cell-duration_seconds="{ row }">{{ row.duration_seconds ? clock(row.duration_seconds) : "—" }}</template>
      <template #cell-topics="{ row }">
        <div class="flex flex-wrap gap-1">
          <span v-for="item in row.topics" :key="item.id" class="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs text-fg">
            <span class="size-2 rounded-full" :style="{ background: topicColor(item.color) }" aria-hidden="true" />{{ item.name }}
          </span>
        </div>
      </template>
      <template #cell-viewers="{ row }">
        <span class="text-sm text-fg tabular-nums">{{ t("learning.lessons.watchedCount", { watched: row.viewers.watched, watching: row.viewers.watching }) }}</span>
      </template>
    </DataTable>

    <UiDialog v-model:open="creating" :title="t('learning.lessons.new')" :description="t('learning.lessons.newHint')" size="sm">
      <form class="flex flex-col gap-4" @submit.prevent="create">
        <FormField :label="t('learning.lesson.name')" required>
          <TextInput v-model="title" :maxlength="200" autofocus :placeholder="t('learning.lesson.namePlaceholder')" />
        </FormField>
        <FormField :label="t('learning.lesson.source')">
          <SegmentedControl v-model="source" :options="sources" block />
        </FormField>
      </form>
      <template #footer>
        <UiButton variant="ghost" @click="creating = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="busy" :disabled="!title.trim()" @click="create">{{ t("common.create") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
