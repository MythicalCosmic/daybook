<script setup lang="ts">
/**
 * Performance reviews (plan §13.4 "Reviews"): review rounds with the people's own answers and
 * their managers', goals and the outcome. Open rounds first with how far everyone has got and the
 * reviews waiting for the viewer, then drafts, then closed rounds. "New round" (and `?new=1` from
 * the palette) opens the four-step wizard with a pharmacy's ready questions. A first visit
 * explains the three steps.
 */
import { ClipboardPen, MessageSquareText, PenLine, Plus, Sparkles, TrendingUp } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import RoundCard from "../components/reviews/RoundCard.vue";
import RoundWizard from "../components/reviews/RoundWizard.vue";
import { useRounds } from "../reviews/api";
import type { Round } from "../reviews/types";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();

const rounds = useRounds();
const all = computed(() => rounds.data.value ?? []);
const open = computed(() => all.value.filter((round) => round.status === "self" || round.status === "manager"));
const drafts = computed(() => all.value.filter((round) => round.status === "draft"));
const closed = computed(() => all.value.filter((round) => round.status === "closed"));
const waiting = computed(() => open.value.reduce((sum, round) => sum + round.mine, 0));
const firstWaiting = computed(() => open.value.find((round) => round.mine > 0) ?? null);

const creating = ref(false);
const newParam = useRouteState("new", rs.boolean(false));
watch(
  newParam,
  (value) => {
    if (!value) return;
    newParam.value = false;
    creating.value = true;
  },
  { immediate: true },
);
function opened(round: Round): void {
  void router.push({ path: `/c/${company.currentId}/lifecycle/reviews/${round.id}` });
}
const STEPS = [
  { icon: ClipboardPen, key: "one" },
  { icon: MessageSquareText, key: "two" },
  { icon: TrendingUp, key: "three" },
] as const;
</script>

<template>
  <div class="flex flex-col gap-6">
    <PageHeader :title="t('lifecycle.nav.reviews')" :description="t('lifecycle.reviews.description')">
      <template #actions>
        <UiButton variant="primary" :icon="Plus" @click="creating = true">{{ t("lifecycle.reviews.newRound") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="rounds.isPending.value" class="grid gap-4 lg:grid-cols-2">
      <SkeletonBlock v-for="n in 4" :key="n" height="180px" radius="16px" />
    </div>
    <ErrorState v-else-if="rounds.isError.value" :error="rounds.error.value" :retry="() => rounds.refetch()" />

    <!-- The first visit: what a round is, in three steps -->
    <section v-else-if="!all.length" class="ui-card overflow-hidden" data-reviews-empty>
      <div class="bg-gradient-to-br from-[color-mix(in_srgb,var(--c-primary)_10%,transparent)] via-transparent to-transparent px-5 py-8 text-center sm:px-10 sm:py-12">
        <span class="mx-auto grid size-14 place-items-center rounded-[18px] bg-primary-soft text-primary"><Sparkles :size="26" aria-hidden="true" /></span>
        <h2 class="mt-4 text-xl font-semibold text-fg">{{ t("lifecycle.reviews.empty.title") }}</h2>
        <p class="mx-auto mt-2 max-w-xl text-sm text-muted">{{ t("lifecycle.reviews.empty.body") }}</p>
        <ol class="mx-auto mt-8 grid max-w-3xl gap-3 text-left sm:grid-cols-3">
          <li v-for="(step, index) in STEPS" :key="step.key" class="rounded-[14px] border border-line bg-surface p-4">
            <div class="mb-2 flex items-center gap-2">
              <span class="grid size-7 place-items-center rounded-full bg-primary text-xs font-semibold text-white">{{ index + 1 }}</span>
              <component :is="step.icon" :size="16" class="text-primary" aria-hidden="true" />
            </div>
            <p class="text-sm font-semibold text-fg">{{ t(`lifecycle.reviews.empty.${step.key}Title`) }}</p>
            <p class="mt-1 text-xs text-muted">{{ t(`lifecycle.reviews.empty.${step.key}Body`) }}</p>
          </li>
        </ol>
        <UiButton class="mt-8" variant="primary" :icon="Plus" @click="creating = true">{{ t("lifecycle.reviews.empty.start") }}</UiButton>
      </div>
    </section>

    <template v-else>
      <RouterLink
        v-if="waiting && firstWaiting"
        :to="{ path: `/c/${company.currentId}/lifecycle/reviews/${firstWaiting.id}`, query: { mine: '1' } }"
        class="flex items-center gap-3 rounded-[16px] border border-[color-mix(in_srgb,var(--c-primary)_30%,transparent)] bg-primary-soft/60 px-4 py-3.5 transition-colors hover:bg-primary-soft"
        data-waiting
      >
        <span class="grid size-10 shrink-0 place-items-center rounded-[12px] bg-primary text-white"><PenLine :size="18" aria-hidden="true" /></span>
        <div class="min-w-0 flex-1">
          <p class="text-sm font-semibold text-fg">{{ t("lifecycle.reviews.waitingTitle", { count: waiting }, waiting) }}</p>
          <p class="truncate text-xs text-muted">{{ t("lifecycle.reviews.waitingBody", { name: firstWaiting.name, date: fmt.day(firstWaiting.manager_due_on, "medium") }) }}</p>
        </div>
        <span class="text-sm font-medium text-primary">{{ t("lifecycle.reviews.waitingOpen") }}</span>
      </RouterLink>

      <section v-if="open.length" class="flex flex-col gap-3" data-section="open">
        <h2 class="text-sm font-semibold uppercase tracking-wide text-subtle">{{ t("lifecycle.reviews.sections.open") }}</h2>
        <div class="grid gap-4 lg:grid-cols-2"><RoundCard v-for="round in open" :key="round.id" :round="round" /></div>
      </section>
      <section v-if="drafts.length" class="flex flex-col gap-3" data-section="drafts">
        <h2 class="text-sm font-semibold uppercase tracking-wide text-subtle">{{ t("lifecycle.reviews.sections.drafts") }}</h2>
        <div class="grid gap-4 lg:grid-cols-2"><RoundCard v-for="round in drafts" :key="round.id" :round="round" /></div>
      </section>
      <section v-if="closed.length" class="flex flex-col gap-3" data-section="closed">
        <h2 class="text-sm font-semibold uppercase tracking-wide text-subtle">{{ t("lifecycle.reviews.sections.closed") }}</h2>
        <div class="grid gap-4 lg:grid-cols-2"><RoundCard v-for="round in closed" :key="round.id" :round="round" /></div>
      </section>
    </template>

    <RoundWizard v-model:open="creating" @saved="opened" />
  </div>
</template>
