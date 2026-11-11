/**
 * The contracts endpoints as typed functions, and the vue-query helpers the pages use. Keys
 * start with `[companyId, "contracts"]`, so the `contracts` pulse key (`invalidates` in
 * index.ts) refreshes every query of the module, and switching company never shows another's.
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, type Query } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import { useCompanyId } from "@/stores/company";

import type { ContractDetail, ContractFileKind, ContractInput, ContractRow, ContractSettings, Options, Summary } from "./types";

export const MODULE = "contracts";

const path = (cid: number, rest = "") => ownerPath(cid, `contracts/${rest}`);

export const contractsApi = {
  list: (cid: number, params: Query = {}, signal?: AbortSignal) => http.get<ContractRow[]>(path(cid), params, { signal }),
  summary: (cid: number, params: Query = {}) => http.get<Summary>(path(cid, "summary/"), params),
  one: (cid: number, id: number) => http.get<ContractDetail>(path(cid, `${id}/`)),
  create: (cid: number, input: ContractInput) => http.post<ContractDetail>(path(cid), input),
  update: (cid: number, id: number, input: ContractInput) => http.patch<ContractDetail>(path(cid, `${id}/`), input),
  remove: (cid: number, id: number) => http.delete(path(cid, `${id}/`)),
  renew: (cid: number, id: number, endsOn: string) => http.post<ContractDetail>(path(cid, `${id}/renew/`), { ends_on: endsOn }),
  terminate: (cid: number, id: number, on: string, reason = "") => http.post<ContractDetail>(path(cid, `${id}/terminate/`), { on, reason }),
  keepRenewing: (cid: number, id: number) => http.post<ContractDetail>(path(cid, `${id}/keep-renewing/`), {}),
  stopRenewing: (cid: number, id: number) => http.post<ContractDetail>(path(cid, `${id}/stop-renewing/`), {}),
  upload: (cid: number, id: number, file: File, kind: ContractFileKind, label = "") => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    form.append("label", label);
    return http.form<ContractDetail>(path(cid, `${id}/files/`), form);
  },
  removeFile: (cid: number, fileId: number) => http.delete(path(cid, `files/${fileId}/`)),
  settings: (cid: number) => http.get<ContractSettings>(path(cid, "settings/")),
  updateSettings: (cid: number, input: Partial<ContractSettings>) => http.patch<ContractSettings>(path(cid, "settings/"), input),
  options: (cid: number) => http.get<Options>(path(cid, "options/")),
};

export const contractKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  of: (cid: number, resource: string, params: Record<string, unknown> = {}) => qk(cid, MODULE, resource, params),
};

function useResource<T>(
  resource: string,
  params: MaybeRefOrGetter<Record<string, unknown>>,
  fetcher: (cid: number, params: Record<string, unknown>, signal: AbortSignal) => Promise<T>,
  options: { enabled?: MaybeRefOrGetter<boolean>; keepPrevious?: boolean; staleTime?: number } = {},
) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => contractKeys.of(cid.value, resource, toValue(params))),
    queryFn: ({ signal }) => fetcher(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && (options.enabled === undefined || toValue(options.enabled))),
    placeholderData: options.keepPrevious ? keepPreviousData : undefined,
    staleTime: options.staleTime ?? 20_000,
  });
}

export const useContracts = (params: MaybeRefOrGetter<Query>) =>
  useResource("list", () => ({ ...toValue(params) }), (cid, p, signal) => contractsApi.list(cid, p as Query, signal), { keepPrevious: true });
export const useSummary = (params: MaybeRefOrGetter<Query>) => useResource("summary", () => ({ ...toValue(params) }), (cid, p) => contractsApi.summary(cid, p as Query), { keepPrevious: true });
export const useContract = (id: MaybeRefOrGetter<number>) =>
  // A file link lives ten minutes: the page refetches well before that.
  useResource("one", () => ({ id: toValue(id) }), (cid, p) => contractsApi.one(cid, Number(p.id)), { enabled: () => toValue(id) > 0, staleTime: 60_000 });
export const useOptions = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("options", {}, (cid) => contractsApi.options(cid), { enabled, staleTime: 60_000 });
export const useContractSettings = () => useResource("settings", {}, (cid) => contractsApi.settings(cid), { staleTime: 60_000 });

/** Refetch every contracts query and the sidebar pulse (after a write). */
export function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: contractKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "shell", "pulse"] });
  };
}
