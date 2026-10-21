<script setup lang="ts">
/**
 * One widget on the Overview: a skeleton of its kind's shape while its code loads (so the grid
 * doesn't jump as cards arrive), and a quiet error card if it breaks, so one module's widget never
 * takes the page down (plan §6.2: every widget fails on its own).
 */
import { onErrorCaptured, ref } from "vue";
import { useI18n } from "vue-i18n";

import SkeletonBlock from "@/components/SkeletonBlock.vue";
import type { Widget, WidgetProps } from "@/core/modules";

// `placeholder: false` for cards that may have nothing to show (Get started once it is done): a
// skeleton that then vanishes would make the page jump.
withDefaults(defineProps<{ widget: Widget; widgetProps: WidgetProps; placeholder?: boolean }>(), { placeholder: true });

const { t } = useI18n();
const failure = ref<unknown>(null);
onErrorCaptured((error) => {
  failure.value = error;
  if (import.meta.env.DEV) console.error(error);
  return false;
});
</script>

<template>
  <!-- Plain markup, not ErrorState: the Overview page is part of the first-load budget. -->
  <div v-if="failure" class="ui-card flex h-full min-h-[136px] flex-col items-center justify-center gap-1.5 p-4 text-center" role="alert">
    <p class="text-sm font-semibold text-fg">{{ t("overview.widget.failed") }}</p>
    <button type="button" class="rounded-[6px] px-2 py-0.5 text-sm font-semibold text-primary hover:bg-highlight" @click="failure = null">{{ t("common.retry") }}</button>
  </div>
  <Suspense v-else>
    <component :is="widget.component" v-bind="widgetProps" />
    <template #fallback>
      <template v-if="!placeholder" />
      <div v-else-if="widget.kind === 'kpi'" class="ui-card flex h-full min-h-[136px] flex-col p-4" aria-hidden="true">
        <SkeletonBlock width="45%" height="13px" />
        <SkeletonBlock class="mt-3" width="60%" height="26px" />
        <SkeletonBlock class="mt-auto" width="35%" height="12px" />
      </div>
      <div v-else class="ui-card flex h-full min-h-[18rem] flex-col gap-3 p-4" aria-hidden="true">
        <SkeletonBlock width="35%" height="13px" />
        <SkeletonBlock v-for="n in 4" :key="n" height="34px" radius="8px" />
      </div>
    </template>
  </Suspense>
</template>
