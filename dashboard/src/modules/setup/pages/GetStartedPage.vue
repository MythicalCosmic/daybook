<script setup lang="ts">
/**
 * Get started (plan §6.2): a card per registered step with why it matters and a "Do it" button to
 * the page that does it, a tick when it's done, and a progress ring. Steps of switched-off modules
 * (and steps the person can't act on) aren't listed. "Dismiss for now" hides the sidebar pill for
 * everyone; the page stays reachable from the palette and can be brought back.
 */
import { ArrowRight, Check, EyeOff, PartyPopper, Rocket, RotateCcw } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useCompanyStore } from "@/stores/company";

import { useSetup, useSetupVisibility } from "../api";
import { stepBody, stepIcon, stepTitle } from "../steps";

const i18n = useI18n();
const { t } = i18n;
const company = useCompanyStore();
const setup = useSetup();
const visibility = useSetupVisibility();
const confirm = useConfirm();
const showSkeleton = useDelayedPending(() => setup.isPending.value);

const data = computed(() => setup.data.value);
const percent = computed(() => (data.value?.total ? Math.round((data.value.done / data.value.total) * 100) : 0));
const allDone = computed(() => !!data.value && data.value.total > 0 && data.value.done === data.value.total);
const nextKey = computed(() => data.value?.steps.find((s) => !s.done)?.key ?? null);
const path = (url: string) => `/c/${company.currentId}/${url.replace(/^\/+/, "")}`;

async function dismiss(): Promise<void> {
  const answer = await confirm({ title: t("setup.dismissTitle"), message: t("setup.dismissBody"), confirmLabel: t("setup.dismiss"), icon: EyeOff });
  if (!answer) return;
  await visibility.dismiss.mutateAsync();
  toast.success(t("setup.dismissed"), { action: { label: t("common.undo"), onClick: () => visibility.resume.mutate() } });
}
</script>

<template>
  <div class="mx-auto max-w-[920px]">
    <PageHeader :title="t('setup.title')" :description="t('setup.description', { company: company.current?.name ?? '' })">
      <template v-if="data?.can_dismiss" #actions>
        <UiButton v-if="!data.dismissed" variant="ghost" :icon="EyeOff" :loading="visibility.dismiss.isPending.value" @click="dismiss">{{ t("setup.dismiss") }}</UiButton>
        <UiButton v-else variant="ghost" :icon="RotateCcw" :loading="visibility.resume.isPending.value" @click="visibility.resume.mutate()">{{ t("setup.resume") }}</UiButton>
      </template>
    </PageHeader>

    <ErrorState v-if="setup.isError.value" :error="setup.error.value" :retry="() => setup.refetch()" :retrying="setup.isFetching.value" />

    <div v-else-if="showSkeleton || !data" class="flex flex-col gap-4" aria-busy="true">
      <div class="ui-card flex items-center gap-5 p-6"><SkeletonBlock circle width="88px" height="88px" /><div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="40%" height="20px" /><SkeletonBlock width="70%" /></div></div>
      <div v-for="n in 4" :key="n" class="ui-card flex items-center gap-4 p-4"><SkeletonBlock width="40px" height="40px" radius="10px" /><div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="35%" /><SkeletonBlock width="60%" /></div></div>
    </div>

    <EmptyState v-else-if="!data.total" :title="t('setup.emptyTitle')" :description="t('setup.emptyBody')" :icon="Rocket" />

    <div v-else class="flex flex-col gap-5">
      <!-- Progress -->
      <section :class="['ui-card relative flex flex-wrap items-center gap-5 overflow-hidden p-5 md:p-6', allDone && 'border-[color-mix(in_srgb,var(--c-success)_40%,var(--c-border))]']">
        <div class="setup-glow pointer-events-none absolute inset-0 -z-0" aria-hidden="true" />
        <div class="relative">
          <ProgressRing :value="data.done" :max="data.total" :size="88" :stroke="8" :tone="allDone ? 'success' : 'primary'" />
          <span class="absolute inset-0 grid place-items-center">
            <PartyPopper v-if="allDone" :size="28" class="text-success" />
            <span v-else class="text-lg font-bold tabular-nums text-fg">{{ percent }}%</span>
          </span>
        </div>
        <div class="relative min-w-0 flex-1 basis-[240px]">
          <p class="text-lg font-semibold text-fg">{{ allDone ? t("setup.allDoneTitle") : t("setup.progressTitle", { done: data.done, total: data.total }) }}</p>
          <p class="mt-1 text-base text-muted">{{ allDone ? t("setup.allDoneBody") : t("setup.progressBody") }}</p>
        </div>
      </section>

      <!-- Steps -->
      <TransitionGroup tag="ol" name="list" class="flex flex-col gap-3">
        <li
          v-for="(step, index) in data.steps"
          :key="step.key"
          :class="[
            'ui-card group flex flex-wrap items-center gap-x-4 gap-y-3 p-4 transition-[border-color,box-shadow] duration-200',
            step.key === nextKey && 'border-[color-mix(in_srgb,var(--c-primary)_40%,var(--c-border))] shadow-[0_0_0_3px_var(--c-accent-soft)]',
            step.done && 'bg-[color-mix(in_srgb,var(--c-surface)_70%,var(--c-canvas))]',
          ]"
        >
          <span
            :class="[
              'relative grid size-11 shrink-0 place-items-center rounded-[12px] transition-colors',
              step.done ? 'bg-success-soft text-success' : step.key === nextKey ? 'bg-primary text-on-primary' : 'bg-surface-2 text-muted',
            ]"
          >
            <Check v-if="step.done" :size="20" :stroke-width="2.5" />
            <component :is="stepIcon(step)" v-else :size="20" />
          </span>
          <div class="min-w-0 flex-1 basis-[220px]">
            <p :class="['flex flex-wrap items-center gap-2 text-base font-semibold', step.done ? 'text-muted line-through decoration-[1.5px]' : 'text-fg']">
              <span class="text-xs font-semibold tabular-nums text-subtle no-underline">{{ index + 1 }}.</span>
              {{ stepTitle(step, i18n) }}
              <span v-if="step.key === nextKey" class="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent-fg no-underline">{{ t("setup.next") }}</span>
            </p>
            <p class="mt-0.5 text-sm text-muted">{{ stepBody(step, i18n) }}</p>
          </div>
          <UiButton
            v-if="!step.done"
            :to="path(step.url)"
            :variant="step.key === nextKey ? 'primary' : 'secondary'"
            :icon-right="ArrowRight"
            class="max-sm:w-full"
          >{{ t("setup.doIt") }}</UiButton>
          <UiButton v-else :to="path(step.url)" variant="ghost" size="sm" class="text-muted max-sm:w-full">{{ t("setup.review") }}</UiButton>
        </li>
      </TransitionGroup>

      <p class="text-center text-sm text-muted">{{ t("setup.footer") }}</p>
    </div>
  </div>
</template>

<style scoped>
.setup-glow {
  background: radial-gradient(28rem 12rem at 0% 0%, color-mix(in srgb, var(--c-chart-1) 9%, transparent), transparent 70%);
}
.list-move {
  transition: transform var(--dur-drawer) var(--ease-out);
}
</style>
