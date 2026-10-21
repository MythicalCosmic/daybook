<script setup lang="ts">
/**
 * Photo wall (plan §1.3): a day's proof photos, grouped by branch or by routine. Owners check
 * photos first; a photo opens large, its caption opens the task.
 */
import { Camera, ChevronLeft, ChevronRight, Repeat, Store } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DatePicker from "@/components/DatePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProofThumb from "@/components/ProofThumb.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { addDays, todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { patchQuery, rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useProofWall } from "../api";
import TaskDrawer from "../components/TaskDrawer.vue";
import type { TaskRow } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));

const dayParam = useRouteState("day", rs.day());
const day = computed({
  get: () => dayParam.value ?? today.value,
  set: (value: string | null) => (dayParam.value = value && value !== today.value ? value : null),
});
const group = useRouteState("group", rs.enum(["branch", "routine"] as const, "branch"));

const query = useProofWall(computed(() => ({ day: day.value })));
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const items = computed(() => query.data.value?.items ?? []);

const groups = computed(() => {
  const map = new Map<string, { key: string; title: string; items: TaskRow[] }>();
  for (const task of items.value) {
    const key = group.value === "branch" ? String(task.branch?.id ?? "none") : String(task.routine?.id ?? "none");
    const title = group.value === "branch" ? (task.branch?.name ?? t("tasks.photos.noBranch")) : (task.routine?.title ?? t("tasks.photos.givenByHand"));
    if (!map.has(key)) map.set(key, { key, title, items: [] });
    map.get(key)!.items.push(task);
  }
  return [...map.values()].sort((a, b) => b.items.length - a.items.length);
});

function open(task: TaskRow): void {
  patchQuery(router, { task: String(task.id) }, true);
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <PageHeader :title="t('tasks.photos.title')" :description="t('tasks.photos.description')" />

    <div class="flex flex-wrap items-center gap-2">
      <div class="flex items-center gap-1">
        <IconButton :icon="ChevronLeft" :label="t('tasks.photos.previousDay')" variant="secondary" @click="day = addDays(day, -1)" />
        <DatePicker v-model="day" :max="today" format="weekday" class="w-[230px]" />
        <IconButton :icon="ChevronRight" :label="t('tasks.photos.nextDay')" variant="secondary" :disabled="day >= today" @click="day = addDays(day, 1)" />
      </div>
      <span class="flex-1" />
      <p v-if="items.length" class="text-sm text-muted">{{ t("tasks.photos.count", { n: items.length }, items.length) }}</p>
      <SegmentedControl
        v-model="group"
        size="sm"
        :options="[
          { value: 'branch', label: t('tasks.photos.byBranch'), icon: Store },
          { value: 'routine', label: t('tasks.photos.byRoutine'), icon: Repeat },
        ]"
      />
    </div>

    <div v-if="skeleton" class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <SkeletonBlock v-for="n in 10" :key="n" height="180px" radius="12px" />
    </div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.data.value && !items.length" class="ui-card">
      <EmptyState :icon="Camera" tone="neutral" size="lg" :title="t('tasks.photos.emptyTitle')" :description="day === today ? t('tasks.photos.emptyToday') : t('tasks.photos.emptyDay', { day: fmt.day(day, 'long') })" />
    </div>
    <div v-else class="flex flex-col gap-6">
      <section v-for="section in groups" :key="section.key" :aria-label="section.title">
        <h2 class="mb-2.5 flex items-center gap-2 text-sm font-semibold text-fg">
          <component :is="group === 'branch' ? Store : Repeat" :size="15" class="text-subtle" />{{ section.title }}
          <span class="text-xs font-medium text-subtle">{{ section.items.length }}</span>
        </h2>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
          <figure v-for="task in section.items" :key="task.id" class="ui-card group/photo flex min-w-0 flex-col overflow-hidden">
            <div class="aspect-[4/3] w-full overflow-hidden bg-surface-2">
              <ProofThumb
                :src="task.proof_thumb ?? task.proof_photo"
                :images="[{ src: task.proof_photo ?? task.proof_thumb ?? '', thumb: task.proof_thumb ?? undefined, caption: `${task.title} · ${task.assignee.name}` }]"
                size="fill"
                class="!rounded-none"
                :label="task.completed_at ? fmt.instant(task.completed_at, 'time') : undefined"
              />
            </div>
            <figcaption class="flex min-w-0 items-center gap-2 px-2.5 py-2">
              <UserAvatar :name="task.assignee.name" :src="task.assignee.photo_url" :size="22" />
              <button type="button" class="min-w-0 flex-1 text-left" @click="open(task)">
                <span class="block truncate text-sm font-medium text-fg hover:underline">{{ task.title }}</span>
                <span class="block truncate text-xs text-muted">{{ task.assignee.name }}</span>
              </button>
            </figcaption>
          </figure>
        </div>
      </section>
    </div>

    <TaskDrawer />
  </div>
</template>
