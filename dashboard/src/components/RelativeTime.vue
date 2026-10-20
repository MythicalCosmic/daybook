<script setup lang="ts">
/**
 * "just now", "5 min ago", "yesterday, 14:05", "12 Oct", in the company's timezone, kept fresh
 * by one shared 30-second ticker (lib/useNow); the exact date and time is in the tooltip and
 * `datetime`. `mode="time"`, `"date"` or `"datetime"` show a fixed format instead.
 */
import { computed } from "vue";

import type { InstantStyle } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";

const props = withDefaults(defineProps<{ value: string | Date | null | undefined; mode?: "relative" | InstantStyle }>(), { mode: "relative" });

const fmt = useFormat();
const now = useNow();

const iso = computed(() => (props.value instanceof Date ? props.value.toISOString() : (props.value ?? "")));
const text = computed(() => {
  if (!props.value) return "—";
  return props.mode === "relative" ? fmt.relative(props.value, now.value) : fmt.instant(props.value, props.mode);
});
const title = computed(() => (props.value ? fmt.instant(props.value, "datetime") : undefined));
</script>

<template>
  <time :datetime="iso || undefined" :title="mode === 'relative' ? title : undefined" class="whitespace-nowrap tabular-nums">{{ text }}</time>
</template>
