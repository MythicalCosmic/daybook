<script setup lang="ts">
/** Overview widget "Coming up": the next seven days from every calendar the person may see. */
import { CalendarDays } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import type { Range } from "@/api/types";
import { withoutEcho, type CalendarItem } from "@/components/calendarItems";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import WidgetCard from "@/components/WidgetCard.vue";
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
// The calendar's name only when the title doesn't already say it ("Jasur · time off" needs no "Time off").
const items = computed(() => (calendar.data.value?.items ?? []).map((entry) => withoutEcho(toCalendarItem(entry, labels.value[entry.source]))));
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
  <WidgetCard :title="t('agenda.upcoming.title')" :icon="CalendarDays" :to="base" :link-label="t('agenda.upcoming.open')">
    <div v-if="skeleton" class="flex flex-col gap-2 p-2"><SkeletonBlock v-for="n in 4" :key="n" height="32px" radius="8px" /></div>
    <ErrorState v-else-if="calendar.isError.value" compact :error="calendar.error.value" :retry="() => calendar.refetch()" class="m-2" />
    <UpcomingList v-else-if="calendar.data.value" :items="items" :limit="8" @item-click="open">
      <template #empty>
        <EmptyState class="my-auto" size="sm" tone="success" :icon="CalendarDays" :title="t('agenda.upcoming.empty')" :description="t('agenda.upcoming.emptyBody')" />
      </template>
    </UpcomingList>
  </WidgetCard>
</template>
