<script setup lang="ts">
/**
 * One task the AI understood, ready to change before it's created: the title, for whom ("Me"
 * first), when (the AI's words until changed; presets, a day and a time), urgent, photo proof,
 * checklist steps, and remove. A problem reads as a plain sentence with its fix one tap away.
 */
import { CalendarClock, Camera, CircleAlert, Flag, ListChecks, Plus, Trash2, Undo2, UserRound, X } from "@lucide/vue";
import { computed, nextTick, ref } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import type { PersonOption } from "@/components/pickers";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import UiButton from "@/components/UiButton.vue";
import { addDays, todayIn } from "@/lib/dates";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";

import { applyFix, liveProblems, problemFixes, setAssignee, zonedIso, zonedParts, type EditableDraft, type Fix } from "../lib";
import type { DraftProblem } from "../types";

const model = defineModel<EditableDraft>({ required: true });
const props = withDefaults(
  defineProps<{
    index: number;
    people: PersonOption[];
    myId: number;
    timeZone: string;
    disabled?: boolean;
    /** Why the server couldn't create this one (after apply). */
    failure?: string | null;
  }>(),
  { disabled: false, failure: null },
);

const { t } = useI18n();
const fmt = useFormat();
const { isPhone } = useBreakpoints();
/** Fields a finger can hit on a phone (40 px), the console's 32 px elsewhere. */
const size = computed(() => (isPhone.value ? "lg" : "md"));
const now = useNow();
const picker = ref<HTMLElement | null>(null);
const editingDue = ref(false);
const showDetails = ref(model.value.description.trim().length > 0);

const edit = computed(() => model.value);
const problems = computed(() => liveProblems(edit.value, now.value));

/** "Me" first, then everyone else; the AI's pick stays in the list even outside the picker's list. */
const options = computed<PersonOption[]>(() => {
  const me = props.people.find((person) => person.id === props.myId);
  const rest = props.people.filter((person) => person.id !== props.myId);
  const list: PersonOption[] = [{ id: props.myId, name: t("ai.review.me"), subtitle: me?.name, photo_url: me?.photo_url ?? null }, ...rest];
  const picked = edit.value.assigneeId;
  if (picked !== null && picked !== props.myId && !list.some((person) => person.id === picked)) {
    list.push({ id: picked, name: edit.value.assigneeName ?? `#${picked}`, subtitle: edit.value.assigneePosition ?? undefined });
  }
  return list;
});
const assignee = computed<number | null>({
  get: () => edit.value.assigneeId ?? props.myId,
  set: (id) => {
    if (id === null || id === props.myId) {
      model.value = setAssignee(edit.value, null);
      return;
    }
    const person = options.value.find((option) => option.id === id);
    model.value = setAssignee(edit.value, { id, name: person?.name ?? `#${id}`, position: person?.subtitle ?? null });
  },
});

/** The AI's own words ("Ertaga, 10:00") until the time is changed here, then "Today, 18:00" or "5 Nov, 18:00". */
const dueLabel = computed(() => {
  const due = edit.value.dueAt;
  if (due === null) return t("ai.review.noDue");
  if (!edit.value.dueTouched && edit.value.dueText) return edit.value.dueText;
  const { day, time } = zonedParts(due, props.timeZone);
  const today = todayIn(props.timeZone, now.value);
  if (day === today) return t("ai.fix.today", { time });
  if (day === addDays(today, 1)) return t("ai.fix.tomorrow", { time });
  return fmt.instant(due, "short");
});
const dueDay = computed<string | null>({
  get: () => (edit.value.dueAt ? zonedParts(edit.value.dueAt, props.timeZone).day : null),
  set: (day) => {
    if (!day) return;
    const time = edit.value.dueAt ? zonedParts(edit.value.dueAt, props.timeZone).time : "18:00";
    model.value = { ...edit.value, dueAt: zonedIso(day, time, props.timeZone), dueTouched: true };
  },
});
const dueTime = computed<string | null>({
  get: () => (edit.value.dueAt ? zonedParts(edit.value.dueAt, props.timeZone).time : null),
  set: (time) => {
    if (!time) return;
    const day = edit.value.dueAt ? zonedParts(edit.value.dueAt, props.timeZone).day : todayIn(props.timeZone);
    model.value = { ...edit.value, dueAt: zonedIso(day, time, props.timeZone), dueTouched: true };
  },
});

function patch(changes: Partial<EditableDraft>): void {
  model.value = { ...edit.value, ...changes };
}

function problemText(problem: DraftProblem): string {
  const guess = edit.value.guess.trim();
  switch (problem) {
    case "no_assignee_match":
      return guess ? t("ai.problem.noMatch", { guess }) : t("ai.problem.noMatchUnknown");
    case "ambiguous_assignee":
      return guess ? t("ai.problem.ambiguous", { guess }) : t("ai.problem.ambiguousUnknown");
    case "not_allowed":
      return t("ai.problem.notAllowed", { name: edit.value.assigneeName ?? guess });
    case "no_due":
      return t("ai.problem.noDue");
    case "past_due":
      return t("ai.problem.pastDue");
  }
}

function fixLabel(fix: Fix): string {
  if (fix.kind === "pick") return t("ai.fix.pick");
  if (fix.kind === "me") return t("ai.fix.me");
  if (fix.kind === "keepNoDue") return t("ai.review.noDue");
  const today = todayIn(props.timeZone, now.value);
  return t(fix.day === today ? "ai.fix.today" : "ai.fix.tomorrow", { time: fix.time });
}

async function runFix(fix: Fix): Promise<void> {
  if (fix.kind === "pick") {
    await nextTick();
    // Open the person picker: its trigger is the first focusable control in the row.
    const trigger = picker.value?.querySelector<HTMLElement>("button, input, [role=combobox]");
    trigger?.focus();
    trigger?.click();
    return;
  }
  model.value = applyFix(edit.value, fix, { timeZone: props.timeZone });
}

const steps = computed(() => edit.value.checklist);
function setStep(index: number, text: string): void {
  patch({ checklist: steps.value.map((step, at) => (at === index ? text : step)) });
}
function addStep(): void {
  patch({ checklist: [...steps.value, ""] });
}
function removeStep(index: number): void {
  patch({ checklist: steps.value.filter((_, at) => at !== index) });
}
</script>

<template>
  <!-- Removed: one quiet line with Undo, so a slip costs nothing. -->
  <div v-if="edit.removed" class="flex items-center gap-3 rounded-card border border-dashed border-line px-4 py-3 text-sm text-muted" :data-draft="index">
    <span class="min-w-0 flex-1 truncate"><s>{{ edit.title || t("ai.review.untitled") }}</s></span>
    <UiButton variant="ghost" size="sm" :icon="Undo2" :disabled="disabled" @click="patch({ removed: false })">{{ t("ai.review.undo") }}</UiButton>
  </div>
  <article
    v-else
    :class="['ai-draft relative flex flex-col gap-3 rounded-card border bg-surface p-3.5 md:p-4', failure ? 'border-danger' : problems.length ? 'border-[color-mix(in_srgb,var(--c-warning)_45%,var(--c-border))]' : 'border-line']"
    :data-draft="index"
  >
    <div class="flex items-start gap-2.5">
      <span class="num mt-1.5 grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent-fg" aria-hidden="true">{{ index + 1 }}</span>
      <div class="min-w-0 flex-1">
        <TextInput
          :model-value="edit.title"
          :maxlength="200"
          :disabled="disabled"
          :invalid="!edit.title.trim()"
          :aria-label="t('ai.review.titleLabel', { n: index + 1 })"
          :placeholder="t('ai.review.titlePlaceholder')"
          :size="size"
          class="font-medium"
          data-testid="draft-title"
          @update:model-value="(value) => patch({ title: value ?? '' })"
        />
      </div>
      <UiButton variant="ghost" size="md" class="!size-10 !px-0 text-muted md:!size-8" :aria-label="t('ai.review.remove', { n: index + 1 })" :disabled="disabled" @click="patch({ removed: true })">
        <Trash2 :size="16" aria-hidden="true" />
      </UiButton>
    </div>

    <div class="grid gap-3 pl-8 sm:grid-cols-2">
      <div ref="picker" class="flex min-w-0 flex-col gap-1">
        <span class="flex items-center gap-1.5 text-xs font-medium text-muted"><UserRound :size="13" aria-hidden="true" />{{ t("ai.review.for") }}</span>
        <PersonPicker v-model="assignee" :people="options" :clearable="false" :size="size" :disabled="disabled" :invalid="problems.some((p) => p !== 'no_due' && p !== 'past_due')" />
      </div>
      <div class="flex min-w-0 flex-col gap-1">
        <span class="flex items-center gap-1.5 text-xs font-medium text-muted"><CalendarClock :size="13" aria-hidden="true" />{{ t("ai.review.when") }}</span>
        <button
          v-if="!editingDue"
          type="button"
          :disabled="disabled"
          :class="[
            'pressable ui-control flex h-[var(--control-h)] min-h-10 w-full items-center gap-2 px-2.5 text-left text-base md:min-h-0',
            problems.includes('past_due') && 'text-danger',
          ]"
          :aria-label="t('ai.review.changeWhen', { when: dueLabel })"
          data-testid="draft-when"
          @click="editingDue = true"
        >
          <span class="num min-w-0 flex-1 truncate" :class="edit.dueAt === null && 'text-muted'">{{ dueLabel }}</span>
          <span class="shrink-0 text-xs font-medium text-accent-fg">{{ t("ai.review.change") }}</span>
        </button>
        <div v-else class="flex flex-col gap-2">
          <div class="grid grid-cols-[minmax(0,1fr)_104px] gap-2">
            <DatePicker v-model="dueDay" :min="todayIn(timeZone)" :size="size" :disabled="disabled" />
            <TimePicker v-model="dueTime" :step="15" :size="size" :disabled="disabled" />
          </div>
          <div class="flex flex-wrap gap-1.5">
            <button type="button" class="pressable inline-flex h-8 items-center gap-1 rounded-full border border-line px-2.5 text-xs font-medium text-muted hover:bg-highlight" @click="model = applyFix(edit, { kind: 'keepNoDue' }, { timeZone }); editingDue = false">
              <X :size="12" aria-hidden="true" />{{ t("ai.review.noDue") }}
            </button>
            <button type="button" class="pressable inline-flex h-8 items-center rounded-full bg-accent-soft px-3 text-xs font-semibold text-accent-fg" @click="editingDue = false">{{ t("ai.review.doneEditing") }}</button>
          </div>
        </div>
      </div>
    </div>

    <div class="flex flex-wrap items-center gap-1.5 pl-8" role="group" :aria-label="t('ai.review.options')">
      <button
        type="button"
        :aria-pressed="edit.priority === 'urgent'"
        :disabled="disabled"
        :class="[
          'pressable inline-flex h-10 items-center gap-1.5 rounded-full border px-3 text-sm md:h-8',
          edit.priority === 'urgent' ? 'border-danger bg-danger-soft font-semibold text-danger' : 'border-line text-fg hover:bg-highlight',
        ]"
        @click="patch({ priority: edit.priority === 'urgent' ? 'normal' : 'urgent' })"
      >
        <Flag :size="14" aria-hidden="true" />{{ t("ai.review.urgent") }}
      </button>
      <button
        type="button"
        :aria-pressed="edit.proof === 'photo'"
        :disabled="disabled"
        :class="[
          'pressable inline-flex h-10 items-center gap-1.5 rounded-full border px-3 text-sm md:h-8',
          edit.proof === 'photo' ? 'border-primary bg-accent-soft font-semibold text-accent-fg' : 'border-line text-fg hover:bg-highlight',
        ]"
        @click="patch({ proof: edit.proof === 'photo' ? 'none' : 'photo' })"
      >
        <Camera :size="14" aria-hidden="true" />{{ t("ai.review.photo") }}
      </button>
      <button
        v-if="!steps.length"
        type="button"
        :disabled="disabled"
        class="pressable inline-flex h-10 items-center gap-1.5 rounded-full border border-dashed border-line px-3 text-sm text-muted hover:bg-highlight hover:text-fg md:h-8"
        @click="addStep"
      >
        <ListChecks :size="14" aria-hidden="true" />{{ t("ai.review.addSteps") }}
      </button>
      <button
        v-if="!showDetails"
        type="button"
        :disabled="disabled"
        class="pressable inline-flex h-10 items-center gap-1.5 rounded-full border border-dashed border-line px-3 text-sm text-muted hover:bg-highlight hover:text-fg md:h-8"
        @click="showDetails = true"
      >
        <Plus :size="14" aria-hidden="true" />{{ t("ai.review.addDetails") }}
      </button>
    </div>

    <div v-if="showDetails" class="pl-8">
      <TextArea
        :model-value="edit.description"
        :rows="2"
        :max-rows="6"
        :maxlength="2000"
        :disabled="disabled"
        :placeholder="t('ai.review.detailsPlaceholder')"
        :aria-label="t('ai.review.details')"
        @update:model-value="(value) => patch({ description: value ?? '' })"
      />
    </div>

    <div v-if="steps.length" class="flex flex-col gap-1.5 pl-8">
      <span class="flex items-center gap-1.5 text-xs font-medium text-muted"><ListChecks :size="13" aria-hidden="true" />{{ t("ai.review.checklist") }}</span>
      <div v-for="(step, stepIndex) in steps" :key="stepIndex" class="flex items-center gap-1.5">
        <span class="size-1.5 shrink-0 rounded-full bg-line-strong" aria-hidden="true" />
        <TextInput
          :model-value="step"
          :maxlength="200"
          :disabled="disabled"
          :placeholder="t('ai.review.stepPlaceholder')"
          :aria-label="t('ai.review.step', { n: stepIndex + 1 })"
          :size="size"
          class="flex-1"
          @update:model-value="(value) => setStep(stepIndex, value ?? '')"
          @keydown.enter.prevent="addStep"
        />
        <UiButton variant="ghost" size="md" class="!size-9 !px-0 text-muted md:!size-8" :aria-label="t('ai.review.removeStep', { n: stepIndex + 1 })" :disabled="disabled" @click="removeStep(stepIndex)">
          <X :size="15" aria-hidden="true" />
        </UiButton>
      </div>
      <UiButton variant="ghost" size="sm" class="w-fit" :icon="Plus" :disabled="disabled || steps.length >= 50" @click="addStep">{{ t("ai.review.addStep") }}</UiButton>
    </div>

    <ul v-if="problems.length || failure" class="flex flex-col gap-2 pl-8" :aria-label="t('ai.review.problems')">
      <li v-if="failure" class="flex items-start gap-2 rounded-[10px] bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
        <CircleAlert :size="15" class="mt-0.5 shrink-0" aria-hidden="true" />{{ failure }}
      </li>
      <li v-for="problem in problems" :key="problem" class="flex flex-col gap-2 rounded-[10px] bg-warning-soft px-3 py-2.5 text-sm text-fg sm:flex-row sm:items-center" :data-problem="problem">
        <span class="flex min-w-0 flex-1 items-start gap-2">
          <CircleAlert :size="15" class="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
          <span>{{ problemText(problem) }}</span>
        </span>
        <span class="flex flex-wrap gap-1.5 pl-6 sm:pl-0">
          <button
            v-for="fix in problemFixes(problem, edit, { timeZone, now })"
            :key="JSON.stringify(fix)"
            type="button"
            :disabled="disabled"
            class="pressable inline-flex h-9 items-center rounded-full bg-surface px-3 text-sm font-semibold text-accent-fg shadow-xs ring-1 ring-line hover:bg-surface-2 md:h-8"
            :data-fix="fix.kind"
            @click="runFix(fix)"
          >
            {{ fixLabel(fix) }}
          </button>
        </span>
      </li>
    </ul>
  </article>
</template>
