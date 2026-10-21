<script setup lang="ts">
/** "4 of 6 read" with a thin bar: green when everyone has read the page, ochre past half, red below. */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import ProgressBar from "@/components/ProgressBar.vue";

import { readTone } from "../lib";
import type { ReadCount } from "../types";

const props = withDefaults(defineProps<{ read: ReadCount | null; compact?: boolean }>(), { compact: false });
const { t } = useI18n();
const tone = computed(() => readTone(props.read));
</script>

<template>
  <div v-if="read && read.total" :class="['flex min-w-0 items-center gap-2', compact ? 'w-[120px]' : 'w-full']" :title="t('knowledge.read.of', { read: read.read, total: read.total })">
    <ProgressBar :value="read.read" :max="read.total" size="xs" :tone="tone === 'neutral' ? 'primary' : tone" class="min-w-0 flex-1" />
    <span class="shrink-0 text-xs font-semibold tabular-nums text-muted">{{ read.read }}/{{ read.total }}</span>
  </div>
</template>
