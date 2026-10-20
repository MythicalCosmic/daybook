<script setup lang="ts">
/**
 * The bar that slides up while a form has unsaved changes (settings panels, editors) or a page's
 * primary actions on phones (plan §6.1: "primary actions in a sticky bottom bar"). It sticks to the
 * bottom of the scrolling page; on phones it sits above the tab bar.
 *
 *   <StickyActionBar :show="form.dirty.value" :message="t('common.unsaved')">
 *     <UiButton variant="ghost" @click="form.reset()">{{ t('common.discard') }}</UiButton>
 *     <UiButton variant="primary" :loading="form.submitting.value" @click="form.submit">{{ t('common.save') }}</UiButton>
 *   </StickyActionBar>
 */
withDefaults(defineProps<{ show?: boolean; message?: string; tone?: "neutral" | "warning" }>(), { show: true, message: undefined, tone: "neutral" });
</script>

<template>
  <Transition name="action-bar">
    <div
      v-if="show"
      class="sticky bottom-[calc(12px+var(--safe-bottom))] z-30 mt-6 max-md:bottom-[calc(var(--tabbar-h)+10px+var(--safe-bottom))]"
      role="region"
      :aria-label="message"
    >
      <div
        class="mx-auto flex max-w-[760px] flex-wrap items-center gap-2 rounded-[14px] border border-line bg-surface/95 py-2 pl-4 pr-2 shadow-pop backdrop-blur-md max-sm:[&>.actions]:w-full"
      >
        <p class="flex min-w-0 flex-1 items-center gap-2 text-sm font-medium text-fg">
          <span v-if="tone === 'warning'" class="size-2 shrink-0 rounded-full bg-warning" aria-hidden="true" />
          <slot name="message">{{ message }}</slot>
        </p>
        <div class="actions flex shrink-0 items-center gap-2 max-sm:[&>*]:flex-1">
          <slot />
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.action-bar-enter-active,
.action-bar-leave-active {
  transition:
    opacity var(--dur-drawer) var(--ease-out),
    transform var(--dur-drawer) var(--ease-out);
}
.action-bar-enter-from,
.action-bar-leave-to {
  opacity: 0;
  transform: translate3d(0, var(--enter-y-bar, 16px), 0);
}
:root[data-motion="reduced"] .action-bar-enter-from,
:root[data-motion="reduced"] .action-bar-leave-to {
  transform: none;
}
</style>
