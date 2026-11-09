<script setup lang="ts">
/**
 * A lesson: its video (uploaded in pieces with a progress bar, or a YouTube link) with a preview,
 * the notes in the knowledge base's editor (its extension `learning.lesson.notes`), topics and
 * audience, publishing; and "Who watched"
 * (docs/PLAN-LEARNING.md §4.2): everyone it is for, never opened, watching (with the parts they
 * really played) or watched, the time spent, the sessions and when.
 */
import { Archive, AudioLines, Eye, MonitorPlay, RotateCcw, Send, Trash2, Video as VideoIcon, X } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
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
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { topicColor } from "@/lib/topicColors";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { learningApi, useLesson, useRefresh, useTopics, useViewers } from "../api";
import RangesStrip from "../components/RangesStrip.vue";
import VideoUploader from "../components/VideoUploader.vue";
import { clock, STATUS_TONES, VIDEO_TONES, VIEWER_TONES, youtubeEmbed, youtubeId } from "../lib";
import type { LessonDetail, LessonInput, LessonSource, Video, ViewerState } from "../types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const cid = useCompanyId();
const refresh = useRefresh();
const confirm = useConfirm();

const id = computed(() => Number(route.params.lessonId));
// While its video is being made or written down, look again every few seconds.
const making = ref(false);
const lesson = useLesson(id, () => (making.value ? 4000 : false));
const data = computed<LessonDetail | undefined>(() => lesson.data.value);
watch(
  () => [data.value?.video?.state, data.value?.transcription.state] as const,
  ([video, words]) => (making.value = video === "uploading" || video === "processing" || words === "working"),
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
  transcript: "",
});
// The transcript as the server last had it: one written down meanwhile replaces an untouched one.
let loadedTranscript = "";
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
      transcript: value.transcript,
    });
    loadedTranscript = value.transcript;
  },
  { immediate: true },
);
watch(
  () => data.value?.transcript,
  (value) => {
    if (value === undefined || value === loadedTranscript) return;
    if (form.transcript === loadedTranscript) form.transcript = value;
    loadedTranscript = value;
  },
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
// The notes are written in the knowledge base's editor, which that module provides.
const notesContext = computed(() => ({
  html: canManage.value ? form.notes : (data.value?.notes ?? ""),
  editable: canManage.value,
  placeholder: t("learning.lesson.notesPlaceholder"),
  update: (html: string) => (form.notes = html),
  upload: noPictures,
}));

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
  // Only a changed transcript is sent, so saving never undoes one just written down.
  if (form.transcript !== loadedTranscript) input.transcript = form.transcript;
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

// The transcript, written down from the uploaded video ------------------------------------------

const job = computed(() => data.value?.transcription ?? { state: "" as const, done: 0, total: 0, error: "", unavailable: "" as const });
const BLOCKS = new Set(["no_video", "too_long", "ai_off", "no_speech"]);
const FAILURES = new Set(["no_video", "no_sound", "nothing_heard", "audio_unreadable", "speech_unavailable"]);
const failure = computed(() => {
  const code = job.value.error;
  if (code !== "no_video" && BLOCKS.has(code)) return t(`learning.transcript.unavailable.${code}`);
  return t(FAILURES.has(code) ? `learning.transcript.failed.${code}` : "learning.transcript.failed.other");
});
const starting = ref(false);
async function transcribe(): Promise<void> {
  if (form.transcript.trim() || data.value?.transcript.trim()) {
    const ok = await confirm({
      title: t("learning.transcript.replaceTitle"),
      message: t("learning.transcript.replaceBody"),
      confirmLabel: t("learning.transcript.write"),
    });
    if (!ok) return;
  }
  starting.value = true;
  try {
    await learningApi.transcribe(cid.value, id.value);
    refresh();
  } finally {
    starting.value = false;
  }
}
async function stopTranscribing(): Promise<void> {
  await learningApi.stopTranscribing(cid.value, id.value);
  refresh();
}
// "Written down" once, when a job ends with new text (not when someone stops it).
let heardBefore: string | null = null;
watch(
  () => [data.value?.transcription.state, data.value?.transcript] as const,
  ([state, text], [was]) => {
    if (state === "working") heardBefore ??= text ?? "";
    else if (was === "working" && heardBefore !== null && text !== heardBefore) toast.success(t("learning.transcript.done"));
    if (state !== "working") heardBefore = null;
  },
);

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
            <ExtensionSlot name="learning.lesson.notes" as="none" :context="notesContext" />
          </FormField>
          <FormField :label="t('learning.transcript.label')" :hint="t('learning.transcript.hint')" optional>
            <div class="flex min-w-0 flex-col gap-2" data-testid="lesson-transcript">
              <template v-if="canManage && form.source === 'upload' && data.source === 'upload' && data.video">
                <InlineAlert v-if="job.state === 'working'" size="sm" :title="t('learning.transcript.working', { done: job.done, total: job.total })">
                  <p class="text-sm text-muted">{{ t("learning.transcript.workingHint") }}</p>
                  <UiButton class="mt-2" size="sm" variant="secondary" :icon="X" @click="stopTranscribing">{{ t("learning.transcript.stop") }}</UiButton>
                </InlineAlert>
                <template v-else>
                  <InlineAlert v-if="job.state === 'failed'" size="sm" tone="danger" :title="failure" />
                  <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <UiButton size="sm" variant="secondary" :icon="AudioLines" :disabled="!!job.unavailable" :loading="starting" @click="transcribe">
                      {{ t("learning.transcript.write") }}
                    </UiButton>
                    <span v-if="job.unavailable" class="text-xs text-muted">{{ t(`learning.transcript.unavailable.${job.unavailable}`) }}</span>
                  </div>
                </template>
              </template>
              <TextArea
                v-model="form.transcript"
                :rows="4"
                :max-rows="16"
                :maxlength="200000"
                :disabled="!canManage || job.state === 'working'"
                :placeholder="t(form.source === 'upload' ? 'learning.transcript.placeholder' : 'learning.transcript.placeholderTyped')"
              />
            </div>
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
                {{ t("learning.watched.summary", { percent: row.percent, spent: clock(row.spent_seconds), sessions: row.sessions }) }}
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
