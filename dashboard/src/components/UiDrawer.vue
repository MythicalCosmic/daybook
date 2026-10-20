<script setup lang="ts">
/**
 * A side panel for record details (240 ms). Two ways to open it:
 *   - `v-model:open` for local state;
 *   - `query-key="task"`: open while `?task=` is in the URL, so the view can be shared and Back
 *     closes it; the slot receives the value (`<template #default="{ value }">`).
 * On phones it becomes a bottom sheet.
 */
import { X } from "@lucide/vue";
import { DialogClose, DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle, VisuallyHidden } from "reka-ui";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { useBreakpoints } from "@/lib/useBreakpoints";
import { closeQueryKey } from "@/lib/useRouteState";

import BottomSheet from "./BottomSheet.vue";

const openModel = defineModel<boolean>("open", { default: false });

const props = withDefaults(
  defineProps<{
    title?: string;
    description?: string;
    queryKey?: string;
    size?: "sm" | "md" | "lg" | "xl";
    side?: "right" | "left";
    hideHeader?: boolean;
    /** Keep page interaction possible behind the drawer (no overlay). */
    modal?: boolean;
  }>(),
  { title: "", description: undefined, queryKey: undefined, size: "md", side: "right", hideHeader: false, modal: true },
);

const emit = defineEmits<{ closed: [] }>();

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const { isPhone } = useBreakpoints();

const queryValue = computed(() => {
  if (!props.queryKey) return null;
  const raw = route.query[props.queryKey];
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value ?? null;
});

const open = computed({
  get: () => (props.queryKey ? queryValue.value !== null : openModel.value),
  set: (next: boolean) => {
    if (!props.queryKey) {
      openModel.value = next;
      return;
    }
    if (next) return; // opening is done by whoever sets the query value
    closeQueryKey(router, props.queryKey);
  },
});

function focusPanel(event: Event): void {
  event.preventDefault();
  (event.target as HTMLElement | null)?.focus({ preventScroll: true });
}

const widths = { sm: "w-[400px]", md: "w-[480px]", lg: "w-[640px]", xl: "w-[820px]" } as const;
</script>

<template>
  <BottomSheet v-if="isPhone" v-model:open="open" :title="title" :description="description" :hide-header="hideHeader" tall flush @closed="emit('closed')">
    <slot :value="queryValue" />
    <template v-if="$slots.footer" #footer><slot name="footer" :value="queryValue" /></template>
  </BottomSheet>
  <DialogRoot v-else v-model:open="open" :modal="modal">
    <DialogPortal>
      <DialogOverlay v-if="modal" class="anim-overlay fixed inset-0 z-[50] bg-overlay/60" />
      <DialogContent
        :class="[
          'fixed inset-y-2 z-[51] flex max-w-[calc(100vw-16px)] flex-col overflow-hidden rounded-drawer bg-surface shadow-drawer outline-none',
          side === 'right' ? 'anim-drawer-right right-2' : 'anim-drawer-left left-2',
          widths[size],
        ]"
        tabindex="-1"
        @open-auto-focus="focusPanel"
        @close-auto-focus="emit('closed')"
      >
        <VisuallyHidden v-if="hideHeader">
          <DialogTitle>{{ title }}</DialogTitle>
          <DialogDescription v-if="description">{{ description }}</DialogDescription>
        </VisuallyHidden>
        <header v-else class="flex shrink-0 items-center gap-2 border-b border-line py-3 pl-5 pr-3">
          <div class="min-w-0 flex-1">
            <slot name="title">
              <DialogTitle class="truncate text-md font-semibold text-fg">{{ title }}</DialogTitle>
            </slot>
            <DialogDescription v-if="description" class="truncate text-sm text-muted">{{ description }}</DialogDescription>
          </div>
          <slot name="header-actions" :value="queryValue" />
          <DialogClose
            class="pressable grid size-8 shrink-0 place-items-center rounded-button text-muted hover:bg-highlight hover:text-fg"
            :aria-label="t('shell.overlay.close')"
          >
            <X :size="17" />
          </DialogClose>
        </header>
        <div class="min-h-0 flex-1 overflow-y-auto">
          <slot :value="queryValue" />
        </div>
        <footer v-if="$slots.footer" class="flex shrink-0 items-center justify-end gap-2 border-t border-line px-5 py-3">
          <slot name="footer" :value="queryValue" />
        </footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
