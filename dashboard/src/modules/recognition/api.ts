/**
 * The recognition owner endpoints as typed functions, and the vue-query helpers the pages use.
 * Keys start with `[companyId, "recognition"]`, so the `recognition` pulse key (`invalidates` in
 * index.ts) refreshes every query of the module.
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, type Query } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import { useCompanyId } from "@/stores/company";

import type { CatalogueEntry, Kudos, OwnerBoard, Profile, RecognitionSettings, SendKudosInput, SettingsInput } from "./types";

export const MODULE = "recognition";

const path = (cid: number, rest: string) => ownerPath(cid, `recognition/${rest}`);

export const recognitionApi = {
  leaderboard: (cid: number, params: Query) => http.get<OwnerBoard>(path(cid, "leaderboard/"), params),
  person: (cid: number, id: number) => http.get<Profile>(path(cid, `people/${id}/`)),
  adjust: (cid: number, id: number, input: { points: number; note: string }) => http.post<Profile>(path(cid, `people/${id}/adjust/`), input),
  kudos: (cid: number, params: Query = {}) => http.get<Kudos[]>(path(cid, "kudos/"), params),
  sendKudos: (cid: number, input: SendKudosInput) => http.post<Kudos>(path(cid, "kudos/"), input),
  hideKudos: (cid: number, id: number) => http.post<void>(path(cid, `kudos/${id}/hide/`), {}),
  badges: (cid: number, params: Query = {}) => http.get<CatalogueEntry[]>(path(cid, "badges/"), params),
  settings: (cid: number) => http.get<RecognitionSettings>(path(cid, "settings/")),
  updateSettings: (cid: number, input: SettingsInput) => http.patch<RecognitionSettings>(path(cid, "settings/"), input),
};

export const recognitionKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  of: (cid: number, resource: string, params: Record<string, unknown> = {}) => qk(cid, MODULE, resource, params),
};

function useResource<T>(
  resource: string,
  params: MaybeRefOrGetter<Record<string, unknown>>,
  fetcher: (cid: number, params: Record<string, unknown>) => Promise<T>,
  options: { enabled?: MaybeRefOrGetter<boolean>; keepPrevious?: boolean; staleTime?: number } = {},
) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => recognitionKeys.of(cid.value, resource, toValue(params))),
    queryFn: () => fetcher(cid.value, toValue(params)),
    enabled: computed(() => cid.value > 0 && (options.enabled === undefined || toValue(options.enabled))),
    placeholderData: options.keepPrevious ? keepPreviousData : undefined,
    staleTime: options.staleTime ?? 20_000,
  });
}

export const useLeaderboard = (params: MaybeRefOrGetter<Query>) =>
  useResource("leaderboard", () => ({ ...toValue(params) }), (cid, p) => recognitionApi.leaderboard(cid, p as Query), { keepPrevious: true });
export const useProfile = (id: MaybeRefOrGetter<number | null>) =>
  useResource("person", () => ({ id: toValue(id) }), (cid, p) => recognitionApi.person(cid, Number(p.id)), { enabled: () => !!toValue(id) });
export const useKudosFeed = (params: MaybeRefOrGetter<Query>) =>
  useResource("kudos", () => ({ ...toValue(params) }), (cid, p) => recognitionApi.kudos(cid, p as Query), { keepPrevious: true });
export const useBadges = (params: MaybeRefOrGetter<Query>) =>
  useResource("badges", () => ({ ...toValue(params) }), (cid, p) => recognitionApi.badges(cid, p as Query), { keepPrevious: true });
export const useRecognitionSettings = () => useResource("settings", {}, (cid) => recognitionApi.settings(cid), { staleTime: 60_000 });

/** Refetch every recognition query and the sidebar pulse (after a write). */
export function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: recognitionKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "shell", "pulse"] });
  };
}
