/**
 * The Tasks page's filters and built-in views (plan §6.2: "Saved views as tabs (All open, Late
 * now, Waiting for check, Today, Personal for owners, custom). Filter chips (kind, status,
 * assignee, position, branch, priority, created by, due range, overdue, proof)"). Filter keys are
 * the API's own parameter names, so the URL, the request and a saved view are the same object.
 */
import { Ban, CalendarClock, CircleDot, Eye, Flag, Hourglass, Image, Layers, Repeat, ShieldCheck, Store, TriangleAlert, UserRound, UserRoundPen, Users } from "@lucide/vue";

import type { FilterDef } from "@/components/filters";
import type { SavedViewTab } from "@/lib/useSavedViews";

import type { TaskOptions } from "./types";
import { KINDS, PRIORITIES, STATUSES } from "./types";

type T = (key: string, params?: Record<string, unknown>) => string;

export function filterDefs(t: T, options: TaskOptions | undefined, branches: Array<{ id: number; name: string; code: string }>, isOwner: boolean): FilterDef[] {
  const people = (options?.people ?? []).map((p) => ({ value: String(p.id), label: p.name, description: p.position ?? undefined, avatar: { name: p.name, src: p.photo_url } }));
  return [
    { key: "status", label: t("tasks.col.status"), type: "multi", icon: CircleDot, options: STATUSES.map((s) => ({ value: s, label: t(`tasks.status.${s}`) })) },
    { key: "assignee", label: t("tasks.col.assignee"), type: "multi", icon: UserRound, options: people },
    { key: "branch", label: t("tasks.col.branch"), type: "multi", icon: Store, options: branches.map((b) => ({ value: String(b.id), label: b.name, description: b.code })) },
    { key: "priority", label: t("tasks.col.priority"), type: "multi", icon: Flag, options: PRIORITIES.map((p) => ({ value: p, label: t(`tasks.priority.${p}`) })) },
    { key: "kind", label: t("tasks.filter.kind"), type: "multi", icon: Layers, options: KINDS.filter((k) => isOwner || k !== "personal").map((k) => ({ value: k, label: t(`tasks.kind.${k}`) })) },
    { key: "position", label: t("tasks.filter.position"), type: "multi", icon: Users, options: (options?.positions ?? []).map((p) => ({ value: String(p.id), label: p.name })) },
    { key: "routine", label: t("tasks.col.routine"), type: "multi", icon: Repeat, options: (options?.routines ?? []).map((r) => ({ value: String(r.id), label: r.title })) },
    { key: "created_by", label: t("tasks.col.givenBy"), type: "multi", icon: UserRoundPen, options: people },
    { key: "due", label: t("tasks.col.due"), type: "date-range", icon: CalendarClock, params: ["due_from", "due_to"] },
    { key: "overdue", label: t("tasks.filter.overdue"), type: "boolean", icon: TriangleAlert, trueLabel: t("tasks.filter.lateOnly"), falseLabel: t("tasks.filter.notLate") },
    { key: "has_proof", label: t("tasks.col.proof"), type: "boolean", icon: Image, trueLabel: t("tasks.filter.withProof"), falseLabel: t("tasks.filter.withoutProof") },
    { key: "needs_confirmation", label: t("tasks.filter.confirmation"), type: "boolean", icon: ShieldCheck },
    // "Can't do it", "Need more time" and "Seen" (contracts 7, 8, 10).
    { key: "blocked", label: t("tasks.filter.blocked"), type: "boolean", icon: Ban, trueLabel: t("tasks.filter.blockedYes"), falseLabel: t("tasks.filter.blockedNo") },
    { key: "extension", label: t("tasks.filter.extension"), type: "boolean", icon: Hourglass, trueLabel: t("tasks.filter.extensionYes"), falseLabel: t("tasks.filter.extensionNo") },
    { key: "seen", label: t("tasks.field.seen"), type: "boolean", icon: Eye, trueLabel: t("tasks.filter.seenYes"), falseLabel: t("tasks.filter.seenNo") },
  ];
}

/** "Can't do it", waiting for an answer. */
export const BLOCKED_PARAMS: Record<string, string | string[]> = { blocked: "true" };
/** Assigned work still to do that its person hasn't opened. */
export const UNSEEN_PARAMS: Record<string, string | string[]> = { seen: "false", kind: ["assigned"], status: ["todo", "returned"] };
/** Asked for more time, not decided yet. */
export const EXTENSION_PARAMS: Record<string, string | string[]> = { extension: "true" };

export interface BuiltinView {
  id: string;
  params: Record<string, string | string[]>;
  ordering?: string;
  ownerOnly?: boolean;
}

/** Built-in views: their filters (as URL/API params) and default ordering. */
export function builtinViews(today: string): BuiltinView[] {
  return [
    { id: "open", params: { status: ["todo", "in_progress", "review", "returned"] }, ordering: "due_at" },
    { id: "late", params: { overdue: "true" }, ordering: "due_at" },
    { id: "review", params: { status: ["review"] }, ordering: "completed_at" },
    // "Can't do it", waiting for an answer (contract 7).
    { id: "blocked", params: BLOCKED_PARAMS, ordering: "due_at" },
    { id: "today", params: { due_from: today, due_to: today }, ordering: "due_at" },
    { id: "personal", params: { kind: ["personal"] }, ordering: "due_at", ownerOnly: true },
    { id: "all", params: {}, ordering: "-due_at" },
    // Given work its person hasn't opened (contract 10).
    { id: "unseen", params: UNSEEN_PARAMS, ordering: "due_at" },
  ];
}

export function builtinTabs(t: T, views: BuiltinView[], isOwner: boolean): SavedViewTab[] {
  return views.filter((view) => isOwner || !view.ownerOnly).map((view) => ({ id: view.id, name: t(`tasks.views.${view.id}`), builtin: true }));
}

/**
 * Whether the filters ask for routine work themselves: a routine picked, or the Routine kind. The
 * Tasks page lists one-off work otherwise (`routines=without`), unless "Include routines" is on.
 */
export function asksForRoutines(params: Record<string, string | string[] | undefined>): boolean {
  const list = (value: string | string[] | undefined) => (value === undefined ? [] : Array.isArray(value) ? value : [value]);
  // "Can't do it" and "more time" need an answer whatever the work: a routine's broken fridge too.
  return list(params.routine).length > 0 || list(params.kind).includes("daily") || params.blocked === "true" || params.extension === "true";
}

/** The URL/API params a saved view stores, from whatever shape it was saved in. */
export function viewParams(state: Record<string, unknown>): Record<string, string | string[]> {
  const source = (state.params as Record<string, unknown> | undefined) ?? state;
  const out: Record<string, string | string[]> = {};
  for (const [key, value] of Object.entries(source)) {
    if (key === "view" || key === "ordering") continue;
    if (Array.isArray(value)) out[key] = value.map(String);
    else if (value !== null && value !== undefined && value !== "") out[key] = String(value);
  }
  return out;
}
