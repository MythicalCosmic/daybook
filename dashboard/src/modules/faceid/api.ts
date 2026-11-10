/**
 * Face ID endpoints (`faceid/…`) as typed functions and the vue-query helpers the pages use. Keys
 * start with `[companyId, "faceid"]`, so the pulse keys in `index.ts` (`faceid.*`) refresh
 * everything here and switching company never shows another company's scans.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, request } from "@/api/http";
import { keys as shellKeys, moduleKey, qk } from "@/api/keys";
import { downloadFile } from "@/lib/csv";
import { useCompanyId } from "@/stores/company";

import { CATCHUP_FILE } from "./lib";
import type { Device, DeviceInput, FaceIdSettings, KnownPerson, Link, Page, Scan, ScanParams, Setup, Status } from "./types";

export const MODULE = "faceid";

const path = (companyId: number, rest: string) => ownerPath(companyId, `faceid/${rest}`);

// ─── Endpoints ──────────────────────────────────────────────────────────────

export const listDevices = (companyId: number, signal?: AbortSignal) => http.get<Device[]>(path(companyId, "devices/"), undefined, { signal });
export const createDevice = (companyId: number, body: DeviceInput) => http.post<Device>(path(companyId, "devices/"), body);
export const updateDevice = (companyId: number, id: number, body: Partial<DeviceInput> & { enabled?: boolean }) => http.patch<Device>(path(companyId, `devices/${id}/`), body);
export const getSetup = (companyId: number, id: number, signal?: AbortSignal) => http.get<Setup>(path(companyId, `devices/${id}/setup/`), undefined, { signal });
export const regenerate = (companyId: number, id: number) => http.post<Setup>(path(companyId, `devices/${id}/regenerate/`));
export const simulate = (companyId: number, id: number) => http.post<Scan>(path(companyId, `devices/${id}/simulate/`));
export const getStatus = (companyId: number, signal?: AbortSignal) => http.get<Status>(path(companyId, "status/"), undefined, { signal });
export const listScans = (companyId: number, params: ScanParams, signal?: AbortSignal) =>
  http.get<Page<Scan>>(path(companyId, "events/"), { ...params, action: params.action?.length ? params.action : undefined, branch: params.branch?.length ? params.branch : undefined }, { signal });
export const listPeople = (companyId: number, linked?: "0" | "1", signal?: AbortSignal) => http.get<KnownPerson[]>(path(companyId, "people/"), { linked }, { signal });
export const ignoreNumber = (companyId: number, employeeNo: string) => http.post<Link>(path(companyId, "people/ignore/"), { employee_no: employeeNo });
export const listLinks = (companyId: number, params: { member?: number; ignored?: "1" }, signal?: AbortSignal) => http.get<Link[]>(path(companyId, "links/"), params, { signal });
export const createLink = (companyId: number, employeeNo: string, memberId: number) => http.post<Link>(path(companyId, "links/"), { employee_no: employeeNo, member_id: memberId });
export const deleteLink = (companyId: number, id: number) => http.delete(path(companyId, `links/${id}/`));
export const getSettings = (companyId: number, signal?: AbortSignal) => http.get<FaceIdSettings>(path(companyId, "settings/"), undefined, { signal });
export const saveSettings = (companyId: number, body: Partial<FaceIdSettings>) => http.patch<FaceIdSettings>(path(companyId, "settings/"), body);

/**
 * Saves `catchup.py`, the helper that sends a terminal's newest scans while it still uploads its
 * old history, with the terminal's address on the server filled in (`attendance.manage`). A
 * refusal is toasted by the HTTP client.
 */
export async function downloadCatchup(companyId: number, id: number): Promise<void> {
  const response = await request<Response>(path(companyId, `devices/${id}/catchup/`), { headers: { Accept: "*/*" }, raw: true, toast: true });
  downloadFile(CATCHUP_FILE, await response.blob());
}

// ─── Keys ───────────────────────────────────────────────────────────────────

export const faceKeys = {
  all: (companyId: number) => moduleKey(companyId, MODULE),
  devices: (companyId: number) => qk(companyId, MODULE, "devices"),
  setup: (companyId: number, id: number) => qk(companyId, MODULE, "setup", { id }),
  status: (companyId: number) => qk(companyId, MODULE, "status"),
  scans: (companyId: number, params: object) => qk(companyId, MODULE, "scans", { ...params }),
  people: (companyId: number, linked: string) => qk(companyId, MODULE, "people", { linked }),
  links: (companyId: number, params: object) => qk(companyId, MODULE, "links", { ...params }),
  settings: (companyId: number) => qk(companyId, MODULE, "settings"),
};

// ─── Queries ────────────────────────────────────────────────────────────────

export function useDevices(enabled: MaybeRefOrGetter<boolean> = true) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => faceKeys.devices(companyId.value)),
    queryFn: ({ signal }) => listDevices(companyId.value, signal),
    enabled: computed(() => companyId.value > 0 && toValue(enabled)),
    // A terminal's status moves with time too ("quiet" after a silent day).
    refetchInterval: 60_000,
  });
}

/** The setup values; polled every few seconds while the wizard waits for the first scan. */
export function useSetup(id: MaybeRefOrGetter<number | null>, poll: MaybeRefOrGetter<boolean> = false) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => faceKeys.setup(companyId.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => getSetup(companyId.value, toValue(id)!, signal),
    enabled: computed(() => companyId.value > 0 && !!toValue(id)),
    refetchInterval: computed(() => (toValue(poll) ? 3_000 : false)),
  });
}

export function useStatus() {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => faceKeys.status(companyId.value)),
    queryFn: ({ signal }) => getStatus(companyId.value, signal),
    enabled: computed(() => companyId.value > 0),
    refetchInterval: 60_000,
  });
}

export function useScans(params: MaybeRefOrGetter<ScanParams>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => faceKeys.scans(companyId.value, toValue(params))),
    queryFn: ({ signal }) => listScans(companyId.value, toValue(params), signal),
    enabled: computed(() => companyId.value > 0),
    placeholderData: keepPreviousData,
    // The feed is live: the pulse refreshes it on every scan; this catches a missed one.
    refetchInterval: 30_000,
  });
}

export function usePeople(linked: MaybeRefOrGetter<"0" | "1" | undefined> = undefined) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => faceKeys.people(companyId.value, toValue(linked) ?? "")),
    queryFn: ({ signal }) => listPeople(companyId.value, toValue(linked), signal),
    enabled: computed(() => companyId.value > 0),
    placeholderData: keepPreviousData,
  });
}

export function useLinks(params: MaybeRefOrGetter<{ member?: number; ignored?: "1" }>, enabled: MaybeRefOrGetter<boolean> = true) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => faceKeys.links(companyId.value, toValue(params))),
    queryFn: ({ signal }) => listLinks(companyId.value, toValue(params), signal),
    enabled: computed(() => companyId.value > 0 && toValue(enabled)),
  });
}

export function useSettings() {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => faceKeys.settings(companyId.value)),
    queryFn: ({ signal }) => getSettings(companyId.value, signal),
    enabled: computed(() => companyId.value > 0),
  });
}

// ─── Mutations ──────────────────────────────────────────────────────────────

/** Everything Face ID shows, plus the shell's pulse (the "not in Daybook" badge). */
export function useRefresh() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: faceKeys.all(companyId.value) });
    void client.invalidateQueries({ queryKey: shellKeys.pulse(companyId.value) });
  };
}

export function useLink() {
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ employeeNo, memberId }: { employeeNo: string; memberId: number }) => createLink(companyId.value, employeeNo, memberId),
    onSettled: refresh,
  });
}

export function useUnlink() {
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({ mutationFn: (link: { id: number }) => deleteLink(companyId.value, link.id), onSettled: refresh });
}

export function useIgnore() {
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({ mutationFn: (employeeNo: string) => ignoreNumber(companyId.value, employeeNo), onSettled: refresh });
}
