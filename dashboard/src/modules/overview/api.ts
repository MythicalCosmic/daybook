/**
 * The Overview's own reads (plan §4.2, apps.console): branch cards (`branches/today/`) and the
 * activity stream (`stream/`). Every other card on the page is a widget another module registers
 * and fetches for itself.
 */
import { keepPreviousData, useQuery } from "@tanstack/vue-query";
import { computed } from "vue";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import type { BranchToday, StreamItem } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

export const MODULE = "overview";

export function listBranchesToday(companyId: number, signal?: AbortSignal): Promise<BranchToday[]> {
  return http.get<BranchToday[]>(ownerPath(companyId, "branches/today/"), undefined, { signal });
}

/** Newest first; `since` (an ISO instant) returns only newer items. */
export function listStream(companyId: number, params: { limit?: number; since?: string } = {}, signal?: AbortSignal): Promise<{ items: StreamItem[] }> {
  return http.get<{ items: StreamItem[] }>(ownerPath(companyId, "stream/"), { limit: params.limit, since: params.since }, { signal });
}

export const overviewKeys = {
  branches: (companyId: number) => qk(companyId, MODULE, "branches"),
  stream: (companyId: number, limit: number) => qk(companyId, MODULE, "stream", { limit }),
};

function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

/** Branch cards; refreshed every minute, since "not opened" depends on the clock as much as on data. */
export function useBranchesToday() {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => overviewKeys.branches(companyId.value)),
    queryFn: ({ signal }) => listBranchesToday(companyId.value, signal),
    enabled: computed(() => companyId.value > 0),
    refetchInterval: 60_000,
    staleTime: 20_000,
  });
}

export function useStream(limit = 8) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => overviewKeys.stream(companyId.value, limit)),
    queryFn: ({ signal }) => listStream(companyId.value, { limit }, signal),
    enabled: computed(() => companyId.value > 0),
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  });
}

/** Minutes past opening time on the company's clock ("Not opened · +12 min"), or 0. */
export function minutesLate(opensAt: string | null, now: { getHours(): number; getMinutes(): number }): number {
  if (!opensAt || !/^\d{2}:\d{2}$/.test(opensAt)) return 0;
  const [hours, minutes] = opensAt.split(":").map(Number) as [number, number];
  return Math.max(0, now.getHours() * 60 + now.getMinutes() - (hours * 60 + minutes));
}
