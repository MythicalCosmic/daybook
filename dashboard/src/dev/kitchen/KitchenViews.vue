<script setup lang="ts">
/** Kitchen: records (timeline, history, markdown), calendars, the tree, heatmaps, board and timeline. */
import { BookOpen, CircleCheck, FileText, Pencil, Plus, Store, TriangleAlert } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import AuditTrail from "@/components/AuditTrail.vue";
import AvatarStack from "@/components/AvatarStack.vue";
import CalendarMonth from "@/components/CalendarMonth.vue";
import CalendarWeek from "@/components/CalendarWeek.vue";
import type { CalendarItem } from "@/components/calendarItems";
import type { GanttZoom } from "@/components/gantt";
import GanttTimeline from "@/components/GanttTimeline.vue";
import HeatmapGrid, { type HeatmapAxis } from "@/components/HeatmapGrid.vue";
import IconButton from "@/components/IconButton.vue";
import type { KanbanMove } from "@/components/kanban";
import KanbanBoard from "@/components/KanbanBoard.vue";
import MarkdownView from "@/components/MarkdownView.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import TextInput from "@/components/TextInput.vue";
import TimelineList, { type TimelineEvent } from "@/components/TimelineList.vue";
import { locate, moveNode, type TreeMove } from "@/components/tree";
import TreeList from "@/components/TreeList.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { addDays, formatDay, startOfWeek, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import KitchenSection from "./KitchenSection.vue";
import KitchenSpecimen from "./KitchenSpecimen.vue";
import { BOARD_COLUMNS, boardCards, calendarItems, ganttRows, KNOWLEDGE, PEOPLE, seeded, type DemoCard } from "./kitchenData";

const { t } = useI18n();
const k = (key: string, params?: Record<string, unknown>) => t(`dev.kitchen.${key}`, params ?? {});
const fmt = useFormat();
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));

// Records.
const minutesAgo = (n: number) => new Date(Date.now() - n * 60_000).toISOString();
const events = computed<TimelineEvent[]>(() => [
  { key: 1, at: minutesAgo(6), title: k("tl.verified"), icon: CircleCheck, tone: "success", actor: { name: "Dilnoza Karimova" } },
  { key: 2, at: minutesAgo(40), title: k("tl.difference"), body: k("tl.differenceBody"), icon: TriangleAlert, tone: "warning", actor: null },
  { key: 3, at: minutesAgo(52), title: k("tl.closed"), icon: Store, tone: "primary", actor: { name: "Aziz Karimov" }, meta: "CHL-1042" },
  { key: 4, at: minutesAgo(60 * 26), title: k("tl.edited"), icon: Pencil, actor: { name: "Bekzod Mirzayev" } },
  { key: 5, at: minutesAgo(60 * 50), title: k("tl.opened"), icon: Store, tone: "info", actor: { name: "Aziz Karimov" } },
]);
const markdown = computed(
  () => `**${k("md.lead")}** member:14, member:31 ${k("md.and")} [Bekzod](member:12).\n\n- ${k("md.point1")} task:345\n- ${k("md.point2")} shift:1042\n- ${k("md.point3")}\n\n| ${k("branch")} | ${k("md.net")} | ${k("md.change")} |\n|---|---:|---:|\n| Chilonzor | 6 140 000 | +8% |\n| Yunusobod | 0 | −100% |\n\n> ${k("md.quote")}`,
);

// Calendars.
const month = ref(today.value.slice(0, 7));
const day = ref<string | null>(today.value);
const week = ref(startOfWeek(today.value));
const items = computed<CalendarItem[]>(() => calendarItems(today.value));
const holidays = computed(() => ({ [addDays(today.value, 11)]: "Teachers’ day" }));

// Tree.
const tree = ref(KNOWLEDGE);
const page = ref<string | number | null>("close");
const expanded = ref<Array<string | number>>(["ops", "close"]);
function moveTreeNode(move: TreeMove): void {
  tree.value = moveNode(tree.value, move);
}

// Heatmap: hours worked, people × days.
const heatPeople: HeatmapAxis[] = PEOPLE.slice(1, 8).map((p) => ({ key: String(p.id), label: p.name, sublabel: p.subtitle?.split(" · ")[0] }));
const heatDays = computed<HeatmapAxis[]>(() =>
  Array.from({ length: 14 }, (_, i) => {
    const d = addDays(today.value, i - 13);
    return { key: d, label: formatDay(d, fmt.lang.value, "weekdayShort"), short: String(Number(d.slice(8))) };
  }),
);
const hours = (() => {
  const random = seeded(7);
  const map = new Map<string, number | null>();
  for (const person of heatPeople) for (let i = 0; i < 14; i++) map.set(`${person.key}:${i}`, random() < 0.15 ? null : Math.round((4 + random() * 7) * 2) / 2);
  return map;
})();

// Board.
const cards = ref<DemoCard[]>(boardCards(today.value));
const quickTitle = ref("");
function onMove(move: KanbanMove<DemoCard>): void {
  // Optimistic: the page applies the move at once (and would save it to the server here).
  const rest = cards.value.filter((card) => card.id !== move.item.id);
  const byColumn = BOARD_COLUMNS.map((column) => rest.filter((card) => card.list === column.id));
  byColumn[BOARD_COLUMNS.findIndex((column) => column.id === move.to)]?.splice(move.index, 0, { ...move.item, list: move.to });
  cards.value = byColumn.flat();
  toast.success(k("moved", { title: move.item.title, column: BOARD_COLUMNS.find((c) => c.id === move.to)?.title ?? move.to }));
}
function addCard(column: string, close: () => void): void {
  if (!quickTitle.value.trim()) return close();
  cards.value = [...cards.value, { id: Date.now(), key: `RENO-${cards.value.length + 21}`, title: quickTitle.value.trim(), list: column, assignee: PEOPLE[0]!, due: today.value, labels: [], checklist: [0, 0], allowed: BOARD_COLUMNS.map((c) => c.id) }];
  quickTitle.value = "";
  close();
}

// Timeline.
const zoom = ref<GanttZoom>("week");
const rows = ref(ganttRows(today.value));
function reschedule(change: { rowId: string | number; barId: string | number; start: string; end: string }): void {
  rows.value = rows.value.map((row) => (row.id !== change.rowId ? row : { ...row, bars: row.bars.map((bar) => (bar.id === change.barId ? { ...bar, start: change.start, end: change.end } : bar)) }));
}
function moveMilestone(change: { rowId: string | number; milestoneId: string | number; date: string }): void {
  rows.value = rows.value.map((row) =>
    row.id !== change.rowId ? row : { ...row, milestones: row.milestones?.map((m) => (m.id === change.milestoneId ? { ...m, date: change.date } : m)) },
  );
}
const calendarView = ref<"month" | "week">("month");
const notify = (text: string) => toast.info(text);
</script>

<template>
  <KitchenSection id="records" :title="k('section.records')" :description="k('section.recordsHint')">
    <KitchenSpecimen name="TimelineList.vue">
      <TimelineList :events="events" :new-keys="[1]" />
    </KitchenSpecimen>
    <KitchenSpecimen name="MarkdownView.vue" :note="k('mdNote')">
      <MarkdownView :source="markdown" :labels="{ 'member:14': 'Madina', 'member:31': 'Aziz', 'task:345': 'Stock count', 'shift:1042': 'CHL-1042' }" />
    </KitchenSpecimen>
    <KitchenSpecimen name="AuditTrail.vue" :note="k('auditNote')">
      <AuditTrail target-type="finance.transaction" :target-id="7002" />
    </KitchenSpecimen>
    <KitchenSpecimen name="TreeList.vue" :note="k('treeNote')">
      <div class="grid gap-4 sm:grid-cols-[minmax(0,260px)_1fr]">
        <TreeList v-model:selected="page" v-model:expanded="expanded" :nodes="tree" draggable :max-depth="3" :label="k('knowledge')" @move="moveTreeNode">
          <template #actions="{ node }">
            <IconButton :icon="Plus" :label="k('addPage')" size="sm" :tooltip="false" @click="notify(`${k('addPage')} · ${node.label}`)" />
          </template>
        </TreeList>
        <div class="rounded-[10px] border border-dashed border-line-strong p-4 text-sm text-muted">
          <p class="flex items-center gap-2 font-semibold text-fg"><BookOpen :size="15" />{{ (page !== null && locate(tree, page)?.node.label) || "—" }}</p>
          <p class="mt-1">{{ k("treeHelp") }}</p>
        </div>
      </div>
    </KitchenSpecimen>
  </KitchenSection>

  <KitchenSection id="calendars" :title="k('section.calendars')" :description="k('section.calendarsHint')">
    <KitchenSpecimen name="CalendarMonth.vue · CalendarWeek.vue" wide>
      <CalendarMonth v-if="calendarView === 'month'" v-model:month="month" v-model:selected="day" :items="items" :holidays="holidays" @item-click="(item) => notify(item.title)">
        <template #toolbar>
          <SegmentedControl v-model="calendarView" :options="[{ value: 'month', label: t('common.calendar.month') }, { value: 'week', label: t('common.calendar.week') }]" size="sm" />
        </template>
      </CalendarMonth>
      <div v-else class="flex flex-col gap-3">
        <SegmentedControl v-model="calendarView" :options="[{ value: 'month', label: t('common.calendar.month') }, { value: 'week', label: t('common.calendar.week') }]" size="sm" />
        <CalendarWeek v-model:week="week" :items="items" :holidays="holidays" @item-click="(item) => notify(item.title)" @slot-click="(slot) => notify(`${slot.day} ${slot.time}`)" />
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="HeatmapGrid.vue" :note="k('heatNote')" wide>
      <HeatmapGrid
        :rows="heatPeople"
        :columns="heatDays"
        :value="(row, column) => hours.get(`${row.key}:${heatDays.findIndex((d) => d.key === column.key)}`) ?? null"
        :format="(v) => fmt.duration(v * 60)"
        :cell-format="(v) => fmt.number(v, 1)"
        show-values
        clickable
        :cell-size="34"
        :row-label-width="170"
        :label="k('heatNote')"
        @cell-click="(cell) => notify(`${cell.row.label} · ${cell.column.label}`)"
      />
    </KitchenSpecimen>
  </KitchenSection>

  <KitchenSection id="boards" :title="k('section.boards')" :description="k('section.boardsHint')">
    <KitchenSpecimen name="KanbanBoard.vue" :note="k('boardNote')" wide flush canvas>
      <div class="p-3">
        <KanbanBoard
          :columns="BOARD_COLUMNS"
          :items="cards"
          :item-key="(card) => card.id"
          :column-of="(card) => card.list"
          :can-drop="(card, _from, to) => card.allowed.includes(to)"
          height="470px"
          @move="onMove"
        >
          <template #card="{ item }">
            <div class="flex items-center gap-1.5">
              <span class="font-mono text-[11px] font-semibold text-subtle">{{ item.key }}</span>
              <span v-for="label in item.labels" :key="label.name" class="rounded-full px-1.5 py-px text-[10px] font-semibold" :style="{ background: `color-mix(in srgb, ${label.color} 18%, var(--c-surface))`, color: 'var(--c-text)' }">{{
                label.name
              }}</span>
            </div>
            <p class="mt-1.5 text-sm font-semibold leading-5 text-fg">{{ item.title }}</p>
            <div class="mt-2.5 flex items-center gap-2 text-xs text-muted">
              <span :class="['inline-flex items-center gap-1 tabular-nums', item.due < today && item.list !== 'done' && 'font-semibold text-danger']">
                <FileText :size="12" />{{ fmt.day(item.due, "short") }}
              </span>
              <span v-if="item.checklist[1]" class="inline-flex items-center gap-1 tabular-nums">
                <CircleCheck :size="12" :class="item.checklist[0] === item.checklist[1] && 'text-success'" />{{ item.checklist[0] }}/{{ item.checklist[1] }}
              </span>
              <span class="flex-1" />
              <AvatarStack :people="[item.assignee]" :size="20" :tooltips="false" />
            </div>
          </template>
          <template #quick-add="{ column, close }">
            <form class="flex flex-col gap-2" @submit.prevent="addCard(column.id, close)">
              <TextInput v-model="quickTitle" size="sm" autofocus :placeholder="k('cardTitle')" @keydown.esc="close" />
              <div class="flex justify-end gap-1.5">
                <UiButton size="sm" variant="ghost" @click="close">{{ t("common.cancel") }}</UiButton>
                <UiButton size="sm" variant="primary" type="submit">{{ t("common.create") }}</UiButton>
              </div>
            </form>
          </template>
          <template #column-actions="{ column }">
            <ProgressRing v-if="column.id === 'done'" :value="cards.filter((c) => c.list === 'done').length" :max="cards.length" :size="18" :stroke="3" tone="success" />
          </template>
        </KanbanBoard>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="GanttTimeline.vue" :note="k('ganttNote')" wide>
      <GanttTimeline v-model:zoom="zoom" :rows="rows" max-height="380px" :label="k('projects')" @change="reschedule" @milestone-change="moveMilestone" @bar-click="({ bar }) => notify(bar.label ?? '')" />
    </KitchenSpecimen>
  </KitchenSection>
</template>
