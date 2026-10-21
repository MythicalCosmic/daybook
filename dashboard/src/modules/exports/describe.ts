/**
 * An export's parameters in words for the list ("14–20 Oct · Late only · 2 branches"), never the
 * API's keys ("due_to: 2026-10-20 · overdue: true"). Exporters take free-form params, so this reads
 * the shapes the pages send: a period (`from`/`to`, `start`/`end`, `due_from`/`due_to`, any
 * `*_from`/`*_to`), a `month`, a single `date`/`day`, a search, a few known switches and lists of
 * branches or people. Anything else only says the list was filtered.
 */
import type { Language } from "@/api/types";
import { formatDay, formatRange } from "@/lib/dates";

type Translate = (key: string, named?: Record<string, unknown>, plural?: number) => string;

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const MONTH = /^\d{4}-\d{2}$/;
const PERIOD_PAIRS: Array<[string, string]> = [
  ["from", "to"],
  ["start", "end"],
  ["date_from", "date_to"],
  ["due_from", "due_to"],
];
/** Switches worth naming when on; the rest are filters like any other. */
const SWITCHES: Record<string, string> = { overdue: "exports.param.overdue" };
const LISTS: Record<string, string> = {
  branch: "exports.param.branches",
  branches: "exports.param.branches",
  branch_ids: "exports.param.branches",
  assignee: "exports.param.people",
  member: "exports.param.people",
  members: "exports.param.people",
  member_ids: "exports.param.people",
  position: "exports.param.positions",
  positions: "exports.param.positions",
};

const isDay = (value: unknown): value is string => typeof value === "string" && DAY.test(value);
const filled = (value: unknown) => value !== null && value !== undefined && value !== "" && value !== false && !(Array.isArray(value) && !value.length);

export function describeParams(params: Record<string, unknown> | null | undefined, t: Translate, lang: Language): string {
  const entries = Object.entries(params ?? {}).filter(([, value]) => filled(value));
  if (!entries.length) return "";
  const values = Object.fromEntries(entries);
  const used = new Set<string>();
  const parts: string[] = [];

  const pairs = [...PERIOD_PAIRS];
  for (const key of Object.keys(values)) {
    if (key.endsWith("_from")) {
      const end = `${key.slice(0, -5)}_to`;
      if (!pairs.some(([a]) => a === key)) pairs.push([key, end]);
    }
  }
  for (const [startKey, endKey] of pairs) {
    const start = values[startKey];
    const end = values[endKey];
    if (!isDay(start) && !isDay(end)) continue;
    used.add(startKey).add(endKey);
    if (isDay(start) && isDay(end)) parts.push(start === end ? formatDay(start, lang, "medium") : formatRange({ from: start, to: end }, lang));
    else if (isDay(start)) parts.push(t("exports.param.since", { day: formatDay(start, lang, "medium") }));
    else parts.push(t("exports.param.until", { day: formatDay(end as string, lang, "medium") }));
  }
  if (typeof values.month === "string" && MONTH.test(values.month)) {
    used.add("month");
    parts.push(formatDay(`${values.month}-01`, lang, "monthYear"));
  }
  for (const key of ["date", "day"]) {
    if (isDay(values[key])) {
      used.add(key);
      parts.push(formatDay(values[key], lang, "medium"));
    }
  }
  if (typeof values.q === "string") {
    used.add("q");
    parts.push(t("exports.param.search", { text: values.q }));
  }
  for (const [key, label] of Object.entries(SWITCHES)) {
    if (values[key] === true || values[key] === "true") {
      used.add(key);
      parts.push(t(label));
    }
  }
  for (const [key, label] of Object.entries(LISTS)) {
    if (key in values && !used.has(key)) {
      used.add(key);
      const n = Array.isArray(values[key]) ? (values[key] as unknown[]).length : 1;
      parts.push(t(label, { n }, n));
    }
  }
  if (Object.keys(values).some((key) => !used.has(key))) parts.push(t("exports.param.filtered"));
  return parts.join(" · ");
}
