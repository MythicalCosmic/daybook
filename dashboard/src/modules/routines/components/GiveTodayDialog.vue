<script setup lang="ts">
/**
 * A routine made after today's deadline starts the next day it's due (its first task would be late
 * before anyone saw it). After saving one, this says when its first tasks come and offers "Give
 * today's task now": today's task for everyone it applies to, due at a time later today.
 */
import { CalendarClock, Send } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import FormField from "@/components/FormField.vue";
import TimePicker from "@/components/TimePicker.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useGiveToday } from "../api";
import { capitalize, runDayWords, zonedIso } from "../lib";
import type { GiveTarget } from "../types";
import { useRunWords } from "../useRunWords";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ routine: GiveTarget | null }>();
const emit = defineEmits<{ given: [count: number] }>();

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const words = useRunWords();
const give = useGiveToday();

const offer = computed(() => props.routine?.today?.give ?? null);
const dueTime = ref<string | null>(null);
watch(
  open,
  (value) => {
    if (value && offer.value) dueTime.value = fmt.instant(offer.value.due_at, "time");
  },
  { immediate: true },
);

const startsOn = computed(() => (props.routine?.next_run ? runDayWords(props.routine.next_run, words.value) : null));
const title = computed(() => (startsOn.value ? capitalize(t("routines.give.title", { day: startsOn.value })) : t("routines.give.titleLater")));
const body = computed(() => {
  const routine = props.routine;
  if (!routine) return "";
  const due = routine.due_time.slice(0, 5);
  if (!routine.next_run) return t("routines.give.bodyNoRun", { title: routine.title, due });
  return t("routines.give.body", { title: routine.title, due, day: startsOn.value, time: fmt.instant(routine.next_run, "time") });
});
const nowTime = computed(() => fmt.instant(new Date(words.value.now), "time"));
const tooEarly = computed(() => {
  if (!dueTime.value) return false;
  return new Date(zonedIso(todayIn(company.timezone, words.value.now), dueTime.value, company.timezone)).getTime() <= words.value.now;
});

async function submit(): Promise<void> {
  const routine = props.routine;
  if (!routine || !dueTime.value || tooEarly.value) return;
  try {
    const result = await give.mutateAsync({ id: routine.id, dueTime: dueTime.value });
    // Routine work lives on Routines → Today, not in Tasks: say where today's task went.
    const elsewhere = route.name !== "routines.today";
    toast.success(t("routines.give.done", { n: result.given }, result.given), {
      description: t("routines.give.doneBody", { title: routine.title, time: fmt.instant(result.due_at, "time") }),
      ...(elsewhere ? { action: { label: t("routines.give.see"), onClick: () => void router.push({ name: "routines.today", query: { routine: String(routine.id) } }) } } : {}),
    });
    open.value = false;
    emit("given", result.given);
  } catch {
    // the HTTP layer showed why
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="title" size="sm">
    <div class="flex flex-col gap-4">
      <p class="flex items-start gap-2.5 text-sm text-muted">
        <CalendarClock :size="16" class="mt-0.5 shrink-0 text-subtle" aria-hidden="true" />
        <span>{{ body }}</span>
      </p>
      <section v-if="offer" class="flex flex-col gap-3 rounded-[10px] border border-line bg-surface-2/60 p-3.5" data-testid="give-today">
        <div>
          <p class="text-sm font-semibold text-fg">{{ t("routines.give.question") }}</p>
          <p class="mt-0.5 text-sm text-muted">{{ t("routines.give.who", { n: offer.people }, offer.people) }}</p>
        </div>
        <FormField :label="t('routines.give.dueLabel')" :error="tooEarly ? t('routines.give.tooEarly') : undefined">
          <TimePicker v-model="dueTime" :step="15" :min="nowTime" class="max-w-[160px]" />
        </FormField>
      </section>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ offer ? t("routines.give.notNow") : t("common.close") }}</UiButton>
      <UiButton v-if="offer" variant="primary" :icon="Send" :loading="give.isPending.value" :disabled="!dueTime || tooEarly" @click="submit">{{ t("routines.give.button") }}</UiButton>
    </template>
  </UiDialog>
</template>
