/**
 * The fixed assets endpoints as typed functions, and the vue-query helpers the pages use. Keys
 * start with `[companyId, "assets"]`, so the `assets` pulse key (`invalidates` in index.ts)
 * refreshes every query of the module, and switching company never shows another's assets.
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, type Query } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import { useCompanyId } from "@/stores/company";

import type {
  ActionKind,
  AssetCount,
  AssetDetail,
  AssetInput,
  AssetRow,
  AssetSettings,
  Category,
  Custody,
  DepreciationReport,
  Movement,
  Permit,
  PermitInput,
  Planning,
  Purchase,
  Summary,
} from "./types";

export const MODULE = "assets";

const path = (cid: number, rest: string) => ownerPath(cid, `assets/${rest}`);

export const assetsApi = {
  settings: (cid: number) => http.get<AssetSettings>(path(cid, "settings/")),
  updateSettings: (cid: number, input: Partial<AssetSettings>) => http.patch<AssetSettings>(path(cid, "settings/"), input),
  categories: (cid: number) => http.get<Category[]>(path(cid, "categories/")),
  createCategory: (cid: number, input: Partial<Category>) => http.post<Category>(path(cid, "categories/"), input),
  updateCategory: (cid: number, id: number, input: Partial<Category>) => http.patch<Category>(path(cid, `categories/${id}/`), input),
  deleteCategory: (cid: number, id: number) => http.delete(path(cid, `categories/${id}/`)),

  summary: (cid: number, params: Query = {}) => http.get<Summary>(path(cid, "summary/"), params),
  items: (cid: number, params: Query = {}, signal?: AbortSignal) => http.get<AssetRow[]>(path(cid, "items/"), params, { signal }),
  item: (cid: number, id: number) => http.get<AssetDetail>(path(cid, `items/${id}/`)),
  create: (cid: number, input: AssetInput) => http.post<AssetDetail>(path(cid, "items/"), input),
  update: (cid: number, id: number, input: AssetInput) => http.patch<AssetDetail>(path(cid, `items/${id}/`), input),
  remove: (cid: number, id: number) => http.delete(path(cid, `items/${id}/`)),
  /** One step on an asset ("issue", "dispose"…); the answer is its page. */
  act: (cid: number, id: number, kind: ActionKind, body: Record<string, unknown>) => http.post<AssetDetail>(path(cid, `items/${id}/${kind}/`), body),
  upload: (cid: number, id: number, file: File, kind: "photo" | "document", label = "") => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    form.append("label", label);
    return http.form<AssetDetail>(path(cid, `items/${id}/files/`), form);
  },
  removeFile: (cid: number, fileId: number) => http.delete(path(cid, `files/${fileId}/`)),

  depreciation: (cid: number, params: Query) => http.get<DepreciationReport>(path(cid, "depreciation/"), params),
  movement: (cid: number, params: Query) => http.get<Movement>(path(cid, "movement/"), params),
  planning: (cid: number, params: Query = {}) => http.get<Planning>(path(cid, "planning/"), params),
  custody: (cid: number, params: Query = {}) => http.get<Custody[]>(path(cid, "custody/"), params),
  purchases: (cid: number) => http.get<Purchase[]>(path(cid, "purchases/")),

  permits: (cid: number) => http.get<Permit[]>(path(cid, "permits/")),
  createPermit: (cid: number, input: PermitInput) => http.post<Permit>(path(cid, "permits/"), input),
  updatePermit: (cid: number, id: number, input: PermitInput) => http.patch<Permit>(path(cid, `permits/${id}/`), input),
  deletePermit: (cid: number, id: number) => http.delete(path(cid, `permits/${id}/`)),
  uploadPermit: (cid: number, id: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return http.form<Permit>(path(cid, `permits/${id}/file/`), form);
  },

  counts: (cid: number) => http.get<AssetCount[]>(path(cid, "counts/")),
  count: (cid: number, id: number) => http.get<AssetCount>(path(cid, `counts/${id}/`)),
  startCount: (cid: number, input: { branch: number | null; note?: string }) => http.post<AssetCount>(path(cid, "counts/"), input),
  markLine: (cid: number, id: number, line: number, input: { result: string; note?: string }) => http.post<AssetCount>(path(cid, `counts/${id}/lines/${line}/`), input),
  closeCount: (cid: number, id: number) => http.post<AssetCount>(path(cid, `counts/${id}/close/`), {}),
};

export const assetKeys = {
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
    queryKey: computed(() => assetKeys.of(cid.value, resource, toValue(params))),
    queryFn: ({ signal }) => fetcher(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && (options.enabled === undefined || toValue(options.enabled))),
    placeholderData: options.keepPrevious ? keepPreviousData : undefined,
    staleTime: options.staleTime ?? 20_000,
  });
}

export const useAssetSettings = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("settings", {}, (cid) => assetsApi.settings(cid), { enabled, staleTime: 60_000 });
export const useCategories = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("categories", {}, (cid) => assetsApi.categories(cid), { enabled, staleTime: 60_000 });
export const useSummary = (params: MaybeRefOrGetter<Query>) => useResource("summary", () => ({ ...toValue(params) }), (cid, p) => assetsApi.summary(cid, p as Query), { keepPrevious: true });
export const useItems = (params: MaybeRefOrGetter<Query>) =>
  useResource("items", () => ({ ...toValue(params) }), (cid, p, signal) => assetsApi.items(cid, p as Query, signal), { keepPrevious: true });
export const useItem = (id: MaybeRefOrGetter<number>) => useResource("item", () => ({ id: toValue(id) }), (cid, p) => assetsApi.item(cid, Number(p.id)), { enabled: () => toValue(id) > 0 });
export const useDepreciation = (params: MaybeRefOrGetter<Query>) =>
  useResource("depreciation", () => ({ ...toValue(params) }), (cid, p) => assetsApi.depreciation(cid, p as Query), { keepPrevious: true });
export const useMovement = (params: MaybeRefOrGetter<Query>) => useResource("movement", () => ({ ...toValue(params) }), (cid, p) => assetsApi.movement(cid, p as Query), { keepPrevious: true });
export const usePlanning = (params: MaybeRefOrGetter<Query>) => useResource("planning", () => ({ ...toValue(params) }), (cid, p) => assetsApi.planning(cid, p as Query), { keepPrevious: true });
export const useCustody = (params: MaybeRefOrGetter<Query>) => useResource("custody", () => ({ ...toValue(params) }), (cid, p) => assetsApi.custody(cid, p as Query), { keepPrevious: true });
export const usePurchases = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("purchases", {}, (cid) => assetsApi.purchases(cid), { enabled });
export const usePermits = () => useResource("permits", {}, (cid) => assetsApi.permits(cid));
export const useCounts = () => useResource("counts", {}, (cid) => assetsApi.counts(cid));
export const useCount = (id: MaybeRefOrGetter<number | null>) => useResource("count", () => ({ id: toValue(id) }), (cid, p) => assetsApi.count(cid, Number(p.id)), { enabled: () => !!toValue(id) });

/** Refetch every assets query and the sidebar pulse (after a write). */
export function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: assetKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "shell", "pulse"] });
  };
}
