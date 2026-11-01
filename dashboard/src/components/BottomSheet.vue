<script setup lang="ts">
/**
 * A phone sheet that slides up from the bottom (320 ms), with a grab handle you can drag down to
 * close. Drawers and dialogs become this on phones. Respects the bottom safe area.
 */
import { X } from "@lucide/vue";
import { DialogClose, DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle, VisuallyHidden } from "reka-ui";
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import IconButton from "@/components/IconButton.vue";
import { useBackCloses } from "@/lib/backStack";
import { useKeyboardInset } from "@/lib/useKeyboardInset";

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
    /** No close button: the content brings its own (a drawer without a header). */
    hideClose?: boolean;
  }>(),
  { title: "", description: undefined, hideHeader: false, dismissable: true, tall: false, flush: false, hideClose: false },
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

// Telegram's Back (and Android's back gesture) closes the sheet instead of leaving the page.
useBackCloses(() => open.value && props.dismissable, () => (open.value = false));

const { t } = useI18n();

// iOS leaves the sheet under the keyboard: lift it above and fit it in the space left (8 px keep
// the top edge visible), then bring the field being typed in back into view.
const keyboard = useKeyboardInset(open);
const body = ref<HTMLElement | null>(null);
watch(
  () => keyboard.inset.value,
  async (inset) => {
    if (!inset) return;
    await nextTick();
    const field = document.activeElement;
    if (field instanceof HTMLElement && body.value?.contains(field)) field.scrollIntoView?.({ block: "nearest" });
  },
);

const sheetStyle = computed(() => {
  const style: Record<string, string> = {};
  if (dragY.value > 0) {
    style.transform = `translate3d(0, ${dragY.value}px, 0)`;
    if (dragging.value) style.transition = "none";
  }
  const left = keyboard.height.value;
  if (keyboard.inset.value > 0 && left !== null) {
    style.bottom = `${keyboard.inset.value}px`;
    style.maxHeight = `${left - 8}px`;
    if (props.tall) style.height = `${left - 8}px`;
  }
  return Object.keys(style).length ? style : undefined;
});

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
        <VisuallyHidden v-if="hideHeader || !(title || $slots.title)">
          <DialogTitle>{{ title }}</DialogTitle>
          <DialogDescription v-if="description">{{ description }}</DialogDescription>
        </VisuallyHidden>
        <!-- Without a header the close button sits in the top corner, beside the grab handle. -->
        <DialogClose v-if="dismissable && !hideClose && (hideHeader || !(title || $slots.title))" as-child>
          <IconButton class="absolute right-2 top-1.5 z-10" :icon="X" :label="t('common.close')" size="lg" :tooltip="false" />
        </DialogClose>
        <!-- The drawer's and dialog's own header pieces (a custom title, a "More" menu, a status)
             come along on phones too. -->
        <header v-else class="flex shrink-0 items-start gap-2 px-5 pb-3 pt-1">
          <div class="min-w-0 flex-1">
            <slot name="title">
              <DialogTitle class="text-md font-semibold text-fg">{{ title }}</DialogTitle>
            </slot>
            <DialogDescription v-if="description" class="mt-0.5 text-sm text-muted">{{ description }}</DialogDescription>
          </div>
          <div v-if="$slots['header-actions'] || (dismissable && !hideClose)" class="-mr-2.5 -mt-1.5 flex shrink-0 items-center gap-1">
            <slot name="header-actions" />
            <DialogClose v-if="dismissable && !hideClose" as-child>
              <IconButton :icon="X" :label="t('common.close')" size="lg" :tooltip="false" />
            </DialogClose>
          </div>
        </header>
        <!-- The bottom safe area (Telegram's and the phone's) goes under whatever is last: the
             footer when there is one, else the body. -->
        <div
          ref="body"
          :class="[
            'min-h-0 flex-1 overflow-y-auto overscroll-contain',
            flush ? !$slots.footer && 'pb-[var(--safe-bottom)]' : ['px-5', $slots.footer ? 'pb-4' : 'pb-[calc(16px+var(--safe-bottom))]'],
          ]"
          data-sheet-body
        >
          <slot />
        </div>
        <!-- Buttons share the row; a note (`data-sheet-note`, e.g. "Creates 3 tasks") takes a row
             of its own above them instead of being squeezed to a third. -->
        <footer
          v-if="$slots.footer"
          class="flex shrink-0 flex-wrap gap-2 border-t border-line px-5 pb-[calc(12px+var(--safe-bottom))] pt-3 [&>*]:flex-1 [&>[data-sheet-note]]:basis-full"
        >
          <slot name="footer" />
        </footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
