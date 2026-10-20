/**
 * The state behind a DataTable (plan §6.3): server pagination, DRF `ordering`, column visibility
 * (remembered per table in this browser), row selection that survives page changes, and an optional
 * density override. With `url` the page, page size and ordering live in the URL (plan §6.5).
 *
 *   const table = useDataTable({ id: "finance.transactions", ordering: "-date", url: true });
 *   watch(filters, table.resetPage, { deep: true });
 *   const query = useQuery({
 *     queryKey: computed(() => qk(cid, "finance", "transactions", { ...filters.value, ...table.params.value })),
 *     queryFn: () => listTransactions(cid, { ...filters.value, ...table.params.value }),
 *     placeholderData: keepPreviousData,
 *   });
 *   <DataTable :state="table" :columns="columns" :rows="query.data.value?.results" :total="query.data.value?.count" … />
 */
import { computed, ref, shallowRef, type ComputedRef, type Ref, type WritableComputedRef } from "vue";
import { useRoute, useRouter } from "vue-router";

import { readStored, writeStored } from "@/lib/storage";
import { patchQuery } from "@/lib/useRouteState";
import type { Density } from "@/stores/ui";

export interface DataTableOptions {
  /** Remembers hidden columns under this id ("finance.transactions"). */
  id?: string;
  pageSize?: number;
  pageSizes?: number[];
  /** Default ordering, DRF style: "-created_at". Empty for the server's default. */
  ordering?: string;
  /** Keep page, page size and ordering in the URL; a string prefixes the keys (two tables on a page). */
  url?: boolean | string;
  /** Columns hidden until the person shows them. */
  hidden?: string[];
}

export interface TableParams {
  page: number;
  page_size: number;
  ordering?: string;
}

export type SortDirection = "asc" | "desc";

export interface DataTableState {
  readonly id: string | undefined;
  page: Ref<number> | WritableComputedRef<number>;
  pageSize: Ref<number> | WritableComputedRef<number>;
  ordering: Ref<string> | WritableComputedRef<string>;
  readonly pageSizes: number[];
  readonly defaultOrdering: string;
  /** For the API call. */
  params: ComputedRef<TableParams>;
  hiddenColumns: Ref<string[]>;
  isColumnVisible: (id: string) => boolean;
  setColumnVisible: (id: string, visible: boolean) => void;
  resetColumns: () => void;
  sortDirection: (field: string) => SortDirection | null;
  toggleSort: (field: string) => void;
  selected: Ref<ReadonlySet<string>>;
  selectedIds: ComputedRef<string[]>;
  isSelected: (key: string) => boolean;
  toggleRow: (key: string, value?: boolean) => void;
  setRows: (keys: readonly string[], value: boolean) => void;
  clearSelection: () => void;
  /** Back to page 1 (call when filters change). */
  resetPage: () => void;
  /** Per-table density; null follows the person's setting. */
  density: Ref<Density | null>;
}

/**
 * Next ordering after clicking a column: ascending, then descending, then back to the default.
 * A column that is the default descending ordering goes to ascending first, so a click always changes something.
 */
export function nextOrdering(current: string, field: string, fallback: string): string {
  if (current === field) return `-${field}`;
  if (current === `-${field}`) return `-${field}` === fallback ? field : fallback;
  return field;
}

export function directionOf(ordering: string, field: string): SortDirection | null {
  const first = ordering.split(",")[0] ?? "";
  if (first === field) return "asc";
  if (first === `-${field}`) return "desc";
  return null;
}

function useUrlNumber(key: string, fallback: number): WritableComputedRef<number> {
  const route = useRoute();
  const router = useRouter();
  return computed({
    get: () => {
      const raw = route.query[key];
      const value = Number(Array.isArray(raw) ? raw[0] : raw);
      return Number.isInteger(value) && value > 0 ? value : fallback;
    },
    set: (value) => patchQuery(router, { [key]: value === fallback ? undefined : String(value) }),
  });
}

function useUrlString(key: string, fallback: string): WritableComputedRef<string> {
  const route = useRoute();
  const router = useRouter();
  return computed({
    get: () => {
      const raw = route.query[key];
      const value = Array.isArray(raw) ? raw[0] : raw;
      return typeof value === "string" ? value : fallback;
    },
    set: (value) => patchQuery(router, { [key]: value === fallback ? undefined : value }),
  });
}

export function useDataTable(options: DataTableOptions = {}): DataTableState {
  const pageSizes = options.pageSizes ?? [25, 50, 100, 200];
  const defaultSize = options.pageSize ?? 50;
  const defaultOrdering = options.ordering ?? "";
  const prefix = typeof options.url === "string" ? options.url : "";

  const page = options.url ? useUrlNumber(`${prefix}page`, 1) : ref(1);
  const pageSize = options.url ? useUrlNumber(`${prefix}page_size`, defaultSize) : ref(defaultSize);
  const ordering = options.url ? useUrlString(`${prefix}ordering`, defaultOrdering) : ref(defaultOrdering);

  const storageKey = options.id ? `table.${options.id}.hidden` : null;
  const initialHidden = options.hidden ?? [];
  const hiddenColumns = ref<string[]>(
    storageKey ? readStored<string[]>(storageKey, initialHidden, (v): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string")) : [...initialHidden],
  );

  function saveHidden(): void {
    if (storageKey) writeStored(storageKey, hiddenColumns.value);
  }

  const selected = shallowRef<ReadonlySet<string>>(new Set());

  function setSelected(next: Set<string>): void {
    selected.value = next;
  }

  const state: DataTableState = {
    id: options.id,
    page,
    pageSize,
    ordering,
    pageSizes,
    defaultOrdering,
    params: computed(() => {
      const params: TableParams = { page: page.value, page_size: pageSize.value };
      if (ordering.value) params.ordering = ordering.value;
      return params;
    }),
    hiddenColumns,
    isColumnVisible: (id) => !hiddenColumns.value.includes(id),
    setColumnVisible: (id, visible) => {
      const without = hiddenColumns.value.filter((item) => item !== id);
      hiddenColumns.value = visible ? without : [...without, id];
      saveHidden();
    },
    resetColumns: () => {
      hiddenColumns.value = [...initialHidden];
      saveHidden();
    },
    sortDirection: (field) => directionOf(ordering.value, field),
    toggleSort: (field) => {
      ordering.value = nextOrdering(ordering.value, field, defaultOrdering);
      page.value = 1;
    },
    selected,
    selectedIds: computed(() => [...selected.value]),
    isSelected: (key) => selected.value.has(key),
    toggleRow: (key, value) => {
      const next = new Set(selected.value);
      const on = value ?? !next.has(key);
      if (on) next.add(key);
      else next.delete(key);
      setSelected(next);
    },
    setRows: (keys, value) => {
      const next = new Set(selected.value);
      for (const key of keys) {
        if (value) next.add(key);
        else next.delete(key);
      }
      setSelected(next);
    },
    clearSelection: () => setSelected(new Set()),
    resetPage: () => {
      if (page.value !== 1) page.value = 1;
    },
    density: ref<Density | null>(null),
  };
  return state;
}
