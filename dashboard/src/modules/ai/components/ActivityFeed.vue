<script setup lang="ts">
/**
 * What the agents did, newest first and grouped by day: who it was about (their photo, or the
 * agent's icon), the sentence, the record it touched as a chip that opens it, and the time. New
 * items slide in at the top and glow for a moment; older ones load as the list scrolls down.
 */
import { AudioLines, CircleAlert, CircleCheck, ListChecks, UserRound } from "@lucide/vue";
import { useIntersectionObserver } from "@vueuse/core";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import UiButton from "@/components/UiButton.vue";
import UiSpinner from "@/components/UiSpinner.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { addDays, formatDay, todayIn, zonedDay } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { subjectPath } from "../lib";
import type { ActivityItem, SubjectType } from "../types";
import AgentIcon from "./AgentIcon.vue";

const props = withDefaults(
  defineProps<{
    items: ActivityItem[];
    fresh?: number[];
    hasOlder?: boolean;
    loadingOlder?: boolean;
    olderFailed?: boolean;
    /** Fewer details (the agent drawer): no agent names, no day headings. */
    compact?: boolean;
    /** Load older pages by themselves when the end comes into view. */
    autoload?: boolean;
  }>(),
  { fresh: () => [], hasOlder: false, loadingOlder: false, olderFailed: false, compact: false, autoload: true },
);
const emit = defineEmits<{ older: [] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();

const SUBJECT_ICON: Record<SubjectType, typeof ListChecks> = { task: ListChecks, member: UserRound, draft: AudioLines };

const groups = computed(() => {
  const today = todayIn(company.timezone);
  const out: Array<{ day: string; label: string; items: ActivityItem[] }> = [];
  for (const item of props.items) {
    const day = zonedDay(item.created_at, company.timezone);
    let group = out.at(-1);
    if (!group || group.day !== day) {
      const label =
        day === today ? t("common.today") : day === addDays(today, -1) ? t("common.yesterday") : formatDay(day, fmt.lang.value, day.slice(0, 4) === today.slice(0, 4) ? "weekday" : "long");
      group = { day, label, items: [] };
      out.push(group);
    }
    group.items.push(item);
  }
  return props.compact ? [{ day: "", label: "", items: props.items }] : out;
});

const sentinel = ref<HTMLElement | null>(null);
useIntersectionObserver(
  sentinel,
  ([entry]) => {
    if (entry?.isIntersecting && props.autoload && props.hasOlder && !props.loadingOlder && !props.olderFailed) emit("older");
  },
  { rootMargin: "240px" },
);
</script>

<template>
  <div class="flex flex-col gap-5" data-testid="ai-activity">
    <section v-for="group in groups" :key="group.day">
      <h3 v-if="group.label" class="mb-2 px-1 text-xs font-semibold uppercase tracking-[0.05em] text-subtle">{{ group.label }}</h3>
      <TransitionGroup tag="ol" name="list" class="relative flex flex-col">
        <li
          v-for="item in group.items"
          :key="item.id"
          :class="['ai-feed-item relative flex gap-3 rounded-[10px] px-1 py-2.5', fresh.includes(item.id) && 'live-glow']"
          :data-level="item.level"
          :data-id="item.id"
        >
          <span class="relative mt-0.5 shrink-0">
            <UserAvatar v-if="item.actor" :name="item.actor.name" :src="item.actor.photo" :size="32" />
            <AgentIcon v-else :name="item.icon" size="sm" class="!size-8" />
            <span
              v-if="item.level !== 'info'"
              :class="[
                'absolute -bottom-0.5 -right-0.5 grid size-4 place-items-center rounded-full ring-2 ring-[var(--c-surface)]',
                item.level === 'success' ? 'bg-success-soft text-success' : 'bg-warning-soft text-warning',
              ]"
              aria-hidden="true"
            >
              <CircleCheck v-if="item.level === 'success'" :size="11" />
              <CircleAlert v-else :size="11" />
            </span>
          </span>
          <div class="min-w-0 flex-1">
            <p class="text-base leading-[1.45] text-fg">{{ item.text }}</p>
            <div class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-xs text-muted">
              <RouterLink
                v-if="item.subject && company.currentId"
                :to="subjectPath(item.subject, company.currentId)"
                class="pressable inline-flex h-7 min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 text-xs font-medium text-fg hover:border-line-strong hover:bg-surface-2"
                :data-subject="item.subject.type"
              >
                <component :is="SUBJECT_ICON[item.subject.type]" :size="13" class="shrink-0 text-muted" aria-hidden="true" />
                <span class="truncate">{{ item.subject.label }}</span>
              </RouterLink>
              <span v-if="!compact" class="truncate">{{ item.agent_name }}</span>
              <span v-if="!compact" class="text-subtle" aria-hidden="true">·</span>
              <time :datetime="item.created_at" class="num shrink-0 text-subtle" :title="fmt.instant(item.created_at)">{{ compact ? fmt.relative(item.created_at) : fmt.instant(item.created_at, "time") }}</time>
            </div>
          </div>
        </li>
      </TransitionGroup>
    </section>
    <div ref="sentinel" class="flex min-h-10 items-center justify-center">
      <UiSpinner v-if="loadingOlder" :label="t('ai.activity.loadingOlder')" />
      <UiButton v-else-if="hasOlder" variant="ghost" size="lg" @click="emit('older')">{{ olderFailed ? t("ai.activity.olderFailed") : t("ai.activity.older") }}</UiButton>
      <p v-else-if="items.length && !compact" class="text-sm text-subtle">{{ t("ai.activity.end") }}</p>
    </div>
  </div>
</template>
