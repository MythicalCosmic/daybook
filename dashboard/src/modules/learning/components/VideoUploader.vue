<script setup lang="ts">
/**
 * The lesson editor's video upload: a file goes up in 8 MB pieces with a progress bar; a dropped
 * connection carries on from where the server stands, and an upload interrupted by closing the
 * page resumes when the same file is picked again (this browser remembers which upload it was).
 * When every piece is in, the media worker makes the MP4 and the poster.
 */
import { CloudUpload, RotateCcw, X } from "@lucide/vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import FileDrop from "@/components/FileDrop.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import UiButton from "@/components/UiButton.vue";
import { useCompanyId } from "@/stores/company";

import { learningApi } from "../api";
import { bytes } from "../lib";
import type { Video } from "../types";
import { MAX_VIDEO_BYTES, sendFile, VIDEO_ACCEPT, type UploadApi, type UploadProgress } from "../upload";

const props = defineProps<{ disabled?: boolean }>();
const emit = defineEmits<{ uploaded: [video: Video] }>();

const { t, locale } = useI18n();
const cid = useCompanyId();
const files = ref<File[]>([]);
const progress = ref<UploadProgress | null>(null);
const busy = ref(false);
const failed = ref<string | null>(null);
const pending = ref<{ video: Video; file: File } | null>(null);
let controller: AbortController | null = null;

const api: UploadApi = {
  startUpload: (input) => learningApi.startUpload(cid.value, input),
  chunk: (id, offset, piece, signal) => learningApi.chunk(cid.value, id, offset, piece, signal),
  video: (id) => learningApi.video(cid.value, id),
  finishUpload: (id) => learningApi.finishUpload(cid.value, id),
};

/** Which upload a file was (to resume it after the page was closed), per company. */
const memoryKey = (file: File) => `learning.upload.${cid.value}.${file.name}.${file.size}.${file.lastModified}`;
function remember(file: File, video: Video | null): void {
  try {
    if (video) localStorage.setItem(memoryKey(file), String(video.id));
    else localStorage.removeItem(memoryKey(file));
  } catch {
    // Private mode: resuming after a reload just isn't offered.
  }
}
async function remembered(file: File): Promise<Video | null> {
  let id: number | null = null;
  try {
    id = Number(localStorage.getItem(memoryKey(file))) || null;
  } catch {
    return null;
  }
  if (!id) return null;
  try {
    const video = await learningApi.video(cid.value, id);
    return video.state === "uploading" && video.original_bytes === file.size ? video : null;
  } catch {
    return null;
  }
}

async function run(file: File, existing: Video | null): Promise<void> {
  busy.value = true;
  failed.value = null;
  controller = new AbortController();
  let video = existing;
  try {
    video ??= await api.startUpload({ name: file.name, size: file.size });
    remember(file, video);
    pending.value = { video, file };
    const finished = await sendFile(api, video, file, { signal: controller.signal, onProgress: (value) => (progress.value = value) });
    remember(file, null);
    pending.value = null;
    emit("uploaded", finished);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    failed.value = isApiError(error) && error.detail ? error.detail : t("learning.upload.interrupted");
  } finally {
    busy.value = false;
    controller = null;
  }
}

watch(files, async (picked) => {
  const file = picked[0];
  if (!file) return;
  files.value = [];
  progress.value = { sent: 0, total: file.size, percent: 0 };
  await run(file, await remembered(file));
});

function resume(): void {
  if (pending.value) void run(pending.value.file, pending.value.video);
}

function cancel(): void {
  controller?.abort();
  progress.value = null;
  pending.value = null;
}

onBeforeUnmount(() => controller?.abort());

const sentText = computed(() =>
  progress.value ? t("learning.upload.progress", { sent: bytes(progress.value.sent, locale.value), total: bytes(progress.value.total, locale.value) }) : "",
);
</script>

<template>
  <div class="flex flex-col gap-3">
    <div v-if="busy || (progress && pending)" class="ui-card flex flex-col gap-2 p-4" aria-live="polite">
      <div class="flex items-center gap-3">
        <CloudUpload :size="18" class="shrink-0 text-accent" aria-hidden="true" />
        <p class="min-w-0 flex-1 truncate text-sm font-medium text-fg">{{ pending?.file.name }}</p>
        <UiButton v-if="busy" size="sm" variant="ghost" :icon="X" @click="cancel">{{ t("common.cancel") }}</UiButton>
      </div>
      <ProgressBar :value="progress?.percent ?? 0" :max="100" size="sm" :label="t('learning.upload.label')" show-value />
      <p class="text-xs text-muted tabular-nums">{{ sentText }}</p>
    </div>
    <InlineAlert v-if="failed" tone="danger" :title="failed">
      <UiButton v-if="pending" size="sm" variant="secondary" :icon="RotateCcw" @click="resume">{{ t("learning.upload.resume") }}</UiButton>
    </InlineAlert>
    <FileDrop
      v-if="!busy"
      v-model="files"
      :accept="VIDEO_ACCEPT"
      :max-size="MAX_VIDEO_BYTES"
      :max-files="1"
      :disabled="props.disabled"
      :title="t('learning.upload.title')"
      :hint="t('learning.upload.hint')"
    />
  </div>
</template>
