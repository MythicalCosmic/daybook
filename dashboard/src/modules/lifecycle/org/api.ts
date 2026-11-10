/**
 * `GET lifecycle/org/` as a vue-query hook. The key starts with `[companyId, "lifecycle"]`, so a job
 * change proposed from the chart (the lifecycle mutations refresh that prefix) and the lifecycle
 * pulse keys redraw it.
 */
import { useQuery } from "@tanstack/vue-query";
import { computed } from "vue";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import { useCompanyId } from "@/stores/company";

import { MODULE } from "../api";
import type { OrgChart } from "./types";

export const orgApi = {
  chart: (cid: number, signal?: AbortSignal) => http.get<OrgChart>(ownerPath(cid, "lifecycle/org/"), undefined, { signal }),
};

export const orgKeys = {
  chart: (cid: number) => qk(cid, MODULE, "org"),
};

export function useOrgChart() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => orgKeys.chart(cid.value)),
    queryFn: ({ signal }) => orgApi.chart(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 20_000,
  });
}
