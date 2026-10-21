<script setup lang="ts">
/**
 * A page body in the reading view: the server's cleaned HTML, cleaned once more in the browser
 * (DOMPurify, loaded on first use), checklists read-only, pictures opening in the lightbox.
 */
import { ref, watch } from "vue";

import ImageLightbox from "@/components/ImageLightbox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";

import "../prose.css";
import { safeBody } from "../lib";

const props = defineProps<{ html: string }>();

const ready = ref<string | null>(null);
watch(
  () => props.html,
  async (html) => {
    ready.value = await safeBody(html || "");
  },
  { immediate: true },
);

const root = ref<HTMLElement | null>(null);
const lightboxOpen = ref(false);
const lightboxIndex = ref(0);
const images = ref<Array<{ src: string; alt: string }>>([]);

function onClick(event: MouseEvent): void {
  const target = event.target as HTMLElement | null;
  if (target?.tagName !== "IMG") return;
  const all = Array.from(root.value?.querySelectorAll<HTMLImageElement>("img") ?? []);
  images.value = all.map((img) => ({ src: img.src, alt: img.alt }));
  lightboxIndex.value = Math.max(0, all.indexOf(target as HTMLImageElement));
  lightboxOpen.value = true;
}
</script>

<template>
  <div v-if="ready === null" class="flex flex-col gap-3" aria-hidden="true">
    <SkeletonBlock :lines="4" />
    <SkeletonBlock height="120px" radius="12px" />
  </div>
  <!-- eslint-disable-next-line vue/no-v-html -- cleaned twice: by the server's allow-list and DOMPurify -->
  <article v-else ref="root" class="kb-prose kb-read" @click="onClick" v-html="ready" />
  <ImageLightbox v-if="images.length" v-model:open="lightboxOpen" v-model:index="lightboxIndex" :images="images" />
</template>

<style scoped>
.kb-read :deep(img) {
  cursor: zoom-in;
}
</style>
