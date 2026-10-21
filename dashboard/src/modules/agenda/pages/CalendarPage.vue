<script setup lang="ts">
/**
 * The company calendar (plan §13.5): every module's dates (company events, holidays and time off,
 * birthdays, shifts, payroll and bills, milestones…) in a month, week or agenda view, with a chip
 * per calendar to show or hide it. View, day, hidden calendars and the open event live in the URL.
 * Shortcuts: M / W / A switch views, T goes to today, N adds an event.
 */
import { CalendarDays, CalendarPlus, CalendarRange, List, Settings } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { hashIndex } from "@/lib/format";
import CalendarMonth from "@/components/CalendarMonth.vue";
import CalendarWeek from "@/components/CalendarWeek.vue";
import type { CalendarItem } from "@/components/calendarItems";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useHotkey } from "@/core/hotkeys";
import { addDays, todayIn } from "@/lib/dates";
import { companyUrl } from "@/lib/links";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCan } from "@/lib/usePermission";
import { patchQuery, rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useCalendar } from "../api";
import AgendaList from "../components/AgendaList.vue";
import AgendaSettingsPanel from "../components/AgendaSettingsPanel.vue";
import EventDialog from "../components/EventDialog.vue";
import EventDrawer from "../components/EventDrawer.vue";
import SourceToggles from "../components/SourceToggles.vue";
import UpcomingList from "../components/UpcomingList.vue";
import { byPriority, eventParam, monthChips, sourceColor, sourceLabel, toCalendarItem, windowFor } from "../lib";
import type { AgendaEvent, CalendarEntry, CalendarView } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const { isPhone } = useBreakpoints();
const canManage = useCan("agenda.manage");

const today = computed(() => todayIn(company.timezone));
const view = useRouteState<CalendarView>("view", rs.enum(["month", "week", "agenda"] as const, "month"));
const dayParam = useRouteState("d", rs.day());
const hidden = useRouteState("off", rs.list());
const newParam = useRouteState("new", rs.boolean());

const anchor = computed({
  get: () => dayParam.value ?? today.value,
  set: (day: string) => (dayParam.value = day === today.value ? null : day),
});
const month = computed({
  get: () => anchor.value.slice(0, 7),
  set: (value: string) => {
    if (value !== anchor.value.slice(0, 7)) anchor.value = `${value}-01`;
  },
});
const selected = ref<string | null>(null);

const range = computed(() => windowFor(view.value, anchor.value));
const calendar = useCalendar(range);
const upcomingRange = computed(() => ({ from: today.value, to: addDays(today.value, 6) }));
const upcoming = useCalendar(upcomingRange);
const skeleton = useDelayedPending(computed(() => calendar.isPending.value));

const sources = computed(() => (calendar.data.value?.sources ?? []).map((source) => ({ ...source, label: sourceLabel(source, t) })));
const labels = computed(() => Object.fromEntries(sources.value.map((source) => [source.key, source.label])));
const entries = computed(() => calendar.data.value?.items ?? []);
const visibleEntries = computed(() => byPriority(entries.value.filter((entry) => !hidden.value.includes(entry.source))));
const items = computed(() => visibleEntries.value.map((entry) => toCalendarItem(entry, labels.value[entry.source])));
// The month grid on wider screens: a chip per day, in calendar order (phones show dots and a day list).
const chips = computed(() => monthChips(visibleEntries.value, range.value, company.timezone, (iso) => fmt.instant(iso, "time")));
const upcomingItems = computed(() =>
  byPriority((upcoming.data.value?.items ?? []).filter((entry) => !hidden.value.includes(entry.source))).map((entry) => toCalendarItem(entry, labels.value[entry.source] ?? entry.source)),
);
const byId = computed(() => new Map([...entries.value, ...(upcoming.data.value?.items ?? [])].map((entry) => [entry.id, entry])));

const counts = computed(() => {
  const out: Record<string, number> = {};
  for (const entry of entries.value) out[entry.source] = (out[entry.source] ?? 0) + 1;
  return out;
});
const colors = computed(() => {
  const out: Record<string, string> = {};
  for (const source of sources.value) out[source.key] = sourceColor(source.key, entries.value) ?? `var(--c-chart-${hashIndex(source.key, 8) + 1})`;
  return out;
});
/** Holidays shade their day in the month and week grids. */
const holidays = computed(() => {
  const out: Record<string, string> = {};
  for (const entry of visibleEntries.value) if (entry.all_day && entry.kind.endsWith(".holiday")) out[entry.start.slice(0, 10)] = entry.title;
  return out;
});

const viewOptions = computed(() => [
  { value: "month" as const, label: t("common.calendar.month"), icon: CalendarDays },
  { value: "week" as const, label: t("common.calendar.week"), icon: CalendarRange },
  { value: "agenda" as const, label: t("agenda.view.agenda"), icon: List },
]);

// Creating: from the button, a free slot in the week, or a second click on a day.
const creating = ref(false);
const editing = ref<AgendaEvent | null>(null);
const draftDay = ref<string | null>(null);
const draftTime = ref<string | null>(null);

function create(day?: string | null, time?: string | null): void {
  if (!canManage.value) return;
  editing.value = null;
  draftDay.value = day ?? selected.value ?? (anchor.value >= today.value ? anchor.value : today.value);
  draftTime.value = time ?? null;
  creating.value = true;
}

watch(
  newParam,
  (value) => {
    if (!value) return;
    newParam.value = false;
    create();
  },
  { immediate: true },
);

function edit(event: AgendaEvent): void {
  editing.value = event;
  creating.value = true;
}

function onSaved(event: AgendaEvent): void {
  patchQuery(router, { event: String(event.id) }, false);
}

let lastDay: string | null = null;
function onDay(day: string): void {
  if (lastDay === day && canManage.value && !isPhone.value) create(day);
  lastDay = day;
}

// Other modules' dates: open their page when they have one, else show what we know.
const other = ref<CalendarEntry | null>(null);
const otherOpen = ref(false);
function open(item: CalendarItem): void {
  const entry = byId.value.get(chips.value.meta.get(String(item.id))?.origin ?? String(item.id));
  // A repeating event opens on the occurrence that was clicked, not the series' first date.
  const event = entry ? eventParam(entry) : null;
  if (event) {
    patchQuery(router, { event }, true);
    return;
  }
  if (entry?.url) {
    void router.push(companyUrl(company.currentId, entry.url));
    return;
  }
  other.value = entry ?? null;
  otherOpen.value = !!entry;
}

const settingsOpen = ref(false);

useHotkey("m", () => (view.value = "month"), { description: "agenda.hotkey.month", group: "page" });
useHotkey("w", () => (view.value = "week"), { description: "agenda.hotkey.week", group: "page" });
useHotkey("a", () => (view.value = "agenda"), { description: "agenda.hotkey.agenda", group: "page" });
useHotkey("t", () => (anchor.value = today.value), { description: "agenda.hotkey.today", group: "page" });
useHotkey("n", () => create(), { description: "agenda.hotkey.new", group: "page", enabled: () => canManage.value });
</script>

<template>
  <div>
    <PageHeader :title="t('agenda.title')" :description="t('agenda.description')">
      <template #actions>
        <IconButton v-if="canManage" :icon="Settings" :label="t('agenda.settings.title')" variant="ghost" @click="settingsOpen = true" />
        <UiButton v-if="canManage" variant="primary" :icon="CalendarPlus" kbd="N" @click="create()">{{ t("agenda.newEvent") }}</UiButton>
      </template>
    </PageHeader>

    <div class="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
      <SegmentedControl v-model="view" :options="viewOptions" :aria-label="t('agenda.view.label')" class="self-start" />
      <SourceToggles v-if="sources.length" v-model="hidden" :sources="sources" :counts="counts" :colors="colors" class="lg:ml-2" />
    </div>

    <div class="grid gap-6" :class="view === 'month' && '2xl:grid-cols-[minmax(0,1fr)_300px]'">
      <div class="min-w-0">
        <ErrorState v-if="calendar.isError.value" :error="calendar.error.value" :retry="() => calendar.refetch()" />
        <div v-else-if="skeleton" class="flex flex-col gap-3">
          <SkeletonBlock width="30%" height="24px" />
          <SkeletonBlock height="560px" radius="12px" />
        </div>
        <template v-else>
          <CalendarMonth
            v-if="view === 'month'"
            v-model:month="month"
            v-model:selected="selected"
            :items="isPhone ? items : chips.items"
            :holidays="holidays"
            :loading="calendar.isFetching.value"
            @item-click="open"
            @day-click="onDay"
          >
            <template #item="{ item }">
              <span v-if="chips.meta.get(String(item.id))?.time" class="shrink-0 tabular-nums text-muted">{{ chips.meta.get(String(item.id))?.time }}</span>
              <span class="truncate">{{ chips.meta.get(String(item.id))?.title ?? item.title }}</span>
            </template>
          </CalendarMonth>
          <CalendarWeek v-else-if="view === 'week'" v-model:week="anchor" :items="items" :holidays="holidays" @item-click="open" @slot-click="({ day, time }) => create(day, time)" />
          <AgendaList v-else v-model:anchor="anchor" :items="items" :can-create="canManage" @item-click="open" @create="create()" />
          <p v-if="view === 'month' && canManage && !isPhone" class="mt-2 text-xs text-subtle">{{ t("agenda.monthHint") }}</p>
        </template>
      </div>

      <!-- Week and agenda already list what is coming, and need the width: the rail goes with the month only
           (beside it from 1536 px, where the grid still has room for readable chips; under it below). -->
      <aside v-if="view === 'month'" class="grid min-w-0 content-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,320px)] lg:items-start 2xl:grid-cols-1">
        <section class="ui-card p-3" :aria-label="t('agenda.upcoming.title')">
          <h2 class="mb-2 px-2 pt-1 text-sm font-semibold text-fg">{{ t("agenda.upcoming.title") }}</h2>
          <div v-if="upcoming.isPending.value" class="flex flex-col gap-2 px-2"><SkeletonBlock v-for="n in 4" :key="n" height="34px" radius="8px" /></div>
          <UpcomingList v-else :items="upcomingItems" :limit="9" @item-click="open">
            <template #empty>
              <EmptyState size="sm" tone="success" :icon="CalendarDays" :title="t('agenda.upcoming.empty')" :description="t('agenda.upcoming.emptyBody')" />
            </template>
          </UpcomingList>
        </section>
        <section v-if="sources.length > 1" class="ui-card p-4 text-xs text-muted">
          <p class="mb-1 font-semibold text-fg">{{ t("agenda.sources.title") }}</p>
          <p>{{ t("agenda.sources.hint") }}</p>
        </section>
      </aside>
    </div>

    <EventDrawer @edit="edit" />
    <EventDialog v-model:open="creating" :event="editing" :day="draftDay" :time="draftTime" @saved="onSaved" />

    <UiDrawer v-model:open="otherOpen" :title="other ? (labels[other.source] ?? other.source) : ''" size="sm">
      <div v-if="other" class="flex flex-col gap-3 p-5">
        <div class="flex items-center gap-3">
          <span class="h-9 w-1.5 rounded-full" :style="{ background: colors[other.source] }" aria-hidden="true" />
          <div class="min-w-0">
            <p class="text-base font-semibold text-fg">{{ other.title }}</p>
            <p class="text-sm text-muted">
              {{ other.all_day ? fmt.day(other.start.slice(0, 10), "weekday") : `${fmt.day(other.start.slice(0, 10), "weekday")} · ${fmt.instant(other.start, "time")}` }}
            </p>
          </div>
        </div>
        <p class="text-sm text-muted">{{ t("agenda.fromSource", { source: labels[other.source] ?? other.source }) }}</p>
      </div>
    </UiDrawer>

    <UiDialog v-model:open="settingsOpen" :title="t('agenda.settings.title')" :description="t('agenda.settings.description')">
      <AgendaSettingsPanel />
    </UiDialog>
  </div>
</template>
