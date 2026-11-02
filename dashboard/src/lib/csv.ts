/**
 * Client-side CSV for small tables (chart data, the current page). Big exports go through the
 * server (`useExport`), which also sends the file to Telegram.
 */
import { toast } from "@/components/useToast";
import { t } from "@/i18n";
export interface CsvColumn<Row> {
  key: string;
  label: string;
  /** Defaults to `row[key]`. */
  value?: (row: Row) => unknown;
}

export interface CsvOptions {
  /** Excel needs the byte order mark to read UTF-8 (Cyrillic, o‘). Default true. */
  bom?: boolean;
  delimiter?: string;
}

/**
 * A cell that starts with = + - @ (or a tab/CR) would run as a formula in Excel. Text gets a leading
 * apostrophe; real numbers (like "-15000.00") are left alone.
 */
export function guardFormula(text: string): string {
  if (/^[=+\-@\t\r]/.test(text) && !/^[-+]?\d+(\.\d+)?$/.test(text)) return `'${text}`;
  return text;
}

export function csvCell(value: unknown, delimiter = ","): string {
  if (value === null || value === undefined) return "";
  const text = guardFormula(value instanceof Date ? value.toISOString() : String(value));
  if (text.includes(delimiter) || /["\r\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

export function toCsv<Row>(columns: readonly CsvColumn<Row>[], rows: readonly Row[], options: CsvOptions = {}): string {
  const delimiter = options.delimiter ?? ",";
  const lines = [columns.map((c) => csvCell(c.label, delimiter)).join(delimiter)];
  for (const row of rows) {
    lines.push(
      columns
        .map((column) => csvCell(column.value ? column.value(row) : (row as Record<string, unknown>)[column.key], delimiter))
        .join(delimiter),
    );
  }
  return (options.bom === false ? "" : "﻿") + lines.join("\r\n") + "\r\n";
}

/** "data:image/png;base64,…" → a Blob, without fetch (the console's CSP `connect-src 'self'` blocks data: URLs). */
export function dataUrlBlob(url: string): Blob {
  const comma = url.indexOf(",");
  const head = url.slice(0, comma);
  const data = url.slice(comma + 1);
  const type = /^data:([^;,]+)/.exec(head)?.[1] ?? "application/octet-stream";
  const bytes = head.endsWith(";base64") ? Uint8Array.from(atob(data), (c) => c.charCodeAt(0)) : new TextEncoder().encode(decodeURIComponent(data));
  return new Blob([bytes], { type });
}

/**
 * Saves text or a Blob as a file. Telegram's webview ignores `<a download>` (and Telegram's own
 * download prompt only takes an https link), so inside Telegram the phone's share sheet takes the
 * file (Save to Files, a chat); where there is none (Android's webview) a toast says to use a browser.
 */
export function downloadFile(filename: string, content: string | Blob, type = "text/csv;charset=utf-8"): void {
  const blob = typeof content === "string" ? new Blob([content], { type }) : content;
  if (window.Telegram?.WebApp?.initData) {
    const file = new File([blob], filename, { type: blob.type || type });
    if (navigator.canShare?.({ files: [file] })) void navigator.share({ files: [file], title: filename }).catch(() => undefined);
    else toast.warning(t("common.export.noSaveInTelegram"));
    return;
  }
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** "Transactions 2026-10-20.csv" with characters Windows refuses replaced. */
export function safeFilename(name: string, extension: string): string {
  const base = name.replace(/[\\/:*?"<>|]+/g, "-").replace(/\s+/g, " ").trim() || "export";
  return `${base}.${extension.replace(/^\./, "")}`;
}
