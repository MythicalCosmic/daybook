<script setup lang="ts" generic="Row">
/**
 * The console's table (plan §6.3), on TanStack Table 8 and TanStack Virtual: server pagination and
 * ordering through `useDataTable`, a Columns menu (visibility, density), row selection with a bulk
 * bar, virtual rows for long pages, a sticky header, an Export button, and a card list on phones
 * (`#card` slot). Rows are keyboard-navigable: ↑/↓ move, Enter opens, Space or X selects.
 *
 *   <DataTable :state="table" :columns="columns" :rows="data?.results" :total="data?.count" row-key="id"
 *     :loading="query.isPending.value" :fetching="query.isFetching.value" :error="query.error.value" :retry="query.refetch"
 *     selectable export-kind="finance.transactions" :export-params="filters" @row-click="open">
 *     <template #cell-amount="{ row }"><MoneyCell :value="row.amount" /></template>
 *     <template #bulk="{ selected, clear }">…</template>
 *     <template #card="{ row }">…</template>
 *   </DataTable>
 */
import { getCoreRowModel, useVueTable, type ColumnDef, type RowSelectionState, type VisibilityState } from "@tanstack/vue-table";
import { useVirtualizer } from "@tanstack/vue-virtual";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, ChevronsUpDown, Columns3, Inbox } from "@lucide/vue";
import { computed, ref, watch, type Component } from "vue";
import { useI18n } from "vue-i18n";

import { useBreakpoints } from "@/lib/useBreakpoints";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useUiStore } from "@/stores/ui";

import BulkActionBar from "./BulkActionBar.vue";
import CheckBox from "./CheckBox.vue";
import DropdownMenu, { type MenuEntry } from "./DropdownMenu.vue";
import EmptyState from "./EmptyState.vue";
import ErrorState from "./ErrorState.vue";
import ExportButton, { type PageCsv } from "./ExportButton.vue";
import IconButton from "./IconButton.vue";
import SelectBox from "./SelectBox.vue";
import SkeletonBlock from "./SkeletonBlock.vue";
import { columnValue, csvColumns, keyOf, sortField, type RowKey, type TableColumn } from "./table";
import UiButton from "./UiButton.vue";
import type { DataTableState } from "./useDataTable";

const props = withDefaults(
  defineProps<{
    state: DataTableState;
    columns: TableColumn<Row>[];
    rows: Row[] | undefined | null;
    rowKey: RowKey<Row>;
    /** Server count of all rows (pagination); default the rows given. */
    total?: number;
    loading?: boolean;
    fetching?: boolean;
    error?: unknown;
    retry?: () => unknown;
    selectable?: boolean;
    /** Rows open something (a drawer): pointer cursor, Enter, `row-click`. */
    clickable?: boolean;
    activeKey?: string | number | null;
    /** "auto" virtualizes pages longer than 60 rows. */
    virtual?: boolean | "auto";
    maxHeight?: string;
    exportKind?: string;
    exportParams?: Record<string, unknown>;
    exportSensitive?: boolean;
    /** File name of "This page as CSV" (off when empty). */
    csvName?: string;
    emptyTitle?: string;
    emptyDescription?: string;
    emptyIcon?: Component;
    /** Filters are on: the empty state says nothing matches them. */
    filtered?: boolean;
    hidePagination?: boolean;
    hideToolbar?: boolean;
    caption?: string;
    rowClass?: (row: Row) => string | undefined;
  }>(),
  {
    total: undefined,
    loading: false,
    fetching: false,
    error: undefined,
    retry: undefined,
    selectable: false,
    clickable: false,
    activeKey: null,
    virtual: "auto",
    maxHeight: "min(calc(100dvh - 240px), 860px)",
    exportKind: undefined,
    exportParams: () => ({}),
    exportSensitive: false,
    csvName: undefined,
    emptyTitle: undefined,
    emptyDescription: undefined,
    emptyIcon: undefined,
    filtered: false,
    hidePagination: false,
    hideToolbar: false,
    caption: undefined,
    rowClass: undefined,
  },
);

const emit = defineEmits<{ "row-click": [row: Row]; "clear-filters": [] }>();

defineSlots<{
  toolbar?: () => unknown;
  actions?: () => unknown;
  bulk?: (props: { selected: string[]; clear: () => void }) => unknown;
  card?: (props: { row: Row; selected: boolean }) => unknown;
  empty?: () => unknown;
  [cell: `cell-${string}`]: ((props: { row: Row; value: unknown }) => unknown) | undefined;
  [header: `header-${string}`]: ((props: { column: TableColumn<Row> }) => unknown) | undefined;
}>();

const { t } = useI18n();
const fmt = useFormat();
const ui = useUiStore();
const { isPhone } = useBreakpoints();

const data = computed<Row[]>(() => props.rows ?? []);
const total = computed(() => props.total ?? data.value.length);
const byId = computed(() => new Map(props.columns.map((column) => [column.id, column])));

// TanStack: column model, visibility and selection state (sorting and paging are on the server).
const columnDefs = computed<ColumnDef<Row, unknown>[]>(() =>
  props.columns.map((column) => ({
    id: column.id,
    header: column.header,
    accessorFn: (row: Row) => columnValue(column, row),
    enableHiding: column.hideable !== false,
    enableSorting: false,
  })),
);
const visibility = computed<VisibilityState>(() => Object.fromEntries(props.state.hiddenColumns.value.map((id) => [id, false])));
const selection = computed<RowSelectionState>(() => Object.fromEntries([...props.state.selected.value].map((id) => [id, true])));

const table = useVueTable<Row>({
  get data() {
    return data.value;
  },
  get columns() {
    return columnDefs.value;
  },
  state: {
    get columnVisibility() {
      return visibility.value;
    },
    get rowSelection() {
      return selection.value;
    },
  },
  getRowId: (row) => keyOf(props.rowKey, row),
  enableRowSelection: () => props.selectable,
  manualPagination: true,
  manualSorting: true,
  getCoreRowModel: getCoreRowModel(),
});

const visibleColumns = computed(() =>
  table
    .getVisibleLeafColumns()
    .map((column) => byId.value.get(column.id))
    .filter((column): column is TableColumn<Row> => !!column),
);
const rows = computed(() => table.getRowModel().rows);

// Density and virtual rows.
const density = computed(() => props.state.density.value ?? ui.density);
const rowHeight = computed(() => (density.value === "compact" ? 36 : 44));
const scroller = ref<HTMLElement | null>(null);
const virtualOn = computed(() => (props.virtual === "auto" ? rows.value.length > 60 : props.virtual) && !isPhone.value);
const virtualizer = useVirtualizer(
  computed(() => ({
    count: virtualOn.value ? rows.value.length : 0,
    getScrollElement: () => scroller.value,
    estimateSize: () => rowHeight.value,
    overscan: 12,
  })),
);
watch(rowHeight, () => virtualizer.value.measure());
const virtualItems = computed(() => (virtualOn.value ? virtualizer.value.getVirtualItems() : []));
const padTop = computed(() => virtualItems.value[0]?.start ?? 0);
const padBottom = computed(() => {
  const last = virtualItems.value.at(-1);
  return last ? virtualizer.value.getTotalSize() - last.end : 0;
});
const renderedRows = computed(() => (virtualOn.value ? virtualItems.value.map((item) => rows.value[item.index]!).filter(Boolean) : rows.value));

// Back to the top when the page or ordering changes.
watch([props.state.page, props.state.ordering], () => scroller.value?.scrollTo({ top: 0 }));

// Selection.
const pageKeys = computed(() => rows.value.map((row) => row.id));
const selectedOnPage = computed(() => pageKeys.value.filter((key) => props.state.isSelected(key)).length);
const allOnPage = computed(() => pageKeys.value.length > 0 && selectedOnPage.value === pageKeys.value.length);
let lastClicked: string | null = null;

function toggleAll(value: boolean): void {
  props.state.setRows(pageKeys.value, value);
}

function toggle(key: string, event?: MouseEvent | KeyboardEvent): void {
  if (event?.shiftKey && lastClicked && lastClicked !== key) {
    const from = pageKeys.value.indexOf(lastClicked);
    const to = pageKeys.value.indexOf(key);
    if (from >= 0 && to >= 0) {
      const range = pageKeys.value.slice(Math.min(from, to), Math.max(from, to) + 1);
      props.state.setRows(range, !props.state.isSelected(key));
      lastClicked = key;
      return;
    }
  }
  props.state.toggleRow(key);
  lastClicked = key;
}

// Keyboard on rows.
function onRowKeydown(event: KeyboardEvent, row: Row, key: string): void {
  const target = event.currentTarget as HTMLElement;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const sibling = (event.key === "ArrowDown" ? target.nextElementSibling : target.previousElementSibling) as HTMLElement | null;
    if (sibling?.dataset.rowKey) sibling.focus();
    else if (event.key === "ArrowDown" && virtualOn.value) virtualizer.value.scrollBy(rowHeight.value * 4);
  } else if (event.key === "Enter" && props.clickable) {
    event.preventDefault();
    emit("row-click", row);
  } else if ((event.key === " " || event.key === "x") && props.selectable) {
    event.preventDefault();
    toggle(key, event);
  }
}

function onRowClick(event: MouseEvent, row: Row): void {
  if (!props.clickable) return;
  // Clicks on links, buttons and inputs inside a cell keep their own meaning.
  if ((event.target as HTMLElement).closest("a, button, input, label, [role=checkbox]")) return;
  emit("row-click", row);
}

// Header sorting.
function headerSort(column: TableColumn<Row>): void {
  const field = sortField(column);
  if (field) props.state.toggleSort(field);
}

function ariaSort(column: TableColumn<Row>): "ascending" | "descending" | "none" | undefined {
  const field = sortField(column);
  if (!field) return undefined;
  const direction = props.state.sortDirection(field);
  return direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none";
}

// Pagination.
const pages = computed(() => Math.max(1, Math.ceil(total.value / props.state.pageSize.value)));
const fromRow = computed(() => (total.value === 0 ? 0 : (props.state.page.value - 1) * props.state.pageSize.value + 1));
const toRow = computed(() => Math.min(total.value, props.state.page.value * props.state.pageSize.value));
const sizeOptions = computed(() => props.state.pageSizes.map((size) => ({ value: size, label: t("common.table.perPageOption", { n: size }) })));

function setPage(page: number): void {
  props.state.page.value = Math.min(pages.value, Math.max(1, page));
}

function setSize(size: number | null): void {
  if (!size) return;
  props.state.pageSize.value = size;
  props.state.page.value = 1;
}

// A page past the end (rows deleted elsewhere): step back.
watch([total, pages], () => {
  if (!props.loading && props.state.page.value > pages.value) setPage(pages.value);
});

// Columns menu.
const columnsMenu = computed<MenuEntry[]>(() => [
  { type: "label", label: t("common.table.columns") },
  ...props.columns
    .filter((column) => column.hideable !== false)
    .map((column) => ({
      type: "checkbox" as const,
      label: column.header,
      checked: props.state.isColumnVisible(column.id),
      onToggle: (checked: boolean) => props.state.setColumnVisible(column.id, checked),
    })),
  { type: "separator" },
  {
    type: "radio",
    value: density.value,
    options: [
      { value: "comfortable", label: t("shell.density.comfortable") },
      { value: "compact", label: t("shell.density.compact") },
    ],
    onChange: (value: string) => (props.state.density.value = value === "compact" ? "compact" : "comfortable"),
  },
  { type: "separator" },
  { label: t("common.table.resetColumns"), onSelect: () => props.state.resetColumns() },
]);

const pageCsv = computed(() =>
  props.csvName
    ? (): PageCsv<never> => ({ filename: props.csvName!, columns: csvColumns(visibleColumns.value) as PageCsv<never>["columns"], rows: data.value as never[] })
    : undefined,
);

const skeleton = useDelayedPending(computed(() => props.loading && data.value.length === 0));
const empty = computed(() => !props.loading && !props.error && data.value.length === 0);

function cellText(column: TableColumn<Row>, row: Row): string {
  const value = columnValue(column, row);
  if (column.format) return column.format(value, row);
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return fmt.number(value, 2);
  return String(value);
}

function alignClass(column: TableColumn<Row>): string {
  const align = column.align ?? (column.numeric ? "end" : "start");
  return align === "end" ? "text-right justify-end" : align === "center" ? "text-center justify-center" : "text-left";
}

const tableMinWidth = computed(
  () => visibleColumns.value.reduce((sum, column) => sum + (column.width ?? column.minWidth ?? 140), 0) + (props.selectable ? 44 : 0),
);
</script>

<template>
  <div class="flex min-w-0 flex-col gap-3" :data-density="state.density.value ?? undefined">
    <div v-if="!hideToolbar && ($slots.toolbar || $slots.actions || exportKind || csvName || !isPhone)" class="flex flex-wrap items-center gap-2">
      <div class="flex min-w-0 flex-1 flex-wrap items-center gap-2">
        <slot name="toolbar" />
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <slot name="actions" />
        <ExportButton v-if="exportKind || csvName" :kind="exportKind" :params="exportParams" :sensitive="exportSensitive" :page-csv="pageCsv" size="md" />
        <DropdownMenu v-if="!isPhone" :items="columnsMenu" width="230px">
          <template #trigger>
            <IconButton :icon="Columns3" :label="t('common.table.columns')" variant="secondary" />
          </template>
        </DropdownMenu>
      </div>
    </div>

    <ErrorState v-if="error && !data.length" class="ui-card" :error="error" :retry="retry" />

    <!-- Phones: cards -->
    <ul v-else-if="isPhone && $slots.card" class="flex flex-col gap-2" :aria-busy="fetching || undefined">
      <template v-if="skeleton">
        <li v-for="n in 6" :key="n" class="ui-card flex flex-col gap-2 p-3"><SkeletonBlock width="55%" /><SkeletonBlock width="35%" height="12px" /></li>
      </template>
      <li
        v-for="row in rows"
        :key="row.id"
        :class="[
          'ui-card relative flex items-start gap-3 p-3 transition-colors',
          clickable && 'cursor-pointer active:bg-surface-2',
          state.isSelected(row.id) && 'border-[color-mix(in_srgb,var(--c-primary)_40%,transparent)] bg-accent-soft/50',
        ]"
        :tabindex="clickable ? 0 : undefined"
        @click="onRowClick($event, row.original)"
        @keydown.enter="clickable && emit('row-click', row.original)"
      >
        <CheckBox
          v-if="selectable"
          class="pt-0.5"
          :model-value="state.isSelected(row.id)"
          :aria-label="t('common.table.selectRow')"
          @update:model-value="state.toggleRow(row.id, $event)"
          @click.stop
        />
        <div class="min-w-0 flex-1"><slot name="card" :row="row.original" :selected="state.isSelected(row.id)" /></div>
      </li>
    </ul>

    <!-- Table -->
    <div v-else class="ui-card relative min-w-0 overflow-hidden">
      <div v-if="fetching && !skeleton" class="table-progress absolute inset-x-0 top-0 z-[3] h-0.5" aria-hidden="true" />
      <div ref="scroller" class="overflow-auto overscroll-contain" :style="{ maxHeight }">
        <table
          class="w-full table-fixed border-separate border-spacing-0 text-base"
          :style="{ minWidth: `${tableMinWidth}px` }"
          :aria-busy="fetching || loading || undefined"
          :aria-rowcount="total"
        >
          <caption v-if="caption" class="sr-only">{{ caption }}</caption>
          <colgroup>
            <col v-if="selectable" style="width: 44px" />
            <col v-for="column in visibleColumns" :key="column.id" :style="column.width ? { width: `${column.width}px` } : undefined" />
          </colgroup>
          <thead>
            <tr>
              <th v-if="selectable" scope="col" class="dt-th sticky left-0 z-[3] pl-3.5 pr-0">
                <CheckBox
                  size="sm"
                  :model-value="allOnPage"
                  :indeterminate="selectedOnPage > 0 && !allOnPage"
                  :disabled="!pageKeys.length"
                  :aria-label="t('common.table.selectAll')"
                  @update:model-value="toggleAll"
                />
              </th>
              <th
                v-for="(column, index) in visibleColumns"
                :key="column.id"
                scope="col"
                :aria-sort="ariaSort(column)"
                :class="['dt-th', column.sticky && index === 0 && 'sticky z-[3]', column.sticky && index === 0 && (selectable ? 'left-[44px]' : 'left-0')]"
                :title="column.hint"
              >
                <button
                  v-if="sortField(column)"
                  type="button"
                  :class="['group/sort -mx-1.5 inline-flex max-w-[calc(100%+12px)] items-center gap-1 rounded-[6px] px-1.5 py-0.5 hover:bg-highlight hover:text-fg', alignClass(column), 'w-full']"
                  @click="headerSort(column)"
                >
                  <span class="truncate"><slot :name="`header-${column.id}`" :column="column">{{ column.header }}</slot></span>
                  <ArrowUp v-if="state.sortDirection(sortField(column)!) === 'asc'" :size="13" class="shrink-0 text-fg" />
                  <ArrowDown v-else-if="state.sortDirection(sortField(column)!) === 'desc'" :size="13" class="shrink-0 text-fg" />
                  <ChevronsUpDown v-else :size="12" class="shrink-0 opacity-0 transition-opacity group-hover/sort:opacity-60" />
                </button>
                <span v-else :class="['flex', alignClass(column)]"
                  ><span class="truncate"><slot :name="`header-${column.id}`" :column="column">{{ column.header }}</slot></span></span
                >
              </th>
            </tr>
          </thead>
          <tbody :class="fetching && !skeleton && 'opacity-70 transition-opacity'">
            <template v-if="skeleton">
              <tr v-for="n in 8" :key="`s${n}`" class="h-[var(--row-h)]">
                <td v-if="selectable" class="dt-td"><SkeletonBlock width="15px" height="15px" radius="4px" /></td>
                <td v-for="column in visibleColumns" :key="column.id" class="dt-td">
                  <SkeletonBlock :width="column.numeric ? '60%' : `${55 + ((n * 7 + column.id.length * 3) % 35)}%`" :class="column.numeric && 'ml-auto'" />
                </td>
              </tr>
            </template>
            <template v-else>
              <tr v-if="padTop > 0" aria-hidden="true"><td :colspan="visibleColumns.length + (selectable ? 1 : 0)" :style="{ height: `${padTop}px`, padding: 0, border: 0 }" /></tr>
              <tr
                v-for="row in renderedRows"
                :key="row.id"
                :data-row-key="row.id"
                :tabindex="clickable || selectable ? 0 : undefined"
                :aria-selected="selectable ? state.isSelected(row.id) : undefined"
                :class="[
                  'dt-row group/row h-[var(--row-h)] outline-none',
                  clickable && 'cursor-pointer',
                  state.isSelected(row.id) && 'is-selected',
                  activeKey !== null && String(activeKey) === row.id && 'is-active',
                  rowClass?.(row.original),
                ]"
                @click="onRowClick($event, row.original)"
                @keydown="onRowKeydown($event, row.original, row.id)"
              >
                <td v-if="selectable" class="dt-td sticky left-0 z-[1] pl-3.5 pr-0" @click.stop>
                  <CheckBox
                    size="sm"
                    :model-value="state.isSelected(row.id)"
                    :aria-label="t('common.table.selectRow')"
                    @click="(event: MouseEvent) => { event.preventDefault(); toggle(row.id, event); }"
                  />
                </td>
                <td
                  v-for="(column, index) in visibleColumns"
                  :key="column.id"
                  :class="[
                    'dt-td',
                    column.numeric && 'tabular-nums',
                    column.sticky && index === 0 && 'sticky z-[1]',
                    column.sticky && index === 0 && (selectable ? 'left-[44px]' : 'left-0'),
                  ]"
                >
                  <div :class="['flex min-w-0 items-center', alignClass(column)]">
                    <slot :name="`cell-${column.id}`" :row="row.original" :value="columnValue(column, row.original)">
                      <span :class="['truncate', cellText(column, row.original) === '—' && 'text-subtle']">{{ cellText(column, row.original) }}</span>
                    </slot>
                  </div>
                </td>
              </tr>
              <tr v-if="padBottom > 0" aria-hidden="true"><td :colspan="visibleColumns.length + (selectable ? 1 : 0)" :style="{ height: `${padBottom}px`, padding: 0, border: 0 }" /></tr>
            </template>
          </tbody>
        </table>
        <div v-if="empty" class="border-t border-line">
          <slot name="empty">
            <EmptyState
              size="sm"
              :icon="emptyIcon ?? Inbox"
              tone="neutral"
              :title="emptyTitle ?? (filtered ? t('common.table.emptyFiltered') : t('common.table.empty'))"
              :description="emptyDescription ?? (filtered ? t('common.table.emptyFilteredHint') : undefined)"
            >
              <UiButton v-if="filtered" size="sm" @click="emit('clear-filters')">{{ t("common.filter.clearAll") }}</UiButton>
            </EmptyState>
          </slot>
        </div>
      </div>
    </div>

    <div v-if="empty && isPhone && $slots.card" class="ui-card">
      <slot name="empty">
        <EmptyState size="sm" :icon="emptyIcon ?? Inbox" tone="neutral" :title="emptyTitle ?? (filtered ? t('common.table.emptyFiltered') : t('common.table.empty'))" />
      </slot>
    </div>

    <div v-if="!hidePagination && total > 0" class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-1 text-sm text-muted">
      <span class="tabular-nums">{{ t("common.table.range", { from: fmt.number(fromRow), to: fmt.number(toRow), total: fmt.number(total) }) }}</span>
      <div class="flex items-center gap-2">
        <div v-if="!isPhone" class="flex items-center gap-1.5">
          <span>{{ t("common.table.perPage") }}</span>
          <SelectBox :model-value="state.pageSize.value" :options="sizeOptions" size="sm" variant="ghost" class="w-[84px]" @update:model-value="setSize" />
        </div>
        <span class="tabular-nums">{{ t("common.table.page", { page: state.page.value, pages }) }}</span>
        <IconButton :icon="ChevronLeft" :label="t('common.table.prev')" size="sm" variant="secondary" :disabled="state.page.value <= 1" @click="setPage(state.page.value - 1)" />
        <IconButton :icon="ChevronRight" :label="t('common.table.next')" size="sm" variant="secondary" :disabled="state.page.value >= pages" @click="setPage(state.page.value + 1)" />
      </div>
    </div>

    <BulkActionBar v-if="selectable" :count="state.selectedIds.value.length" @clear="state.clearSelection()">
      <slot name="bulk" :selected="state.selectedIds.value" :clear="state.clearSelection" />
    </BulkActionBar>
  </div>
</template>

<style scoped>
.dt-th {
  position: sticky;
  top: 0;
  z-index: 2;
  height: 36px;
  padding: 0 12px;
  border-bottom: 1px solid var(--c-border);
  background: color-mix(in srgb, var(--c-surface-2) 82%, var(--c-surface));
  color: var(--c-muted);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.01em;
  text-align: left;
  white-space: nowrap;
}
[data-theme="dark"] .dt-th {
  background: var(--c-surface-2);
}
.dt-td {
  padding: 0 12px;
  border-bottom: 1px solid var(--c-border);
  background: var(--c-surface);
  color: var(--c-text);
  vertical-align: middle;
  transition: background-color var(--dur-press) var(--ease-standard);
}
tbody tr:last-child .dt-td {
  border-bottom-color: transparent;
}
.dt-row:hover .dt-td {
  background: color-mix(in srgb, var(--c-surface-2) 55%, var(--c-surface));
}
.dt-row.is-selected .dt-td {
  background: color-mix(in srgb, var(--c-accent-soft) 70%, var(--c-surface));
}
.dt-row.is-active .dt-td {
  background: var(--c-accent-soft);
}
.dt-row.is-active .dt-td:first-child {
  box-shadow: inset 2px 0 0 var(--c-primary);
}
.dt-row:focus-visible .dt-td {
  background: color-mix(in srgb, var(--c-surface-2) 70%, var(--c-surface));
}
.dt-row:focus-visible .dt-td:first-child {
  box-shadow: inset 2px 0 0 var(--c-ring);
}
.table-progress {
  overflow: hidden;
  background: color-mix(in srgb, var(--c-primary) 15%, transparent);
}
.table-progress::after {
  content: "";
  position: absolute;
  inset-block: 0;
  width: 30%;
  background: var(--c-primary);
  animation: table-progress 1s var(--ease-standard) infinite;
}
@keyframes table-progress {
  from {
    left: -30%;
  }
  to {
    left: 100%;
  }
}
</style>
