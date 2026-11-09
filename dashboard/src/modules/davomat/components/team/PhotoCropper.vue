<script setup lang="ts">
/**
 * A square crop of a photo, framed as the round avatar it becomes: drag the picture (or use the
 * arrow keys), zoom with the slider, the wheel or + and −. "Use this photo" draws the square at
 * 512 × 512 as a JPEG and hands it over; nothing is uploaded here.
 */
import { ZoomIn, ZoomOut } from "@lucide/vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";

import { centred, clampOffset, coverScale, sourceSquare, zoomAround } from "./team";

const props = withDefaults(defineProps<{ file: File; frame?: number; output?: number }>(), { frame: 280, output: 512 });
const emit = defineEmits<{ done: [photo: Blob]; cancel: [] }>();

const { t } = useI18n();

const url = ref<string | null>(null);
const image = ref<HTMLImageElement | null>(null);
const natural = ref({ width: 0, height: 0 });
const failed = ref(false);
const busy = ref(false);
const zoom = ref(1);
const offset = ref({ x: 0, y: 0 });

const base = computed(() => (natural.value.width ? coverScale(natural.value.width, natural.value.height, props.frame) : 1));
const scale = computed(() => base.value * zoom.value);

watch(
  () => props.file,
  (file) => {
    if (url.value) URL.revokeObjectURL(url.value);
    failed.value = false;
    natural.value = { width: 0, height: 0 };
    url.value = URL.createObjectURL(file);
  },
  { immediate: true },
);
onBeforeUnmount(() => url.value && URL.revokeObjectURL(url.value));

function loaded(): void {
  const element = image.value;
  if (!element) return;
  natural.value = { width: element.naturalWidth, height: element.naturalHeight };
  zoom.value = 1;
  offset.value = centred(element.naturalWidth, element.naturalHeight, props.frame, base.value);
}

watch(zoom, (next, previous) => {
  const { width, height } = natural.value;
  if (!width) return;
  offset.value = zoomAround(width, height, props.frame, { scale: base.value * previous, ...offset.value }, base.value * next);
});

function moveTo(x: number, y: number): void {
  const { width, height } = natural.value;
  offset.value = clampOffset(width, height, props.frame, scale.value, x, y);
}

let drag: { pointer: number; x: number; y: number; from: { x: number; y: number } } | null = null;

function down(event: PointerEvent): void {
  if (!natural.value.width) return;
  (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
  drag = { pointer: event.pointerId, x: event.clientX, y: event.clientY, from: { ...offset.value } };
}

function move(event: PointerEvent): void {
  if (!drag || drag.pointer !== event.pointerId) return;
  moveTo(drag.from.x + event.clientX - drag.x, drag.from.y + event.clientY - drag.y);
}

function up(event: PointerEvent): void {
  if (drag?.pointer === event.pointerId) drag = null;
}

function wheel(event: WheelEvent): void {
  event.preventDefault();
  zoom.value = Math.min(4, Math.max(1, zoom.value - event.deltaY * 0.002));
}

function key(event: KeyboardEvent): void {
  const step = event.shiftKey ? 40 : 10;
  const moves: Record<string, [number, number]> = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
  const delta = moves[event.key];
  if (delta) {
    event.preventDefault();
    moveTo(offset.value.x + delta[0], offset.value.y + delta[1]);
  } else if (event.key === "+" || event.key === "=") {
    zoom.value = Math.min(4, zoom.value + 0.2);
  } else if (event.key === "-") {
    zoom.value = Math.max(1, zoom.value - 0.2);
  }
}

function use(): void {
  const element = image.value;
  if (!element || !natural.value.width) return;
  busy.value = true;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = props.output;
    canvas.height = props.output;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("no canvas");
    const square = sourceSquare(props.frame, scale.value, offset.value.x, offset.value.y);
    context.imageSmoothingQuality = "high";
    context.drawImage(element, square.sx, square.sy, square.size, square.size, 0, 0, props.output, props.output);
    canvas.toBlob(
      (blob) => {
        busy.value = false;
        if (blob) emit("done", blob);
        else failed.value = true;
      },
      "image/jpeg",
      0.9,
    );
  } catch {
    busy.value = false;
    failed.value = true;
  }
}
</script>

<template>
  <div class="flex flex-col items-center gap-4" data-cropper>
    <p class="max-w-[320px] text-center text-sm text-muted">{{ t("davomat.team.photo.hint") }}</p>
    <div
      class="cropper relative touch-none select-none overflow-hidden rounded-[18px] bg-surface-3 outline-none focus-visible:ring-2 focus-visible:ring-[var(--c-ring)]"
      :style="{ width: `${frame}px`, height: `${frame}px` }"
      tabindex="0"
      role="application"
      :aria-label="t('davomat.team.photo.title')"
      @pointerdown="down"
      @pointermove="move"
      @pointerup="up"
      @pointercancel="up"
      @wheel="wheel"
      @keydown="key"
    >
      <img
        v-if="url && !failed"
        ref="image"
        :src="url"
        alt=""
        draggable="false"
        class="pointer-events-none absolute left-0 top-0 max-w-none origin-top-left"
        :style="{ width: `${natural.width * scale}px`, height: `${natural.height * scale}px`, transform: `translate(${offset.x}px, ${offset.y}px)`, opacity: natural.width ? 1 : 0 }"
        @load="loaded"
        @error="failed = true"
      />
      <span class="cropper-mask pointer-events-none absolute inset-[14px] rounded-full" aria-hidden="true" />
      <p v-if="failed" class="absolute inset-0 grid place-items-center p-6 text-center text-sm text-muted">{{ t("davomat.team.photo.failed") }}</p>
    </div>
    <label class="flex w-full max-w-[280px] items-center gap-3 text-muted">
      <ZoomOut :size="16" aria-hidden="true" />
      <span class="sr-only">{{ t("davomat.team.photo.zoom") }}</span>
      <input v-model.number="zoom" type="range" min="1" max="4" step="0.01" class="cropper-range min-w-0 flex-1" :disabled="!natural.width" />
      <ZoomIn :size="16" aria-hidden="true" />
    </label>
    <div class="flex w-full justify-end gap-2">
      <UiButton variant="ghost" @click="emit('cancel')">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="busy" :disabled="!natural.width || failed" data-use-photo @click="use">{{ t("davomat.team.photo.use") }}</UiButton>
    </div>
  </div>
</template>

<style scoped>
.cropper {
  cursor: grab;
}
.cropper:active {
  cursor: grabbing;
}
/* The round avatar it becomes: a light rim on the photo, the corners dimmed with the overlay token. */
.cropper-mask {
  box-shadow:
    0 0 0 2px color-mix(in srgb, white 72%, transparent),
    0 0 0 999px var(--c-overlay);
}
.cropper-range {
  accent-color: var(--c-primary);
}
</style>
