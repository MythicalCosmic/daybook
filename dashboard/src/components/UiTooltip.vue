<script setup lang="ts">
/**
 * A short label on hover or keyboard focus, optionally with a shortcut:
 * `<UiTooltip content="Inbox" shortcut="g i"><button …/></UiTooltip>`. The default slot is the
 * trigger, rendered as-is (no wrapper); `#content` replaces the text.
 *
 * Its own small engine rather than reka-ui's Tooltip: every IconButton has one and the shell is full
 * of them, and reka's tooltip brings its positioning library (floating-ui) into the first load
 * (README "Budgets"). It behaves the same: it opens after a pause on hover (at once when another
 * tooltip just closed), at once on keyboard focus, never on touch, closes on leaving, a press,
 * Escape or a scroll, flips to the other side when there is no room, and stays in the window.
 * Attributes given to it (a `class` from a component whose root it is) go to the trigger.
 */
import { cloneVNode, computed, nextTick, onBeforeUnmount, ref, useAttrs, useId, useSlots, watch, type VNode } from "vue";

import KbdKey from "./KbdKey.vue";
import { firstSlotNode } from "./slotNode";
import { placeTooltip, tooltipTiming, type TooltipPlacement, type TooltipSide } from "./tooltip";

defineOptions({ inheritAttrs: false });

const props = withDefaults(
  defineProps<{
    content?: string;
    shortcut?: string;
    side?: TooltipSide;
    align?: "start" | "center" | "end";
    sideOffset?: number;
    disabled?: boolean;
    delay?: number;
  }>(),
  { content: undefined, shortcut: undefined, side: "top", align: "center", sideOffset: 6, disabled: false, delay: undefined },
);

const slots = useSlots();
const id = `tip-${useId()}`;
const open = ref(false);
const placed = ref<TooltipPlacement | null>(null);
const panel = ref<HTMLElement | null>(null);
let anchor: HTMLElement | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
// After a press, the tooltip stays away until the pointer leaves (as reka-ui does).
let pressed = false;

function place(): void {
  if (!anchor || !panel.value) return;
  placed.value = placeTooltip(anchor.getBoundingClientRect(), { width: panel.value.offsetWidth, height: panel.value.offsetHeight }, {
    side: props.side,
    align: props.align,
    offset: props.sideOffset,
    viewport: { width: window.innerWidth, height: window.innerHeight },
  });
}

function show(): void {
  clearTimeout(timer);
  if (open.value) return;
  open.value = true;
  placed.value = null;
  tooltipTiming.opened();
  window.addEventListener("scroll", hide, { capture: true, passive: true });
  window.addEventListener("keydown", onEscape, true);
  void nextTick(place);
}

function hide(): void {
  clearTimeout(timer);
  if (!open.value) return;
  open.value = false;
  tooltipTiming.closed();
  window.removeEventListener("scroll", hide, { capture: true });
  window.removeEventListener("keydown", onEscape, true);
}

function onEscape(event: KeyboardEvent): void {
  if (event.key === "Escape") hide();
}

const handlers = {
  onPointerenter(event: PointerEvent) {
    if (event.pointerType === "touch" || pressed) return;
    anchor = event.currentTarget as HTMLElement;
    clearTimeout(timer);
    const wait = tooltipTiming.waitFor(props.delay);
    if (wait <= 0) show();
    else timer = setTimeout(show, wait);
  },
  onPointerleave() {
    pressed = false;
    hide();
  },
  onPointerdown() {
    pressed = true;
    hide();
  },
  onFocus(event: FocusEvent) {
    const target = event.currentTarget as HTMLElement;
    // Keyboard focus only: a click focuses the button too, and must not pop a label over it.
    if (!target.matches?.(":focus-visible")) return;
    anchor = target;
    show();
  },
  onBlur() {
    hide();
  },
};

const attrs = useAttrs();
const active = computed(() => !props.disabled && (!!props.content || !!slots.content));
watch(active, (on) => {
  if (!on) hide();
});

/**
 * The trigger: the slot's first element, with the attributes given to the tooltip and, while it
 * is on, the tooltip's listeners and its description. Other nodes of the slot render as they are.
 */
function Trigger() {
  const nodes = slots.default?.() ?? [];
  const first = firstSlotNode(nodes);
  const extra = active.value ? { ...attrs, ...handlers, "aria-describedby": open.value ? id : undefined } : attrs;
  if (!first || !Object.keys(extra).length) return nodes;
  const trigger = cloneVNode(first, extra, true);
  return nodes.includes(first) ? nodes.map((node: VNode) => (node === first ? trigger : node)) : trigger;
}

onBeforeUnmount(hide);
</script>

<template>
  <Trigger />
  <template v-if="active">
    <Teleport v-if="open" to="body">
      <div
        :id="id"
        ref="panel"
        role="tooltip"
        :data-side="placed?.side ?? side"
        data-state="delayed-open"
        class="anim-pop pointer-events-none fixed z-[80] flex max-w-[280px] select-none items-center gap-2 rounded-[7px] bg-[#201e1d] px-2 py-1 text-xs font-medium text-[#f7f3ec] shadow-pop dark:bg-surface-3 dark:text-fg"
        :style="placed ? { left: `${placed.x}px`, top: `${placed.y}px` } : { left: '0', top: '0', visibility: 'hidden' }"
      >
        <slot name="content">{{ content }}</slot>
        <KbdKey v-if="shortcut" :keys="shortcut" inverted class="-mr-0.5 opacity-90" />
        <svg
          v-if="placed"
          class="absolute fill-[#201e1d] dark:fill-[var(--c-surface-3)]"
          :style="placed.arrow"
          width="10"
          height="5"
          viewBox="0 0 10 5"
          aria-hidden="true"
        >
          <path d="M0 0 L5 5 L10 0 Z" />
        </svg>
      </div>
    </Teleport>
  </template>
</template>
