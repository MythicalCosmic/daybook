<script setup lang="ts">
/** Overview widget "Coming up": the next seven days from every calendar the person may see. */
import { ArrowRight, CalendarDays } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRouter } from "vue-router";

import type { Range } from "@/api/types";
import type { CalendarItem } from "@/components/calendarItems";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { addDays, todayIn } from "@/lib/dates";
import { companyUrl } from "@/lib/links";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useCompanyStore } from "@/stores/company";

import { useCalendar } from "../api";
import UpcomingList from "../components/UpcomingList.vue";
import { eventIdOf, sourceLabel, toCalendarItem } from "../lib";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const router = useRouter();
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));
const calendar = useCalendar(computed(() => ({ from: today.value, to: addDays(today.value, 6) })));
const skeleton = useDelayedPending(computed(() => calendar.isPending.value));
const labels = computed(() => Object.fromEntries((calendar.data.value?.sources ?? []).map((source) => [source.key, sourceLabel(source, t)])));
const items = computed(() => (calendar.data.value?.items ?? []).map((entry) => toCalendarItem(entry, labels.value[entry.source])));
const base = computed(() => `/c/${props.companyId}/calendar`);

function open(item: CalendarItem): void {
  const entry = calendar.data.value?.items.find((row) => row.id === String(item.id));
  if (!entry) return;
  const eventId = eventIdOf(entry);
  if (eventId) void router.push({ path: base.value, query: { event: String(eventId) } });
  else if (entry.url) void router.push(companyUrl(props.companyId, entry.url));
  else void router.push({ path: base.value, query: { view: "agenda" } });
}
</script>

<template>
  <section class="ui-card flex h-full min-w-0 flex-col" :aria-label="t('agenda.upcoming.title')">
    <header class="flex items-center gap-2 px-4 pb-2 pt-4">
      <CalendarDays :size="16" class="text-subtle" aria-hidden="true" />
      <h3 class="text-sm font-semibold text-fg">{{ t("agenda.upcoming.title") }}</h3>
      <span class="flex-1" />
      <RouterLink :to="base" class="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">
        {{ t("agenda.upcoming.open") }}<ArrowRight :size="14" />
      </RouterLink>
    </header>
    <div class="min-h-0 flex-1 px-2 pb-3">
      <div v-if="skeleton" class="flex flex-col gap-2 p-2"><SkeletonBlock v-for="n in 4" :key="n" height="32px" radius="8px" /></div>
      <ErrorState v-else-if="calendar.isError.value" compact :error="calendar.error.value" :retry="() => calendar.refetch()" class="m-2" />
      <UpcomingList v-else-if="calendar.data.value" :items="items" :limit="6" @item-click="open">
        <template #empty>
          <EmptyState size="sm" tone="success" :icon="CalendarDays" :title="t('agenda.upcoming.empty')" :description="t('agenda.upcoming.emptyBody')" />
        </template>
      </UpcomingList>
    </div>
  </section>
</template>
