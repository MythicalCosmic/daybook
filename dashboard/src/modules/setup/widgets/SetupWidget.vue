<script setup lang="ts">
/** Overview card while "Get started" isn't finished: progress and the next step to take. */
import { ArrowRight, Rocket } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import ProgressRing from "@/components/ProgressRing.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useCompanyStore } from "@/stores/company";

import { useSetup } from "../api";
import { stepBody, stepIcon, stepTitle } from "../steps";

defineProps<{ companyId: number }>();

const i18n = useI18n();
const { t } = i18n;
const company = useCompanyStore();
const wanted = computed(() => !!company.current && !company.current.setup_completed);
const setup = useSetup(wanted);
const data = computed(() => setup.data.value);
const next = computed(() => data.value?.steps.find((s) => !s.done) ?? null);
const visible = computed(() => wanted.value && (!data.value || (!data.value.dismissed && !!next.value)));
</script>

<template>
  <!-- A banner across the Overview when it has the room, a stacked card otherwise. -->
  <section v-if="visible" class="ui-card flex h-full flex-col gap-4 p-5 @container">
    <div class="flex flex-col gap-4 @3xl:flex-row @3xl:items-center">
    <header class="flex items-center gap-3 @3xl:w-[300px] @3xl:shrink-0">
      <span class="grid size-9 place-items-center rounded-[10px] bg-accent-soft text-accent-fg"><Rocket :size="18" /></span>
      <div class="min-w-0 flex-1">
        <h2 class="text-md font-semibold text-fg">{{ t("setup.title") }}</h2>
        <p v-if="data" class="text-sm text-muted">{{ t("setup.progressTitle", { done: data.done, total: data.total }) }}</p>
        <SkeletonBlock v-else width="50%" />
      </div>
      <ProgressRing v-if="data" :value="data.done" :max="data.total" :size="40" :stroke="4" show-value />
    </header>
    <div v-if="next" class="flex min-w-0 flex-1 items-start gap-3 rounded-[10px] bg-surface-2 p-3">
      <component :is="stepIcon(next)" :size="18" class="mt-0.5 shrink-0 text-primary" />
      <div class="min-w-0 flex-1">
        <p class="text-base font-semibold text-fg">{{ stepTitle(next, i18n) }}</p>
        <p class="mt-0.5 text-sm text-muted">{{ stepBody(next, i18n) }}</p>
      </div>
    </div>
    <div class="mt-auto flex shrink-0 justify-end gap-2 @3xl:mt-0">
      <UiButton variant="ghost" size="sm" :to="`/c/${companyId}/get-started`">{{ t("setup.allSteps") }}</UiButton>
      <UiButton v-if="next" variant="primary" size="sm" :icon-right="ArrowRight" :to="`/c/${companyId}/${next.url}`">{{ t("setup.doIt") }}</UiButton>
    </div>
    </div>
  </section>
</template>
