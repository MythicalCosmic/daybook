<script setup lang="ts">
/**
 * A PDF in the page (contracts, payslips, invoices, termination orders): an iframe of a signed URL
 * (plan §2.8) with "Open in a new tab" and "Download". Signed links expire, so pass a fresh one;
 * `loading` shows the skeleton while the page asks for it.
 */
import { Download, ExternalLink, FileText } from "@lucide/vue";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import SkeletonBlock from "./SkeletonBlock.vue";
import UiButton from "./UiButton.vue";

const props = withDefaults(defineProps<{ src: string | null | undefined; title?: string; height?: string; loading?: boolean; filename?: string }>(), {
  title: undefined,
  height: "min(78vh, 900px)",
  loading: false,
  filename: undefined,
});

const { t } = useI18n();
const ready = ref(false);
watch(
  () => props.src,
  () => (ready.value = false),
);
</script>

<template>
  <div class="flex flex-col overflow-hidden rounded-card border border-line bg-surface">
    <div class="flex items-center gap-2 border-b border-line px-3 py-2">
      <FileText :size="16" class="shrink-0 text-muted" aria-hidden="true" />
      <p class="min-w-0 flex-1 truncate text-sm font-semibold text-fg">{{ title ?? filename ?? "PDF" }}</p>
      <UiButton v-if="src" size="sm" variant="ghost" :icon="ExternalLink" :href="src" target="_blank">{{ t("common.pdf.open") }}</UiButton>
      <a
        v-if="src"
        :href="src"
        :download="filename ?? ''"
        class="pressable inline-flex h-7 items-center gap-1.5 rounded-[7px] px-2.5 text-sm font-[550] text-fg hover:bg-highlight"
      >
        <Download :size="15" aria-hidden="true" />{{ t("common.pdf.download") }}
      </a>
    </div>
    <div class="relative bg-surface-2 dark:bg-surface-3" :style="{ height }">
      <div v-if="loading || !src || !ready" class="absolute inset-0 flex flex-col items-center gap-3 p-8" aria-hidden="true">
        <div class="flex w-full max-w-[520px] flex-col gap-3 rounded-[6px] bg-surface p-8 shadow-raised">
          <SkeletonBlock width="45%" height="16px" />
          <SkeletonBlock :lines="4" />
          <SkeletonBlock :lines="3" />
        </div>
      </div>
      <iframe
        v-if="src && !loading"
        :src="src"
        :title="title ?? filename ?? 'PDF'"
        class="relative size-full border-0 transition-opacity duration-200"
        :class="ready ? 'opacity-100' : 'opacity-0'"
        @load="ready = true"
      />
    </div>
  </div>
</template>
