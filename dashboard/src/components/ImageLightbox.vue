<script setup lang="ts">
/**
 * Full-screen photos (task proofs, Z-reports, receipts): ← → between them, zoom with the wheel,
 * double-click, + and −, drag to pan while zoomed, Esc to close, thumbnails below, download.
 *
 *   <ImageLightbox v-model:open="open" v-model:index="index" :images="[{ src, caption: 'CHL-1042 · Z-report' }]" />
 */
import { ChevronLeft, ChevronRight, Download, Minus, Plus, RotateCcw, X } from "@lucide/vue";
import { DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle, VisuallyHidden } from "reka-ui";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

export interface LightboxImage {
  src: string;
  alt?: string;
  caption?: string;
  thumb?: string;
  /** Offer a download of this URL (default: the image itself). */
  download?: string | false;
}

const open = defineModel<boolean>("open", { default: false });
const index = defineModel<number>("index", { default: 0 });

const props = defineProps<{ images: LightboxImage[]; title?: string }>();

const { t } = useI18n();
const scale = ref(1);
const offset = ref({ x: 0, y: 0 });
const loaded = ref(false);
let drag: { x: number; y: number; ox: number; oy: number } | null = null;
const dragging = ref(false);

const current = computed(() => props.images[Math.min(Math.max(0, index.value), props.images.length - 1)] ?? null);
const many = computed(() => props.images.length > 1);

function reset(): void {
  scale.value = 1;
  offset.value = { x: 0, y: 0 };
}

watch([index, open], () => {
  reset();
  loaded.value = false;
});

function go(step: number): void {
  if (!many.value) return;
  index.value = (index.value + step + props.images.length) % props.images.length;
}

function zoom(factor: number): void {
  scale.value = Math.min(5, Math.max(1, scale.value * factor));
  if (scale.value === 1) offset.value = { x: 0, y: 0 };
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "ArrowRight") go(1);
  else if (event.key === "ArrowLeft") go(-1);
  else if (event.key === "+" || event.key === "=") zoom(1.4);
  else if (event.key === "-") zoom(1 / 1.4);
  else if (event.key === "0") reset();
}

function onWheel(event: WheelEvent): void {
  zoom(Math.exp(-event.deltaY * 0.0022));
}

function onDoubleClick(): void {
  if (scale.value > 1) reset();
  else zoom(2.2);
}

function onPointerDown(event: PointerEvent): void {
  if (scale.value <= 1) return;
  drag = { x: event.clientX, y: event.clientY, ox: offset.value.x, oy: offset.value.y };
  dragging.value = true;
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
}

function onPointerMove(event: PointerEvent): void {
  if (!drag) return;
  offset.value = { x: drag.ox + (event.clientX - drag.x) / scale.value, y: drag.oy + (event.clientY - drag.y) / scale.value };
}

function onPointerUp(): void {
  drag = null;
  dragging.value = false;
}

// Swipe left/right on phones when not zoomed.
let swipeX: number | null = null;
function onTouchStart(event: TouchEvent): void {
  swipeX = event.touches.length === 1 && scale.value === 1 ? event.touches[0]!.clientX : null;
}
function onTouchEnd(event: TouchEvent): void {
  if (swipeX === null) return;
  const dx = event.changedTouches[0]!.clientX - swipeX;
  if (Math.abs(dx) > 60) go(dx < 0 ? 1 : -1);
  swipeX = null;
}
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogPortal>
      <DialogOverlay class="anim-overlay fixed inset-0 z-[95] bg-[rgb(12_10_8/0.9)] backdrop-blur-sm" />
      <DialogContent
        class="anim-fade fixed inset-0 z-[96] flex flex-col text-[#f3ece1] outline-none"
        @keydown="onKeydown"
      >
        <VisuallyHidden>
          <DialogTitle>{{ title ?? current?.caption ?? current?.alt ?? t("common.lightbox.title") }}</DialogTitle>
          <DialogDescription>{{ t("common.lightbox.help") }}</DialogDescription>
        </VisuallyHidden>

        <header class="flex shrink-0 items-center gap-2 px-3 pt-[calc(10px+var(--safe-top))] pb-2 md:px-5">
          <p class="min-w-0 flex-1 truncate text-sm font-medium text-[#f3ece1]/85">
            <span v-if="many" class="mr-2 tabular-nums text-[#f3ece1]/55">{{ t("common.lightbox.counter", { n: index + 1, total: images.length }) }}</span>
            {{ current?.caption }}
          </p>
          <div class="flex items-center gap-1 rounded-full bg-white/8 p-1">
            <button type="button" class="lb-btn" :aria-label="t('common.lightbox.zoomOut')" :disabled="scale <= 1" @click="zoom(1 / 1.4)"><Minus :size="16" /></button>
            <span class="w-11 text-center text-xs tabular-nums text-[#f3ece1]/70">{{ Math.round(scale * 100) }}%</span>
            <button type="button" class="lb-btn" :aria-label="t('common.lightbox.zoomIn')" :disabled="scale >= 5" @click="zoom(1.4)"><Plus :size="16" /></button>
            <button type="button" class="lb-btn" :aria-label="t('common.lightbox.reset')" :disabled="scale === 1" @click="reset"><RotateCcw :size="15" /></button>
          </div>
          <a
            v-if="current && current.download !== false"
            :href="current.download || current.src"
            download
            target="_blank"
            rel="noopener"
            class="lb-btn"
            :aria-label="t('common.lightbox.download')"
            ><Download :size="17"
          /></a>
          <button type="button" class="lb-btn" :aria-label="t('shell.overlay.close')" @click="open = false"><X :size="19" /></button>
        </header>

        <div
          class="relative min-h-0 flex-1 touch-none overflow-hidden"
          :class="scale > 1 ? 'cursor-grab active:cursor-grabbing' : 'cursor-zoom-in'"
          @wheel.prevent="onWheel"
          @dblclick="onDoubleClick"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerUp"
          @touchstart.passive="onTouchStart"
          @touchend.passive="onTouchEnd"
          @click.self="scale === 1 && (open = false)"
        >
          <img
            v-if="current"
            :key="current.src"
            :src="current.src"
            :alt="current.alt ?? current.caption ?? ''"
            draggable="false"
            :class="['absolute inset-0 m-auto max-h-full max-w-full select-none object-contain transition-opacity duration-200', loaded ? 'opacity-100' : 'opacity-0']"
            :style="{
              transform: `scale(${scale}) translate3d(${offset.x}px, ${offset.y}px, 0)`,
              transition: dragging ? 'opacity 200ms' : 'transform 180ms var(--ease-out), opacity 200ms',
            }"
            @load="loaded = true"
          />
          <button v-if="many" type="button" class="lb-nav left-3 md:left-5" :aria-label="t('common.lightbox.prev')" @click.stop="go(-1)"><ChevronLeft :size="22" /></button>
          <button v-if="many" type="button" class="lb-nav right-3 md:right-5" :aria-label="t('common.lightbox.next')" @click.stop="go(1)"><ChevronRight :size="22" /></button>
        </div>

        <footer v-if="many" class="no-scrollbar flex shrink-0 justify-center gap-2 overflow-x-auto px-4 pb-[calc(12px+var(--safe-bottom))] pt-3">
          <button
            v-for="(image, i) in images"
            :key="image.src"
            type="button"
            :aria-label="t('common.lightbox.counter', { n: i + 1, total: images.length })"
            :aria-current="i === index ? 'true' : undefined"
            :class="['size-12 shrink-0 overflow-hidden rounded-[8px] ring-2 transition-all', i === index ? 'opacity-100 ring-[#f3ece1]' : 'opacity-50 ring-transparent hover:opacity-80']"
            @click="index = i"
          >
            <img :src="image.thumb ?? image.src" alt="" class="size-full object-cover" loading="lazy" />
          </button>
        </footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style scoped>
.lb-btn {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border-radius: 999px;
  color: rgb(243 236 225 / 0.85);
  transition: background-color var(--dur-press) var(--ease-standard);
}
.lb-btn:hover:not(:disabled) {
  background: rgb(255 255 255 / 0.12);
  color: #fff;
}
.lb-btn:disabled {
  opacity: 0.35;
}
.lb-nav {
  position: absolute;
  top: 50%;
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  border-radius: 999px;
  background: rgb(255 255 255 / 0.1);
  color: #fff;
  transform: translateY(-50%);
  backdrop-filter: blur(6px);
  transition: background-color var(--dur-press) var(--ease-standard);
}
.lb-nav:hover {
  background: rgb(255 255 255 / 0.2);
}
</style>
