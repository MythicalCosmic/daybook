<script setup lang="ts">
/**
 * The floating bar while rows are selected: "12 selected · Clear" and the page's bulk actions.
 * It rises from the bottom (above the tab bar on phones); Esc clears the selection.
 *
 *   <BulkActionBar :count="selected.length" @clear="clear"><UiButton size="sm" @click="approveAll">…</UiButton></BulkActionBar>
 */
import { X } from "@lucide/vue";
import { onBeforeUnmount, watch } from "vue";
import { useI18n } from "vue-i18n";

import { formatNumber } from "@/lib/format";
import { useFormat } from "@/lib/useFormat";

const props = withDefaults(defineProps<{ count: number; label?: string }>(), { label: undefined });
const emit = defineEmits<{ clear: [] }>();

const { t } = useI18n();
const fmt = useFormat();

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== "Escape" || props.count === 0 || event.defaultPrevented) return;
  // Leave Escape to open dialogs and menus.
  if (document.querySelector("[role=dialog][data-state=open], [role=menu][data-state=open]")) return;
  emit("clear");
}

watch(
  () => props.count > 0,
  (active) => {
    if (active) window.addEventListener("keydown", onKeydown);
    else window.removeEventListener("keydown", onKeydown);
  },
  { immediate: true },
);
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <Teleport to="body">
    <Transition name="bulk">
      <div
        v-if="count > 0"
        role="toolbar"
        :aria-label="label ?? t('common.bulk.selected', { n: count })"
        class="fixed inset-x-3 bottom-[calc(var(--tabbar-h)+12px+var(--safe-bottom))] z-[45] mx-auto flex max-w-max items-center gap-1 rounded-[14px] bg-[#201e1d] p-1.5 pl-3.5 text-[#f7f3ec] shadow-palette md:bottom-6 dark:bg-surface-3 dark:text-fg"
      >
        <span class="mr-1 whitespace-nowrap text-sm font-semibold tabular-nums">{{ label ?? t("common.bulk.selected", { n: formatNumber(count, fmt.lang.value) }) }}</span>
        <span class="mx-1 h-5 w-px bg-white/15" aria-hidden="true" />
        <div class="bulk-actions flex items-center gap-1">
          <slot />
        </div>
        <button
          type="button"
          class="ml-0.5 grid size-8 shrink-0 place-items-center rounded-[9px] text-white/70 transition-colors hover:bg-white/10 hover:text-white dark:text-muted dark:hover:text-fg"
          :aria-label="t('common.bulk.clear')"
          :title="t('common.bulk.clear')"
          @click="emit('clear')"
        >
          <X :size="16" />
        </button>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.bulk-enter-active,
.bulk-leave-active {
  transition:
    opacity var(--dur-drawer) var(--ease-out),
    transform var(--dur-drawer) var(--ease-out);
}
.bulk-enter-from,
.bulk-leave-to {
  opacity: 0;
  transform: translate3d(0, 16px, 0) scale(0.98);
}
:root[data-motion="reduced"] .bulk-enter-from,
:root[data-motion="reduced"] .bulk-leave-to {
  transform: none;
}
/* Buttons inside read on the dark bar. */
.bulk-actions :deep(button) {
  color: inherit;
}
.bulk-actions :deep(.border-line) {
  border-color: rgb(255 255 255 / 0.16);
  background: rgb(255 255 255 / 0.06);
}
.bulk-actions :deep(.border-line:hover) {
  background: rgb(255 255 255 / 0.12);
}
</style>
