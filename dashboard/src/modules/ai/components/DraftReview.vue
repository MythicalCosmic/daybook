<script setup lang="ts">
/**
 * The review of a ready draft: what was heard (a quote that opens in full), the AI's questions,
 * and each task as an editable card. Used by the dictate dialog and the voice note drawer; the
 * host draws "Create N tasks" from `review`.
 */
import { ChevronDown, CircleHelp, Quote } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { useCompanyPeople } from "@/components/pickers";
import { useCompanyStore } from "@/stores/company";

import type { Review } from "../review";
import type { AiDraft } from "../types";
import DraftCard from "./DraftCard.vue";

const props = withDefaults(defineProps<{ draft: AiDraft; review: Review; disabled?: boolean }>(), { disabled: false });

const { t } = useI18n();
const company = useCompanyStore();
const people = useCompanyPeople(
  computed(() => true),
  computed(() => ({ status: "active" })),
);
const myId = computed(() => company.current?.membership_id ?? 0);
const quoteOpen = ref(false);
const longQuote = computed(() => props.draft.transcript.length > 160);

/** "Couldn't create" per kept card, after apply. */
const failures = computed(() => {
  const out = new Map<string, string>();
  const result = props.review.result.value;
  if (!result) return out;
  const kept = props.review.edits.value.filter((edit) => !edit.removed);
  for (const failure of result.failed) {
    const edit = kept[failure.index];
    if (edit) out.set(edit.key, failure.detail);
  }
  return out;
});
</script>

<template>
  <div class="flex flex-col gap-4" data-testid="draft-review">
    <figure v-if="draft.transcript" class="relative rounded-card bg-surface-2 px-4 py-3 dark:bg-surface-3">
      <figcaption class="mb-1 flex items-center gap-1.5 text-xs font-semibold text-muted">
        <Quote :size="13" aria-hidden="true" />{{ draft.audio ? t("ai.review.heard") : t("ai.review.typed") }}
      </figcaption>
      <blockquote :class="['whitespace-pre-line text-base leading-[1.5] text-fg', !quoteOpen && longQuote && 'line-clamp-2']">{{ draft.transcript }}</blockquote>
      <button
        v-if="longQuote"
        type="button"
        class="mt-1 inline-flex h-8 items-center gap-1 text-sm font-medium text-accent-fg"
        :aria-expanded="quoteOpen"
        @click="quoteOpen = !quoteOpen"
      >
        {{ quoteOpen ? t("ai.review.less") : t("ai.review.more") }}
        <ChevronDown :size="14" :class="['transition-transform', quoteOpen && 'rotate-180']" aria-hidden="true" />
      </button>
    </figure>

    <div v-if="draft.questions.length" class="flex flex-col gap-1.5 rounded-card border border-[color-mix(in_srgb,var(--c-info)_24%,transparent)] bg-info-soft/70 px-4 py-3">
      <p class="flex items-center gap-1.5 text-sm font-semibold text-info"><CircleHelp :size="15" aria-hidden="true" />{{ t("ai.review.questions") }}</p>
      <p v-for="(question, index) in draft.questions" :key="index" class="text-base text-fg">{{ question }}</p>
    </div>

    <p v-if="!review.edits.value.length" class="rounded-card border border-dashed border-line px-4 py-6 text-center text-base text-muted">{{ t("ai.review.none") }}</p>
    <TransitionGroup tag="div" name="list" class="relative flex flex-col gap-3">
      <DraftCard
        v-for="(edit, index) in review.edits.value"
        :key="edit.key"
        v-model="review.edits.value[index]!"
        :index="index"
        :people="people.data.value ?? []"
        :my-id="myId"
        :time-zone="company.timezone"
        :disabled="disabled"
        :failure="failures.get(edit.key) ?? null"
      />
    </TransitionGroup>
  </div>
</template>
