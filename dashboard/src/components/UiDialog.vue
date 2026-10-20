<script setup lang="ts">
/**
 * A centered dialog for focused tasks (create, confirm, edit a few fields). On phones it becomes a
 * bottom sheet unless `mobile="center"`. Footer buttons go in the `footer` slot, primary last.
 */
import { X } from "@lucide/vue";
import { DialogClose, DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle, VisuallyHidden } from "reka-ui";
import { useI18n } from "vue-i18n";

import { useBreakpoints } from "@/lib/useBreakpoints";

import BottomSheet from "./BottomSheet.vue";

const open = defineModel<boolean>("open", { default: false });

const props = withDefaults(
  defineProps<{
    title: string;
    description?: string;
    size?: "sm" | "md" | "lg" | "xl";
    dismissable?: boolean;
    hideClose?: boolean;
    hideHeader?: boolean;
    mobile?: "sheet" | "center";
  }>(),
  { description: undefined, size: "md", dismissable: true, hideClose: false, hideHeader: false, mobile: "sheet" },
);

const emit = defineEmits<{ closed: [] }>();

const { t } = useI18n();
const { isPhone } = useBreakpoints();

const widths = { sm: "max-w-[400px]", md: "max-w-[520px]", lg: "max-w-[680px]", xl: "max-w-[880px]" } as const;

/** Focus the first field of the body (or the dialog itself), never the close button in the header. */
function focusFirstField(event: Event): void {
  event.preventDefault();
  const content = event.target as HTMLElement | null;
  const field = content?.querySelector<HTMLElement>(
    "[data-dialog-body] [autofocus], [data-dialog-body] input:not([type=hidden]), [data-dialog-body] textarea, [data-dialog-body] select",
  );
  (field ?? content)?.focus({ preventScroll: true });
}

function guard(event: Event): void {
  if (!props.dismissable) event.preventDefault();
}
</script>

<template>
  <BottomSheet
    v-if="isPhone && mobile === 'sheet'"
    v-model:open="open"
    :title="title"
    :description="description"
    :hide-header="hideHeader"
    :dismissable="dismissable"
    @closed="emit('closed')"
  >
    <slot />
    <template v-if="$slots.footer" #footer><slot name="footer" /></template>
  </BottomSheet>
  <DialogRoot v-else v-model:open="open">
    <DialogPortal>
      <DialogOverlay class="anim-overlay fixed inset-0 z-[60] bg-overlay backdrop-blur-[2px]" />
      <div class="pointer-events-none fixed inset-0 z-[61] flex items-start justify-center overflow-y-auto p-4 pt-[min(14vh,120px)]">
        <DialogContent
          :class="[
            'anim-dialog pointer-events-auto relative flex max-h-[calc(100dvh-32px)] w-full flex-col overflow-hidden rounded-drawer bg-surface shadow-palette outline-none',
            widths[size],
          ]"
          @pointer-down-outside="guard"
          @escape-key-down="guard"
          tabindex="-1"
          v-bind="description ? {} : { 'aria-describedby': undefined }"
          @open-auto-focus="focusFirstField"
          @close-auto-focus="emit('closed')"
        >
          <VisuallyHidden v-if="hideHeader">
            <DialogTitle>{{ title }}</DialogTitle>
            <DialogDescription v-if="description">{{ description }}</DialogDescription>
          </VisuallyHidden>
          <header v-else class="flex shrink-0 items-start gap-3 px-5 pb-3 pt-5">
            <div class="min-w-0 flex-1">
              <DialogTitle class="text-md font-semibold leading-6 text-fg">{{ title }}</DialogTitle>
              <DialogDescription v-if="description" class="mt-1 text-sm text-muted">{{ description }}</DialogDescription>
            </div>
            <slot name="header-actions" />
            <DialogClose
              v-if="!hideClose"
              class="pressable -mr-1.5 -mt-1 grid size-8 shrink-0 place-items-center rounded-button text-muted hover:bg-highlight hover:text-fg"
              :aria-label="t('shell.overlay.close')"
            >
              <X :size="17" />
            </DialogClose>
          </header>
          <div data-dialog-body class="min-h-0 flex-1 overflow-y-auto px-5 pb-5" :class="hideHeader && 'pt-5'">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="flex shrink-0 items-center justify-end gap-2 border-t border-line bg-canvas/60 px-5 py-3">
            <slot name="footer" />
          </footer>
        </DialogContent>
      </div>
    </DialogPortal>
  </DialogRoot>
</template>
