<script setup lang="ts">
/**
 * On learning's overview (the slot `learning.overview.cards`): the tutor's open suggestions (the
 * first three, and a way to all of them) and the weakest topics of the people the viewer sees.
 */
import { GraduationCap, Sparkles } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useCompanyStore } from "@/stores/company";

import { useSuggestions, useTutor } from "../api";
import { BAND_CELL, band } from "../lib";

defineProps<{ context: { companyId: number } }>();
const { t } = useI18n();
const company = useCompanyStore();
const allowed = computed(() => company.can(["learning.view", "learning.manage"]));
const tutor = useTutor();
const suggestions = useSuggestions();
const first = computed(() => (suggestions.data.value ?? []).slice(0, 3));
</script>

<template>
  <div v-if="allowed" class="grid gap-4 lg:grid-cols-2" data-testid="quizzes-overview-cards">
    <section class="ui-card flex flex-col gap-3 p-4">
      <div class="flex items-center gap-2">
        <Sparkles :size="18" class="text-muted" aria-hidden="true" />
        <h3 class="flex-1 text-md font-semibold text-fg">{{ t("quizzes.overview.suggestions") }}</h3>
        <span class="text-sm tabular-nums text-muted">{{ suggestions.data.value?.length ?? 0 }}</span>
      </div>
      <SkeletonBlock v-if="suggestions.isPending.value" height="72px" />
      <ul v-else-if="first.length" class="flex flex-col gap-2">
        <li v-for="row in first" :key="row.id" class="text-sm text-fg">{{ row.text }}</li>
      </ul>
      <p v-else class="text-sm text-muted">{{ t("quizzes.tutor.noSuggestions") }}</p>
      <UiButton size="sm" variant="ghost" class="self-start" :to="`/c/${company.currentId}/learning/tutor`">{{ t("quizzes.overview.openTutor") }}</UiButton>
    </section>
    <section class="ui-card flex flex-col gap-3 p-4">
      <div class="flex items-center gap-2">
        <GraduationCap :size="18" class="text-muted" aria-hidden="true" />
        <h3 class="flex-1 text-md font-semibold text-fg">{{ t("quizzes.overview.weakest") }}</h3>
      </div>
      <SkeletonBlock v-if="tutor.isPending.value" height="72px" />
      <ul v-else-if="tutor.data.value?.weakest.length" class="flex flex-col gap-2">
        <li v-for="topic in tutor.data.value.weakest.slice(0, 4)" :key="topic.id" class="flex items-center gap-3 text-sm">
          <span class="min-w-0 flex-1 truncate text-fg">{{ topic.name }}</span>
          <ProgressBar :value="topic.average ?? 0" :max="100" size="sm" tone="auto" class="w-24" />
          <span class="w-8 text-right font-semibold tabular-nums" :class="BAND_CELL[band(topic.average)].split(' ')[1]">{{ topic.average }}</span>
        </li>
      </ul>
      <p v-else class="text-sm text-muted">{{ t("quizzes.tutor.noWeakest") }}</p>
      <UiButton size="sm" variant="ghost" class="self-start" :to="`/c/${company.currentId}/learning/skills`">{{ t("quizzes.overview.openSkills") }}</UiButton>
    </section>
  </div>
</template>
