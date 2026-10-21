<script setup lang="ts">
/**
 * A reminder as the employee sees it in Telegram: the owner's text (or the built-in wording) with
 * the placeholders filled from a sample task, the task in bold, and the bot's buttons below.
 * Rendered as plain text segments, never as HTML.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

const props = withDefaults(defineProps<{ text: string; step?: number; snooze?: number | null; time?: string }>(), { step: 1, snooze: 30, time: "18:00" });
const { t } = useI18n();

interface Segment {
  text: string;
  bold: boolean;
}

const sample = computed(() => ({
  name: t("reminders.sample.name"),
  task: t("reminders.sample.task"),
  due: props.time,
  late: t("reminders.sample.late", { n: 20 * props.step }),
}));

const segments = computed<Segment[]>(() => {
  const out: Segment[] = [];
  const pattern = /\{(name|task|due|late)\}/g;
  let last = 0;
  for (const match of props.text.matchAll(pattern)) {
    if (match.index! > last) out.push({ text: props.text.slice(last, match.index), bold: false });
    const key = match[1] as keyof typeof sample.value;
    out.push({ text: sample.value[key], bold: key === "task" });
    last = match.index! + match[0].length;
  }
  if (last < props.text.length) out.push({ text: props.text.slice(last), bold: false });
  return out;
});
</script>

<template>
  <div class="flex min-w-0 flex-col items-start gap-1">
    <div class="max-w-[340px] rounded-[16px] rounded-bl-[4px] bg-surface px-3 py-2 text-sm leading-5 text-fg shadow-xs ring-1 ring-line">
      <p class="whitespace-pre-line break-words">
        <template v-for="(segment, index) in segments" :key="index"><b v-if="segment.bold">{{ segment.text }}</b><template v-else>{{ segment.text }}</template></template>
      </p>
      <p class="mt-0.5 text-right text-[10px] text-subtle">{{ time }}</p>
    </div>
    <div class="grid w-full max-w-[340px] grid-cols-3 gap-1">
      <span class="truncate rounded-[8px] bg-surface/80 px-2 py-1 text-center text-xs font-medium text-fg ring-1 ring-line">✅ {{ t("reminders.bubble.done") }}</span>
      <span v-if="snooze" class="truncate rounded-[8px] bg-surface/80 px-2 py-1 text-center text-xs font-medium text-fg ring-1 ring-line">⏰ {{ t("reminders.bubble.snooze", { n: snooze }) }}</span>
      <span class="truncate rounded-[8px] bg-surface/80 px-2 py-1 text-center text-xs font-medium text-fg ring-1 ring-line">📋 {{ t("reminders.bubble.open") }}</span>
    </div>
  </div>
</template>
