/**
 * Live data without websockets (plan §6.5): `GET pulse/` every 15 s while the tab is visible and on
 * focus. Counters feed the sidebar badges; when a version key changes, the queries of every module
 * that lists that key in `invalidates` are refetched. The shell runs the one poller; everything
 * else reads `pulse` and `connection`.
 */
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, shallowRef, watch, type ComputedRef, type Ref } from "vue";

import { shellApi } from "@/api/shell";
import { keys, moduleKey } from "@/api/keys";
import type { Pulse } from "@/api/types";
import { modules as registry, type DashboardModule } from "@/core/modules";

export const PULSE_INTERVAL = 15_000;
/** Pulse counter for the inbox bell (unread notifications) and the "Needs you" count. */
export const PULSE_INBOX_UNREAD = "inbox.unread";
export const PULSE_INBOX_CRITICAL = "inbox.critical";
export const PULSE_QUEUE = "queue.total";

const EMPTY: Pulse = { counters: {}, versions: {} };

/** The latest pulse of the current company. */
export const pulse = shallowRef<Pulse>(EMPTY);

export type ConnectionState = "online" | "reconnecting" | "offline";
export const connection = shallowRef<ConnectionState>("online");

export function pulseCount(source: Pulse, key: string): number {
  const value = source.counters[key];
  return typeof value === "number" && value > 0 ? value : 0;
}

/** A badge function for `NavItem.badge` / `DashboardModule.badge`: `badge: counter("tasks.review")`. */
export const counter =
  (...keysToSum: string[]) =>
  (source: Pulse): number =>
    keysToSum.reduce((sum, key) => sum + pulseCount(source, key), 0);

export function usePulseCount(key: string): ComputedRef<number> {
  return computed(() => pulseCount(pulse.value, key));
}

/** Version keys whose value differs between two pulses (new keys count as changed). */
export function changedVersions(previous: Pulse["versions"] | null, next: Pulse["versions"]): string[] {
  if (!previous) return [];
  return Object.keys(next).filter((key) => previous[key] !== next[key]);
}

/** Ids of modules that asked to be refreshed when any of `changed` moves. */
export function modulesToRefresh(changed: readonly string[], list: readonly DashboardModule[] = registry): string[] {
  if (changed.length === 0) return [];
  return list.filter((m) => m.invalidates?.some((key) => changed.includes(key))).map((m) => m.id);
}

/** True while the browser tab is visible (vue-query pauses intervals in the background). */
function onlineNow(): boolean {
  return typeof navigator === "undefined" || navigator.onLine !== false;
}

/**
 * The poller. Call once, from the shell, with the current company id. Returns the query so the
 * ConnectionPill can offer "Retry now".
 */
export function usePulsePolling(companyId: Ref<number | null>, onChange?: (changed: string[], next: Pulse) => void) {
  const client = useQueryClient();
  const enabled = computed(() => companyId.value !== null);
  const lastVersions = new Map<number, Pulse["versions"]>();

  const query = useQuery({
    queryKey: computed(() => keys.pulse(companyId.value ?? 0)),
    queryFn: ({ signal }) => shellApi.pulse(companyId.value!, signal),
    enabled,
    refetchInterval: PULSE_INTERVAL,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: "always",
    staleTime: 5_000,
    retry: 1,
  });

  watch(query.data, (next) => {
    const id = companyId.value;
    if (!next || id === null) return;
    pulse.value = next;
    const changed = changedVersions(lastVersions.get(id) ?? null, next.versions);
    lastVersions.set(id, next.versions);
    for (const moduleId of modulesToRefresh(changed)) void client.invalidateQueries({ queryKey: moduleKey(id, moduleId) });
    if (changed.length) onChange?.(changed, next);
  });

  watch(companyId, () => {
    pulse.value = EMPTY;
  });

  watch(
    () => [query.failureCount.value, query.isError.value, query.dataUpdatedAt.value] as const,
    ([failures, isError]) => {
      if (!onlineNow()) connection.value = "offline";
      else connection.value = failures >= 2 || (isError && failures > 0) ? "reconnecting" : "online";
    },
  );

  if (typeof window !== "undefined") {
    window.addEventListener("offline", () => (connection.value = "offline"));
    window.addEventListener("online", () => {
      connection.value = "online";
      void query.refetch();
    });
  }

  return query;
}
