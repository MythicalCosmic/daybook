<script setup lang="ts">
/**
 * A list beside its selected item (inbox, claims, chat): the list pane on the left (drag its edge to
 * resize, remembered per `id`), the detail on the right, the `empty` slot when nothing is selected.
 * On phones only one pane shows: the detail while `detailOpen`, with a Back button.
 *
 *   <SplitView id="inbox" :detail-open="!!selected" @back="selected = null">
 *     <template #list>…</template>
 *     <template #detail>…</template>
 *   </SplitView>
 */
import { ArrowLeft } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { useBreakpoints } from "@/lib/useBreakpoints";
import { isNumber, readStored, writeStored } from "@/lib/storage";

const props = withDefaults(
  defineProps<{
    id?: string;
    detailOpen?: boolean;
    listWidth?: number;
    minListWidth?: number;
    maxListWidth?: number;
    resizable?: boolean;
    /** Fill the available height (pages with `layout: "full"`); otherwise a fixed panel height. */
    height?: string;
    backLabel?: string;
  }>(),
  { id: undefined, detailOpen: false, listWidth: 380, minListWidth: 280, maxListWidth: 560, resizable: true, height: "calc(100dvh - 210px)", backLabel: undefined },
);

const emit = defineEmits<{ back: [] }>();

const { t } = useI18n();
const { isPhone } = useBreakpoints();
const width = ref(props.id ? readStored(`split.${props.id}`, props.listWidth, isNumber) : props.listWidth);
const resizing = ref(false);
let start = 0;
let startWidth = 0;

const clamped = computed(() => Math.min(props.maxListWidth, Math.max(props.minListWidth, width.value)));

function onPointerDown(event: PointerEvent): void {
  resizing.value = true;
  start = event.clientX;
  startWidth = clamped.value;
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
}

function onPointerMove(event: PointerEvent): void {
  if (!resizing.value) return;
  width.value = startWidth + event.clientX - start;
}

function onPointerUp(): void {
  if (!resizing.value) return;
  resizing.value = false;
  width.value = clamped.value;
  if (props.id) writeStored(`split.${props.id}`, width.value);
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  event.preventDefault();
  width.value = clamped.value + (event.key === "ArrowLeft" ? -24 : 24);
  if (props.id) writeStored(`split.${props.id}`, clamped.value);
}
</script>

<template>
  <div v-if="isPhone" class="min-w-0">
    <div v-show="!detailOpen"><slot name="list" /></div>
    <div v-if="detailOpen" class="flex flex-col">
      <button
        type="button"
        class="mb-3 inline-flex w-fit items-center gap-1.5 rounded-[6px] py-1 text-sm font-semibold text-muted hover:text-fg"
        @click="emit('back')"
      >
        <ArrowLeft :size="16" />{{ backLabel ?? t("common.back") }}
      </button>
      <slot name="detail" />
    </div>
  </div>
  <div v-else class="ui-card flex min-h-0 overflow-hidden" :style="{ height }" :class="resizing && 'select-none'">
    <div class="flex min-h-0 shrink-0 flex-col border-r border-line" :style="{ width: `${clamped}px` }">
      <slot name="list" />
    </div>
    <div
      v-if="resizable"
      role="separator"
      aria-orientation="vertical"
      :aria-valuenow="clamped"
      :aria-valuemin="minListWidth"
      :aria-valuemax="maxListWidth"
      tabindex="0"
      class="group relative z-10 -ml-[3px] w-[6px] shrink-0 cursor-col-resize outline-none"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @keydown="onKeydown"
    >
      <span
        :class="[
          'absolute inset-y-0 left-1/2 w-[2px] -translate-x-1/2 rounded-full transition-colors',
          resizing ? 'bg-primary' : 'bg-transparent group-hover:bg-line-strong group-focus-visible:bg-primary',
        ]"
      />
    </div>
    <div class="flex min-h-0 min-w-0 flex-1 flex-col">
      <slot v-if="detailOpen" name="detail" />
      <slot v-else name="empty" />
    </div>
  </div>
</template>
