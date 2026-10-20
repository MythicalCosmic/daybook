<script setup lang="ts">
/**
 * A phone sheet that slides up from the bottom (320 ms), with a grab handle you can drag down to
 * close. Drawers and dialogs become this on phones. Respects the bottom safe area.
 */
import { DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle, VisuallyHidden } from "reka-ui";
import { computed, ref, watch } from "vue";

const open = defineModel<boolean>("open", { default: false });

const props = withDefaults(
  defineProps<{
    title?: string;
    description?: string;
    /** Visually hide the header (the title stays for screen readers). */
    hideHeader?: boolean;
    /** Allow drag and outside click to close. */
    dismissable?: boolean;
    /** Fill most of the screen even with little content (lists, palettes). */
    tall?: boolean;
    /** No body padding: the content brings its own (drawers rendered as sheets). */
    flush?: boolean;
  }>(),
  { title: "", description: undefined, hideHeader: false, dismissable: true, tall: false, flush: false },
);

const emit = defineEmits<{ closed: [] }>();

const dragY = ref(0);
const dragging = ref(false);
let startY = 0;
let startTime = 0;

function onPointerDown(event: PointerEvent): void {
  if (!props.dismissable) return;
  dragging.value = true;
  startY = event.clientY;
  startTime = performance.now();
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
}

function onPointerMove(event: PointerEvent): void {
  if (!dragging.value) return;
  dragY.value = Math.max(0, event.clientY - startY);
}

function onPointerUp(event: PointerEvent): void {
  if (!dragging.value) return;
  dragging.value = false;
  const distance = Math.max(0, event.clientY - startY);
  const velocity = distance / Math.max(1, performance.now() - startTime);
  // Closing keeps the dragged offset so the exit animation continues from where the finger let go.
  if (distance > 120 || velocity > 0.6) open.value = false;
  else dragY.value = 0;
}

watch(open, (isOpen) => {
  if (isOpen) dragY.value = 0;
});

const sheetStyle = computed(() =>
  dragY.value > 0 ? { transform: `translate3d(0, ${dragY.value}px, 0)`, transition: dragging.value ? "none" : undefined } : undefined,
);

/** Focus the sheet itself: focusing a field would pop the phone keyboard over half the sheet. */
function focusPanel(event: Event): void {
  event.preventDefault();
  (event.target as HTMLElement | null)?.focus({ preventScroll: true });
}

function onOutside(event: Event): void {
  if (!props.dismissable) event.preventDefault();
}
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogPortal>
      <DialogOverlay class="anim-overlay fixed inset-0 z-[60] bg-overlay" />
      <DialogContent
        :class="[
          'anim-sheet fixed inset-x-0 bottom-0 z-[61] flex max-h-[92dvh] flex-col rounded-t-[20px] bg-surface shadow-drawer outline-none transition-transform duration-240 ease-out',
          tall && 'h-[88dvh]',
        ]"
        :style="sheetStyle"
        tabindex="-1"
        v-bind="description ? {} : { 'aria-describedby': undefined }"
        @open-auto-focus="focusPanel"
        @pointer-down-outside="onOutside"
        @escape-key-down="onOutside"
        @close-auto-focus="emit('closed')"
      >
        <div
          class="flex shrink-0 cursor-grab touch-none justify-center pb-1 pt-2.5 active:cursor-grabbing"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerUp"
        >
          <span class="h-1 w-9 rounded-full bg-line-strong" aria-hidden="true" />
        </div>
        <VisuallyHidden v-if="hideHeader || !title">
          <DialogTitle>{{ title }}</DialogTitle>
          <DialogDescription v-if="description">{{ description }}</DialogDescription>
        </VisuallyHidden>
        <header v-else class="shrink-0 px-5 pb-3 pt-1">
          <DialogTitle class="text-md font-semibold text-fg">{{ title }}</DialogTitle>
          <DialogDescription v-if="description" class="mt-0.5 text-sm text-muted">{{ description }}</DialogDescription>
        </header>
        <div :class="['min-h-0 flex-1 overflow-y-auto overscroll-contain', flush ? 'pb-[var(--safe-bottom)]' : 'px-5 pb-[calc(16px+var(--safe-bottom))]']">
          <slot />
        </div>
        <footer
          v-if="$slots.footer"
          class="flex shrink-0 gap-2 border-t border-line px-5 pb-[calc(12px+var(--safe-bottom))] pt-3 [&>*]:flex-1"
        >
          <slot name="footer" />
        </footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
