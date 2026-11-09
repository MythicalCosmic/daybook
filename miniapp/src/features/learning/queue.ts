/**
 * The reports that must not be lost on a pharmacy's patchy signal: a lesson's progress, a quiz's
 * saved answers and a page's reading time (docs/PLAN-LEARNING.md §4.1, §4.2, §4.7).
 *
 * Each report has a key (`progress:<lesson>:<session>`, `answer:<attempt>:<question>`,
 * `view:<page>:<session>`). One request per key is in flight at a time; what comes meanwhile
 * waits and is merged into one (progress ranges add up, the newest answer wins, reading seconds
 * add up). A report that didn't get through (no signal, a server hiccup) is kept, merged into
 * the next one, and sent again on a backoff, when the phone is back online, and on the next start
 * of the app (they are kept in localStorage). A refusal (400 after a quiz's deadline, 404) is
 * dropped and handed to the caller. Every request goes with `keepalive`, so the last report still
 * leaves when the app closes or goes to the background.
 */
import { useSyncExternalStore } from "react";

import { api, ApiError } from "../../api/client";
import { initData } from "../../telegram";
import type { Answer, PageViewReport, ProgressReport, Range } from "./types";
import { capRanges, normaliseRanges } from "./tracker";

export type QueueJob =
  | { kind: "progress"; key: string; path: string; method: "POST"; body: ProgressReport }
  | { kind: "answer"; key: string; path: string; method: "PUT"; body: { question: number; answer: Answer | null } }
  | { kind: "view"; key: string; path: string; method: "POST"; body: PageViewReport };

type Waiter = { resolve: (value: unknown) => void; reject: (error: unknown) => void };
type Entry = { job: QueueJob; at: number; waiters: Waiter[] };
type Slot = { inflight: Entry | null; waiting: Entry | null; failing: boolean };

const STORAGE_KEY = "daybook.learning.queue.v1";
/** Reports older than a day are let go: a quiz is long over, a lesson's session long closed. */
const MAX_AGE_MS = 24 * 60 * 60 * 1000;
const BACKOFF_MS = [2_000, 5_000, 15_000, 30_000, 60_000];

const slots = new Map<string, Slot>();
const listeners = new Set<() => void>();
let retryTimer: ReturnType<typeof setTimeout> | undefined;
let retries = 0;
let version = 0;
let restored = false;

/** Two reports of one key as one: the older's content first, the newer's state on top. */
export function mergeJobs(older: QueueJob, newer: QueueJob): QueueJob {
  if (older.kind === "progress" && newer.kind === "progress") {
    const ranges: Range[] = capRanges(normaliseRanges([...older.body.ranges, ...newer.body.ranges], newer.body.duration || older.body.duration));
    return { ...newer, body: { ...newer.body, ranges } };
  }
  if (older.kind === "view" && newer.kind === "view") {
    return { ...newer, body: { ...newer.body, seconds: older.body.seconds + newer.body.seconds, scrolled: Math.max(older.body.scrolled, newer.body.scrolled) } };
  }
  return newer;
}

function mergeEntries(older: Entry, newer: Entry): Entry {
  return { job: mergeJobs(older.job, newer.job), at: older.at, waiters: [...older.waiters, ...newer.waiters] };
}

/** The server said no for good: sending it again would get the same answer. */
function refused(error: unknown): boolean {
  return error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408 && error.status !== 429;
}

function changed(): void {
  version += 1;
  persist();
  listeners.forEach((listener) => listener());
}

/**
 * Where the reports are kept: per Telegram account (a phone may hold two, sharing the webview's
 * storage), so one person's reports never go out signed in as the other.
 */
export function storageKey(): string {
  try {
    const user = JSON.parse(new URLSearchParams(initData()).get("user") ?? "null") as { id?: number } | null;
    return user?.id ? `${STORAGE_KEY}:${user.id}` : STORAGE_KEY;
  } catch {
    return STORAGE_KEY;
  }
}

function persist(): void {
  try {
    const kept = [...slots.values()].flatMap((slot) => [slot.inflight, slot.waiting]).filter((entry): entry is Entry => entry !== null);
    if (kept.length) localStorage.setItem(storageKey(), JSON.stringify(kept.map(({ job, at }) => ({ job, at }))));
    else localStorage.removeItem(storageKey());
  } catch {
    // Private mode or full storage: the reports still go while the app is open.
  }
}

function slotOf(key: string): Slot {
  let slot = slots.get(key);
  if (!slot) {
    slot = { inflight: null, waiting: null, failing: false };
    slots.set(key, slot);
  }
  return slot;
}

function settle(key: string, slot: Slot): void {
  if (!slot.inflight && !slot.waiting) slots.delete(key);
}

function pump(key: string): void {
  const slot = slots.get(key);
  if (!slot || slot.inflight || !slot.waiting) return;
  const entry = slot.waiting;
  slot.waiting = null;
  slot.inflight = entry;
  const { path, method, body } = entry.job;
  api<unknown>(path, { method, json: body, keepalive: true }).then(
    (value) => {
      slot.inflight = null;
      slot.failing = false;
      retries = 0;
      entry.waiters.forEach((waiter) => waiter.resolve(value));
      settle(key, slot);
      changed();
      pump(key);
    },
    (error: unknown) => {
      slot.inflight = null;
      if (refused(error)) {
        entry.waiters.forEach((waiter) => waiter.reject(error));
        slot.failing = false;
        settle(key, slot);
        changed();
        pump(key);
        return;
      }
      // Kept, with whatever came meanwhile on top, for the next try.
      slot.waiting = slot.waiting ? mergeEntries(entry, slot.waiting) : entry;
      slot.failing = true;
      changed();
      scheduleRetry();
    },
  );
  changed();
}

function scheduleRetry(): void {
  if (retryTimer !== undefined) return;
  const delay = BACKOFF_MS[Math.min(retries, BACKOFF_MS.length - 1)];
  retries += 1;
  retryTimer = setTimeout(() => {
    retryTimer = undefined;
    retryAll();
  }, delay);
}

/** Send everything that waits, now (the phone is back online, a screen asks for it). */
export function retryAll(): void {
  if (retryTimer !== undefined) {
    clearTimeout(retryTimer);
    retryTimer = undefined;
  }
  [...slots.keys()].forEach(pump);
}

/**
 * Send a report. The promise settles with the server's answer to the request that carried it
 * (merged with others of its key, perhaps much later), or rejects when the server refused it.
 */
export function send<T>(job: QueueJob): Promise<T> {
  restoreOnce();
  return new Promise<T>((resolve, reject) => {
    const slot = slotOf(job.key);
    const entry: Entry = { job, at: Date.now(), waiters: [{ resolve: resolve as (value: unknown) => void, reject }] };
    slot.waiting = slot.waiting ? mergeEntries(slot.waiting, entry) : entry;
    changed();
    pump(job.key);
  });
}

function busy(prefix: string): boolean {
  return [...slots.entries()].some(([key, slot]) => key.startsWith(prefix) && (slot.inflight || slot.waiting));
}

/**
 * Wait until every report whose key starts with `prefix` got through (true), or `timeoutMs`
 * passed with some still waiting (false): a quiz finishes only once its answers are saved.
 */
export function drain(prefix: string, timeoutMs = 8_000): Promise<boolean> {
  if (!busy(prefix)) return Promise.resolve(true);
  retryAll();
  return new Promise((resolve) => {
    const done = (result: boolean) => {
      listeners.delete(check);
      clearTimeout(timer);
      resolve(result);
    };
    const check = () => {
      if (!busy(prefix)) done(true);
    };
    const timer = setTimeout(() => done(!busy(prefix)), timeoutMs);
    listeners.add(check);
  });
}

export type QueueState = { pending: number; failing: boolean };

/** How many reports under `prefix` wait, and whether the last try of one failed. */
export function queueState(prefix: string): QueueState {
  let pending = 0;
  let failing = false;
  for (const [key, slot] of slots) {
    if (!key.startsWith(prefix)) continue;
    if (slot.inflight || slot.waiting) pending += 1;
    failing ||= slot.failing;
  }
  return { pending, failing };
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The queue's state under `prefix`, for "Saving…" and "No connection" lines. */
export function useQueueState(prefix: string): QueueState {
  const at = useSyncExternalStore(subscribe, () => version);
  void at;
  return queueState(prefix);
}

/** The reports a closed app left behind, once per start: from Home's cards or the first report. */
export function restoreOnce(): void {
  if (restored) return;
  restored = true;
  restore();
}

/** Reports a closed app left behind: they go out again (merged per key). */
export function restore(): void {
  let saved: { job: QueueJob; at: number }[] = [];
  try {
    saved = JSON.parse(localStorage.getItem(storageKey()) ?? "[]") as { job: QueueJob; at: number }[];
  } catch {
    return;
  }
  const now = Date.now();
  for (const { job, at } of Array.isArray(saved) ? saved : []) {
    if (!job?.key || !job.path || now - at > MAX_AGE_MS) continue;
    const slot = slotOf(job.key);
    const entry: Entry = { job, at, waiters: [] };
    slot.waiting = slot.waiting ? mergeEntries(slot.waiting, entry) : entry;
  }
  if (slots.size) {
    changed();
    retryAll();
  }
}

/** Only for tests: forget everything. */
export function resetQueue(): void {
  slots.clear();
  restored = false;
  if (retryTimer !== undefined) clearTimeout(retryTimer);
  retryTimer = undefined;
  retries = 0;
  changed();
}

if (typeof window !== "undefined") {
  window.addEventListener("online", retryAll);
}
