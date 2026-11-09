<script setup lang="ts">
/**
 * A lesson: its video (uploaded in pieces with a progress bar, or a YouTube link) with a preview,
 * the notes in the knowledge base's editor, topics and audience, publishing; and "Who watched"
 * (docs/PLAN-LEARNING.md §4.2): everyone it is for, never opened, watching (with the parts they
 * really played) or watched, the time spent, the sessions and when.
 */
import { Archive, Eye, MonitorPlay, RotateCcw, Send, Trash2, Video as VideoIcon } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MultiSelect from "@/components/MultiSelect.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import RadioCards from "@/components/RadioCards.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import RichEditor from "@/modules/knowledge/components/editor/RichEditor.vue";
import "@/modules/knowledge/prose.css";
import { topicColor } from "@/modules/knowledge/topics";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { learningApi, useLesson, useRefresh, useTopics, useViewers } from "../api";
import RangesStrip from "../components/RangesStrip.vue";
import VideoUploader from "../components/VideoUploader.vue";
import { clock, STATUS_TONES, VIDEO_TONES, VIEWER_TONES, youtubeEmbed, youtubeId } from "../lib";
import type { LessonDetail, LessonInput, LessonSource, Video, ViewerState } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const cid = useCompanyId();
const refresh = useRefresh();
const confirm = useConfirm();

const id = computed(() => Number(route.params.lessonId));
// While its video is being made, look again every few seconds.
const making = ref(false);
const lesson = useLesson(id, () => (making.value ? 4000 : false));
const data = computed<LessonDetail | undefined>(() => lesson.data.value);
watch(
  () => data.value?.video?.state,
  (state) => (making.value = state === "uploading" || state === "processing"),
  { immediate: true },
);
const canManage = computed(() => company.can("learning.manage"));
const tab = ref<"details" | "viewers">("details");
const viewers = useViewers(id, computed(() => tab.value === "viewers"));
const topics = useTopics();
const tabs = computed(() => [
  { id: "details", label: t("learning.lesson.tabDetails") },
  { id: "viewers", label: t("learning.lesson.tabViewers"), count: data.value ? data.value.viewers.watched + data.value.viewers.watching : undefined },
]);

const form = reactive({
  title: "",
  emoji: "",
  summary: "",
  notes: "",
  source: "upload" as LessonSource,
  youtube: "",
  topic_ids: [] as number[],
  audience: "all" as "all" | "positions",
  position_ids: [] as number[],
});
watch(
  () => data.value?.id,
  () => {
    const value = data.value;
    if (!value) return;
    Object.assign(form, {
      title: value.title,
      emoji: value.emoji,
      summary: value.summary,
      notes: value.notes,
      source: value.source,
      youtube: value.youtube_id,
      topic_ids: value.topics.map((row) => row.id),
      audience: value.audience_all ? "all" : "positions",
      position_ids: value.positions.map((row) => row.id),
    });
  },
  { immediate: true },
);
const sources = computed(() => [
  { value: "upload" as const, label: t("learning.lesson.upload"), icon: VideoIcon },
  { value: "youtube" as const, label: "YouTube", icon: MonitorPlay },
]);
const audienceOptions = computed(() => [
  { value: "all" as const, label: t("learning.audience.all"), description: t("learning.audience.allLesson") },
  { value: "positions" as const, label: t("learning.audience.positions"), description: t("learning.audience.positionsHint") },
]);
const topicOptions = computed(() => (topics.data.value ?? []).map((row) => ({ value: row.id, label: row.name, color: topicColor(row.color) })));
const previewId = computed(() => (form.source === "youtube" ? youtubeId(form.youtube) : null));
const badLink = computed(() => form.source === "youtube" && form.youtube.trim() !== "" && !previewId.value);

async function noPictures(): Promise<{ id: number; url: string }> {
  toast.error(t("learning.lesson.noPictures"));
  throw new Error("pictures belong on pages");
}

const saving = ref(false);
async function save(): Promise<void> {
  saving.value = true;
  const input: LessonInput = {
    title: form.title.trim(),
    emoji: form.emoji.trim(),
    summary: form.summary,
    notes: form.notes,
    source: form.source,
    topic_ids: form.topic_ids,
    audience_all: form.audience === "all",
    position_ids: form.audience === "all" ? [] : form.position_ids,
  };
  if (form.source === "youtube") input.youtube = form.youtube.trim();
  try {
    await learningApi.updateLesson(cid.value, id.value, input);
    toast.success(t("learning.saved"));
    refresh();
  } finally {
    saving.value = false;
  }
}

async function uploaded(video: Video): Promise<void> {
  await learningApi.updateLesson(cid.value, id.value, { source: "upload", video_id: video.id });
  toast.success(t("learning.upload.done"));
  refresh();
}

async function act(action: "publish" | "archive" | "restore"): Promise<void> {
  await learningApi.lessonAction(cid.value, id.value, action);
  toast.success(t(`learning.lesson.done.${action}`));
  refresh();
}

async function remove(): Promise<void> {
  const ok = await confirm({ title: t("learning.lesson.deleteTitle"), message: t("learning.lesson.deleteBody"), confirmLabel: t("common.delete"), tone: "danger" });
  if (!ok) return;
  await learningApi.deleteLesson(cid.value, id.value);
  refresh();
  void router.push(`/c/${company.currentId}/learning/lessons`);
}

// Who watched ---------------------------------------------------------------------------------

const filter = ref<"all" | ViewerState>("all");
const rows = computed(() => (viewers.data.value?.results ?? []).filter((row) => filter.value === "all" || row.state === filter.value));
const viewerOptions = computed(() => {
  const counts = viewers.data.value?.counts;
  return [
    { value: "all" as const, label: t("common.all"), count: viewers.data.value?.results.length },
    { value: "watching" as const, label: t("learning.watched.watching"), count: counts?.watching },
    { value: "never" as const, label: t("learning.watched.never"), count: counts?.never },
    { value: "watched" as const, label: t("learning.watched.watched"), count: counts?.watched },
  ];
});
</script>

<template>
  <div>
    <ErrorState v-if="lesson.isError.value" :error="lesson.error.value" :retry="() => lesson.refetch()" />
    <template v-else-if="!data">
      <SkeletonBlock height="72px" radius="12px" class="mb-4" />
      <SkeletonBlock height="280px" radius="12px" />
    </template>
    <template v-else>
      <PageHeader v-model:tab="tab" :title="`${data.emoji ? `${data.emoji} ` : ''}${data.title}`" :back="`/c/${company.currentId}/learning/lessons`" :back-label="t('learning.nav.lessons')" :tabs="tabs">
        <template #actions>
          <StatusPill :tone="STATUS_TONES[data.status]" :label="t(`learning.status.${data.status}`)" />
          <template v-if="canManage">
            <UiButton v-if="data.status === 'draft'" variant="primary" :icon="Send" @click="act('publish')">{{ t("learning.lesson.publish") }}</UiButton>
            <UiButton v-if="data.status === 'published'" variant="secondary" :icon="Archive" @click="act('archive')">{{ t("learning.lesson.archive") }}</UiButton>
            <UiButton v-if="data.status === 'archived'" variant="secondary" :icon="RotateCcw" @click="act('restore')">{{ t("learning.lesson.restore") }}</UiButton>
            <UiButton v-if="!data.courses.length" variant="ghost" :icon="Trash2" @click="remove">{{ t("common.delete") }}</UiButton>
          </template>
        </template>
      </PageHeader>

      <div v-if="tab === 'details'" class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
        <form class="ui-card flex min-w-0 flex-col gap-5 p-5" @submit.prevent="save">
          <div class="grid gap-4 sm:grid-cols-[6rem_minmax(0,1fr)]">
            <FormField :label="t('learning.course.emoji')">
              <TextInput v-model="form.emoji" :maxlength="16" :disabled="!canManage" />
            </FormField>
            <FormField :label="t('learning.lesson.name')" required>
              <TextInput v-model="form.title" :maxlength="200" :disabled="!canManage" />
            </FormField>
          </div>
          <FormField :label="t('learning.lesson.summary')" :hint="t('learning.lesson.summaryHint')" optional :count="form.summary.length" :max="300">
            <TextInput v-model="form.summary" :maxlength="300" :disabled="!canManage" />
          </FormField>

          <FormField :label="t('learning.lesson.source')">
            <SegmentedControl v-model="form.source" :options="sources" :disabled="!canManage" />
          </FormField>
          <template v-if="form.source === 'upload'">
            <InlineAlert v-if="data.video?.state === 'failed'" tone="danger" :title="t('learning.video.failed')" :description="data.video.error" />
            <InlineAlert v-else-if="data.video && data.video.state !== 'ready'" tone="info" :title="t(`learning.video.${data.video.state}`)" :description="t('learning.video.processingHint')" />
            <VideoUploader v-if="canManage" @uploaded="uploaded" />
          </template>
          <FormField v-else :label="t('learning.lesson.youtube')" :hint="t('learning.lesson.youtubeHint')" :error="badLink ? t('learning.lesson.badLink') : null">
            <TextInput v-model="form.youtube" type="url" :placeholder="'https://youtu.be/…'" :invalid="badLink" :disabled="!canManage" />
          </FormField>

          <FormField :label="t('learning.lesson.notes')" :hint="t('learning.lesson.notesHint')">
            <RichEditor v-if="canManage" v-model="form.notes" :upload="noPictures" :placeholder="t('learning.lesson.notesPlaceholder')" />
            <!-- eslint-disable-next-line vue/no-v-html -- notes are cleaned by the server (knowledge sanitizer) -->
            <div v-else class="kb-prose text-sm" v-html="data.notes" />
          </FormField>
          <FormField :label="t('learning.lesson.topics')" :hint="t('learning.lesson.topicsHint')" optional>
            <MultiSelect v-model="form.topic_ids" :options="topicOptions" :placeholder="t('learning.lesson.pickTopics')" display="chips" :disabled="!canManage" />
          </FormField>
          <FormField :label="t('learning.course.audience')">
            <RadioCards v-model="form.audience" :options="audienceOptions" :disabled="!canManage" />
          </FormField>
          <FormField v-if="form.audience === 'positions'" :label="t('learning.course.positions')" required>
            <PositionPicker v-model="form.position_ids" multiple :disabled="!canManage" />
          </FormField>
          <div v-if="canManage">
            <UiButton type="submit" variant="primary" :loading="saving" :disabled="!form.title.trim() || badLink">{{ t("common.save") }}</UiButton>
          </div>
        </form>

        <aside class="flex min-w-0 flex-col gap-4">
          <section class="ui-card overflow-hidden" :aria-label="t('learning.lesson.preview')">
            <div class="aspect-video w-full bg-surface-2">
              <iframe
                v-if="previewId"
                :src="youtubeEmbed(previewId)"
                class="size-full"
                :title="data.title"
                allow="encrypted-media; picture-in-picture; fullscreen"
                referrerpolicy="strict-origin-when-cross-origin"
                loading="lazy"
              />
              <video
                v-else-if="form.source === 'upload' && data.video?.url"
                :src="data.video.url"
                :poster="data.video.poster_url ?? undefined"
                class="size-full bg-black"
                controls
                playsinline
                preload="metadata"
              />
              <div v-else class="grid size-full place-items-center text-muted"><VideoIcon :size="32" aria-hidden="true" /></div>
            </div>
            <dl class="grid grid-cols-2 gap-2 p-4 text-sm">
              <dt class="text-muted">{{ t("learning.lesson.length") }}</dt>
              <dd class="text-right tabular-nums text-fg">{{ data.duration_seconds ? clock(data.duration_seconds) : "—" }}</dd>
              <template v-if="data.video">
                <dt class="text-muted">{{ t("learning.lesson.videoState") }}</dt>
                <dd class="text-right"><StatusPill size="sm" :tone="VIDEO_TONES[data.video.state]" :label="t(`learning.video.${data.video.state}`)" /></dd>
                <template v-if="data.video.height">
                  <dt class="text-muted">{{ t("learning.lesson.quality") }}</dt>
                  <dd class="text-right tabular-nums text-fg">{{ data.video.height }}p</dd>
                </template>
              </template>
              <dt class="text-muted">{{ t("learning.lesson.inCourses") }}</dt>
              <dd class="text-right text-fg">{{ data.courses.length ? data.courses.map((row) => row.name).join(", ") : "—" }}</dd>
            </dl>
          </section>
        </aside>
      </div>

      <section v-else class="flex flex-col gap-3">
        <SegmentedControl v-model="filter" :options="viewerOptions" size="sm" />
        <template v-if="viewers.isPending.value">
          <SkeletonBlock v-for="n in 5" :key="n" height="52px" radius="10px" />
        </template>
        <ErrorState v-else-if="viewers.isError.value" compact :error="viewers.error.value" :retry="() => viewers.refetch()" />
        <div v-else-if="!rows.length" class="ui-card">
          <EmptyState size="sm" :icon="Eye" :title="t('learning.watched.empty')" />
        </div>
        <ul v-else class="ui-card flex flex-col divide-y divide-line">
          <li v-for="row in rows" :key="row.member.id" class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
            <PersonCell :person="row.member" :subtitle="[row.member.position, row.member.branch].filter(Boolean).join(' · ') || null" link class="min-w-0 flex-1 basis-48" />
            <div class="flex w-full flex-col gap-1 sm:w-64">
              <RangesStrip :ranges="row.ranges" :duration="viewers.data.value?.duration_seconds ?? 0" :percent="row.percent" />
              <span class="text-xs text-muted tabular-nums">
                {{ t("learning.watched.summary", { percent: row.percent, spent: fmt.duration(Math.round(row.spent_seconds / 60)), sessions: row.sessions }) }}
              </span>
            </div>
            <div class="flex w-36 flex-col items-start gap-0.5">
              <StatusPill size="sm" :tone="VIEWER_TONES[row.state]" :label="t(`learning.watched.${row.state}`)" />
              <RelativeTime v-if="row.completed_at || row.last_at" :value="(row.completed_at ?? row.last_at)!" class="text-[11px] text-subtle" />
            </div>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
