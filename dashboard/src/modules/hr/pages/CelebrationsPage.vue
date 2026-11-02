<script setup lang="ts">
/**
 * Celebrations (plan §6.2 HR): birthdays (of people who show theirs) and work anniversaries in a
 * month, as a calm list by day with today marked, and a month calendar beside it on wide screens.
 * The month is in the URL (`?month=2026-11`).
 */
import { Award, Cake, ChevronLeft, ChevronRight, PartyPopper } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import CalendarMonth from "@/components/CalendarMonth.vue";
import { monthOf, shiftMonth } from "@/components/calendar";
import type { CalendarItem } from "@/components/calendarItems";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { endOfMonth } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useCelebrations, useHrSettings } from "../api";
import { hrAccess } from "../lib";
import type { Celebration } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();
const access = computed(() => hrAccess((perm) => company.can(perm)));

const monthParam = useRouteState("month", rs.string(""));
const month = computed({
  get: () => (/^\d{4}-\d{2}$/.test(monthParam.value) ? monthParam.value : monthOf(today.value)),
  set: (value: string) => (monthParam.value = value === monthOf(today.value) ? "" : value),
});
const range = computed(() => ({ from: `${month.value}-01`, to: endOfMonth(`${month.value}-01`) }));
const query = useCelebrations(range);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const settings = useHrSettings(computed(() => access.value.manage));
const switchedOff = computed(() => settings.data.value?.celebrations_enabled === false);

const rows = computed(() => [...(query.data.value ?? [])].sort((a, b) => a.day.localeCompare(b.day) || a.member.name.localeCompare(b.member.name)));
const days = computed(() => {
  const groups: Array<{ day: string; items: Celebration[] }> = [];
  for (const row of rows.value) {
    const last = groups.at(-1);
    if (last && last.day === row.day) last.items.push(row);
    else groups.push({ day: row.day, items: [row] });
  }
  return groups;
});
const counts = computed(() => ({
  birthdays: rows.value.filter((row) => row.kind === "birthday").length,
  anniversaries: rows.value.filter((row) => row.kind === "anniversary").length,
}));

const items = computed<CalendarItem[]>(() =>
  rows.value.map((row) => ({
    id: `${row.kind}-${row.member.id}-${row.day}`,
    kind: row.kind,
    title: row.member.name,
    start: row.day,
    all_day: true,
    color: row.kind === "birthday" ? "var(--c-chart-1)" : "var(--c-chart-3)",
    url: `/c/${company.currentId}/people/${row.member.id}`,
  })),
);

function what(row: Celebration): string {
  if (row.kind === "birthday") return t("hr.celebrations.birthday");
  return row.years ? t("hr.celebrations.years", { n: row.years }, row.years) : t("hr.celebrations.anniversary");
}
function dayLabel(day: string): string {
  if (day === today.value) return t("hr.overview.today");
  return fmt.day(day, "weekday");
}
</script>

<template>
  <div>
    <PageHeader :title="t('hr.nav.celebrations')" :description="t('hr.celebrations.description')">
      <template #actions>
        <div class="flex items-center gap-1">
          <IconButton :icon="ChevronLeft" variant="secondary" :label="t('common.date.prevMonth')" @click="month = shiftMonth(month, -1)" />
          <span class="min-w-[136px] text-center text-sm font-semibold text-fg">{{ fmt.day(`${month}-01`, "monthYear") }}</span>
          <IconButton :icon="ChevronRight" variant="secondary" :label="t('common.date.nextMonth')" @click="month = shiftMonth(month, 1)" />
        </div>
        <UiButton v-if="month !== monthOf(today)" variant="ghost" @click="month = monthOf(today)">{{ t("hr.celebrations.thisMonth") }}</UiButton>
      </template>
    </PageHeader>

    <InlineAlert v-if="switchedOff" class="mb-4" tone="info" size="sm" :title="t('hr.celebrations.offTitle')" :description="t('hr.celebrations.offBody')">
      <template #actions><UiButton size="sm" :to="`/c/${company.currentId}/settings/hr`">{{ t("hr.settings.open") }}</UiButton></template>
    </InlineAlert>

    <ErrorState v-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else class="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,400px)]">
      <section class="ui-card hidden p-4 lg:block" :aria-label="t('hr.celebrations.calendar')">
        <CalendarMonth v-model:month="month" :items="items" :loading="query.isPending.value" :max-per-day="2" />
      </section>

      <section class="ui-card flex flex-col p-4" :aria-label="t('hr.celebrations.list')">
        <header class="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
          <h2 class="flex-1 text-sm font-semibold text-fg">{{ fmt.day(`${month}-01`, "monthYear") }}</h2>
          <span v-if="rows.length" class="inline-flex items-center gap-1 text-xs text-muted"><Cake :size="13" class="text-[var(--c-chart-1)]" aria-hidden="true" />{{ counts.birthdays }}</span>
          <span v-if="rows.length" class="inline-flex items-center gap-1 text-xs text-muted"><Award :size="13" class="text-[var(--c-chart-3)]" aria-hidden="true" />{{ counts.anniversaries }}</span>
        </header>
        <div v-if="skeleton" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 5" :key="n" height="48px" /></div>
        <EmptyState v-else-if="query.data.value && !rows.length" size="sm" tone="neutral" :icon="PartyPopper" :title="t('hr.celebrations.emptyTitle')" :description="t('hr.celebrations.emptyBody')" />
        <ol v-else class="flex flex-col gap-3">
          <li v-for="group in days" :key="group.day" :class="group.day < today && 'opacity-60'">
            <p :class="['mb-1 text-xs font-semibold', group.day === today ? 'text-primary' : 'text-muted']">{{ dayLabel(group.day) }}</p>
            <ul class="-mx-2 flex flex-col">
              <li v-for="row in group.items" :key="`${row.kind}-${row.member.id}`">
                <RouterLink :to="`/c/${company.currentId}/people/${row.member.id}`" class="flex min-h-12 items-center gap-3 rounded-[10px] px-2 py-1.5 hover:bg-highlight">
                  <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="34" />
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-semibold text-fg">{{ row.member.name }}</p>
                    <p class="truncate text-xs text-muted">{{ row.position ?? "" }}</p>
                  </div>
                  <span
                    :class="[
                      'inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold',
                      row.kind === 'birthday' ? 'bg-accent-soft text-accent-fg' : 'bg-info-soft text-info',
                    ]"
                  >
                    <component :is="row.kind === 'birthday' ? Cake : Award" :size="12" aria-hidden="true" />{{ what(row) }}
                  </span>
                </RouterLink>
              </li>
            </ul>
          </li>
        </ol>
      </section>
    </div>
  </div>
</template>
