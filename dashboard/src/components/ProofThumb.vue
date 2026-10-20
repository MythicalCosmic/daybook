<script setup lang="ts">
/**
 * A photo proof thumbnail (task proofs, Z-reports, receipts, nakladnaya): shimmer while loading, a
 * clear state when the signed link has expired, "+2" when there are more photos, an optional time
 * stamp; click opens them all in the lightbox.
 *
 *   <ProofThumb :src="task.proofs[0].url" :images="task.proofs.map((p) => ({ src: p.url }))" :label="fmt.instant(p.at, 'time')" />
 */
import { ImageOff } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ImageLightbox, { type LightboxImage } from "./ImageLightbox.vue";

defineOptions({ inheritAttrs: false });

const props = withDefaults(
  defineProps<{
    src: string | null | undefined;
    /** Every photo of the record; the lightbox opens on `src`. */
    images?: LightboxImage[];
    alt?: string;
    size?: "xs" | "sm" | "md" | "lg" | "fill";
    /** A small caption on the photo ("08:57"). */
    label?: string;
    zoomable?: boolean;
  }>(),
  { images: undefined, alt: "", size: "md", label: undefined, zoomable: true },
);

const { t } = useI18n();
const state = ref<"loading" | "ready" | "failed">("loading");
const open = ref(false);
const index = ref(0);

watch(
  () => props.src,
  () => (state.value = props.src ? "loading" : "failed"),
  { immediate: true },
);

const gallery = computed<LightboxImage[]>(() => props.images ?? (props.src ? [{ src: props.src, alt: props.alt }] : []));
const extra = computed(() => Math.max(0, gallery.value.length - 1));
const sizes = { xs: "size-8 rounded-[6px]", sm: "size-10 rounded-[7px]", md: "size-16 rounded-[9px]", lg: "size-24 rounded-[10px]", fill: "size-full rounded-[10px]" } as const;

function show(): void {
  if (!props.zoomable || state.value === "failed" || !gallery.value.length) return;
  index.value = Math.max(0, gallery.value.findIndex((image) => image.src === props.src));
  open.value = true;
}
</script>

<template>
  <button
    v-bind="$attrs"
    type="button"
    :class="[
      'group relative shrink-0 overflow-hidden border border-line bg-surface-2 outline-offset-2 dark:bg-surface-3',
      sizes[size],
      zoomable && state !== 'failed' ? 'cursor-zoom-in' : 'cursor-default',
    ]"
    :aria-label="alt || t('common.proof.open')"
    :disabled="!zoomable || state === 'failed'"
    @click.stop="show"
  >
    <img
      v-if="src && state !== 'failed'"
      :src="src"
      :alt="alt"
      loading="lazy"
      decoding="async"
      :class="['size-full object-cover transition-[opacity,transform] duration-300 group-hover:scale-[1.04]', state === 'ready' ? 'opacity-100' : 'opacity-0']"
      @load="state = 'ready'"
      @error="state = 'failed'"
    />
    <span v-if="state === 'loading'" class="proof-shimmer absolute inset-0" aria-hidden="true" />
    <span v-if="state === 'failed'" class="absolute inset-0 grid place-items-center text-subtle" :title="t('common.proof.unavailable')">
      <ImageOff :size="size === 'xs' || size === 'sm' ? 14 : 18" />
    </span>
    <span
      v-if="extra && state !== 'failed'"
      class="absolute right-1 top-1 rounded-full bg-[rgb(20_18_16/0.72)] px-1.5 py-px text-[10px] font-semibold tabular-nums text-white backdrop-blur-sm"
      >+{{ extra }}</span
    >
    <span
      v-if="label && state === 'ready' && size !== 'xs' && size !== 'sm'"
      class="absolute inset-x-0 bottom-0 bg-linear-to-t from-[rgb(20_18_16/0.7)] to-transparent px-1.5 pb-1 pt-3 text-left text-[10px] font-semibold tabular-nums text-white"
      >{{ label }}</span
    >
  </button>
  <ImageLightbox v-if="zoomable && gallery.length" v-model:open="open" v-model:index="index" :images="gallery" />
</template>

<style scoped>
.proof-shimmer {
  background-image: linear-gradient(90deg, transparent 0%, var(--c-skeleton-shine) 50%, transparent 100%);
  background-size: 200% 100%;
  animation: shimmer 1.6s var(--ease-standard) infinite;
}
</style>
