/** Column definitions for DataTable, in a plain module so pages can type them without importing the component. */
import type { CsvColumn } from "@/lib/csv";

export interface TableColumn<Row> {
  /** Unique; also the `cell-<id>` slot name and, when `sortable: true`, the ordering field. */
  id: string;
  /** Already translated. */
  header: string;
  /** The cell's value; default `row[id]`. */
  value?: (row: Row) => unknown;
  /** Text of the default cell; default the value as text, "—" when empty. */
  format?: (value: unknown, row: Row) => string;
  /** `true` sorts by `id`; a string names the DRF ordering field ("member__name"). */
  sortable?: boolean | string;
  align?: "start" | "center" | "end";
  /** Fixed width in px; columns without one share the rest. */
  width?: number;
  /** Width the column never shrinks below (px); default 120. */
  minWidth?: number;
  /** The person may hide it from the Columns menu (default true). */
  hideable?: boolean;
  /** Tabular digits, aligned to the end (amounts, counts). */
  numeric?: boolean;
  /** Keep the first column visible while scrolling sideways. */
  sticky?: boolean;
  /** Short help on the header. */
  hint?: string;
  /** Value for the "This page as CSV" download; default `value`. */
  csv?: (row: Row) => unknown;
}

export function columnValue<Row>(column: TableColumn<Row>, row: Row): unknown {
  return column.value ? column.value(row) : (row as Record<string, unknown>)[column.id];
}

export function sortField<Row>(column: TableColumn<Row>): string | null {
  if (!column.sortable) return null;
  return typeof column.sortable === "string" ? column.sortable : column.id;
}

/** CSV columns for the visible table columns. */
export function csvColumns<Row>(columns: readonly TableColumn<Row>[]): CsvColumn<Row>[] {
  return columns.map((column) => ({
    key: column.id,
    label: column.header,
    value: (row: Row) => (column.csv ? column.csv(row) : columnValue(column, row)),
  }));
}

export type RowKey<Row> = keyof Row | ((row: Row) => string | number);

export function keyOf<Row>(rowKey: RowKey<Row>, row: Row): string {
  return String(typeof rowKey === "function" ? rowKey(row) : row[rowKey]);
}
