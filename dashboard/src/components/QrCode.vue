<script setup lang="ts">
/**
 * A QR code for a link (sign-in deep link, invite link, vacancy bot link): always dark on white so
 * every phone camera reads it, in both themes. `downloadable` adds "Download PNG" (posters).
 * The qrcode library loads only when a code is first shown.
 */
import { Download } from "@lucide/vue";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { downloadFile, safeFilename } from "@/lib/csv";

import SkeletonBlock from "./SkeletonBlock.vue";
import UiButton from "./UiButton.vue";

const props = withDefaults(
  defineProps<{ value: string; size?: number; label?: string; downloadable?: boolean; filename?: string; level?: "L" | "M" | "Q" | "H" }>(),
  { size: 168, label: undefined, downloadable: false, filename: "qr", level: "M" },
);

const { t } = useI18n();
const svg = ref<string | null>(null);
const failed = ref(false);

const DARK = "#201e1d";

watch(
  () => [props.value, props.level] as const,
  async ([value, level]) => {
    failed.value = false;
    if (!value) {
      svg.value = null;
      return;
    }
    try {
      const QR = await import("qrcode");
      svg.value = await QR.toString(value, { type: "svg", margin: 0, errorCorrectionLevel: level, color: { dark: DARK, light: "#ffffff00" } });
    } catch {
      failed.value = true;
    }
  },
  { immediate: true },
);

/** Drawn on a canvas (no data: URL fetch, which the console's CSP `connect-src 'self'` would block). */
async function download(): Promise<void> {
  const QR = await import("qrcode");
  const canvas = document.createElement("canvas");
  await QR.toCanvas(canvas, props.value, { width: 1024, margin: 2, errorCorrectionLevel: props.level, color: { dark: DARK, light: "#ffffff" } });
  canvas.toBlob((blob) => blob && downloadFile(safeFilename(props.filename, "png"), blob, "image/png"), "image/png");
}
</script>

<template>
  <figure class="inline-flex flex-col items-center gap-2">
    <div
      class="grid place-items-center rounded-[14px] bg-white p-3 shadow-[0_0_0_1px_rgb(32_30_29/0.08),0_8px_20px_-8px_rgb(32_30_29/0.18)]"
      :style="{ width: `${size + 24}px`, height: `${size + 24}px` }"
    >
      <!-- v-html is safe here: the SVG is generated locally by the qrcode library, never taken from input. -->
      <div v-if="svg" class="qr-svg" :style="{ width: `${size}px`, height: `${size}px` }" role="img" :aria-label="label ?? value" v-html="svg" />
      <SkeletonBlock v-else-if="!failed" :width="`${size}px`" :height="`${size}px`" radius="8px" />
      <span v-else class="px-2 text-center text-xs text-muted">{{ t("common.error.generic") }}</span>
    </div>
    <figcaption v-if="label" class="max-w-[220px] text-center text-sm text-muted">{{ label }}</figcaption>
    <UiButton v-if="downloadable && svg" size="sm" variant="ghost" :icon="Download" @click="download">{{ t("common.qr.download") }}</UiButton>
  </figure>
</template>

<style scoped>
.qr-svg :deep(svg) {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
