<script setup lang="ts">
/**
 * Which calendars show: one chip per source the person may see (company events, holidays,
 * birthdays, shifts…), with its colour and how many dates it has in view. Off chips stay listed.
 */
import { Check } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import { formatCount } from "@/lib/format";

import type { CalendarSource } from "../types";

const hidden = defineModel<string[]>({ default: () => [] });
defineProps<{ sources: CalendarSource[]; counts: Record<string, number>; colors: Record<string, string> }>();

const { t } = useI18n();

function toggle(key: string): void {
  hidden.value = hidden.value.includes(key) ? hidden.value.filter((item) => item !== key) : [...hidden.value, key];
}
</script>

<template>
  <div class="flex min-w-0 flex-wrap items-center gap-1.5" role="group" :aria-label="t('agenda.sources.label')">
    <button
      v-for="source in sources"
      :key="source.key"
      type="button"
      :aria-pressed="!hidden.includes(source.key)"
      :class="[
        'pressable inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-sm font-medium transition-colors',
        hidden.includes(source.key) ? 'border-line text-subtle hover:text-muted' : 'border-line-strong bg-surface text-fg shadow-xs hover:bg-highlight',
      ]"
      @click="toggle(source.key)"
    >
      <span
        class="grid size-3.5 shrink-0 place-items-center rounded-[4px] border-[1.5px]"
        :style="hidden.includes(source.key) ? { borderColor: colors[source.key] } : { background: colors[source.key], borderColor: colors[source.key] }"
        aria-hidden="true"
      >
        <Check v-if="!hidden.includes(source.key)" :size="10" :stroke-width="3" class="text-surface" />
      </span>
      <span :class="hidden.includes(source.key) && 'line-through decoration-1'">{{ source.label }}</span>
      <span v-if="counts[source.key]" class="text-xs tabular-nums text-subtle">{{ formatCount(counts[source.key]!) }}</span>
    </button>
  </div>
</template>
