/**
 * Ko‘z endpoints (`vision/…`, docs/KOZ.md §6) as typed functions and the vue-query helpers the
 * pages use. Keys start with `[companyId, "vision"]`, so the `vision` pulse refreshes everything
 * here and switching company never shows another company's cameras.
 *
 * In fixture mode (mode.ts, dev server only) every call is answered by `./fixtures` instead of the
 * network; the branch that imports them is dropped from a build, chunk and all.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { ownerPath, request, type Query } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyId } from "@/stores/company";

import type { Agent, Alert, AlertParams, Camera, CameraPatch, Clip, ClipRequest, Frame, Live, Overview, Pairing, ReviewItem, VisionSettings } from "./types";

export const MODULE = "vision";

export interface CallOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  query?: Query;
  json?: unknown;
  signal?: AbortSignal;
  /** Show a failure as a toast (default: writes do, reads don't). */
  toast?: boolean;
}

/**
 * One Ko‘z call: the network, or the fixtures in fixture mode. The guard is written out here, not
 * imported, so a build sees `false && …` in this very module and drops the import with its chunk
 * (as main.ts does for the dev mock).
 */
export async function call<T>(companyId: number, rest: string, options: CallOptions = {}): Promise<T> {
  if (import.meta.env.DEV && import.meta.env.VITE_VISION_FIXTURES === "1") {
    const { answer } = await import("./fixtures");
    return answer<T>(companyId, rest, options);
  }
  return request<T>(ownerPath(companyId, `vision/${rest}`), {
    method: options.method ?? "GET",
    query: options.query,
    json: options.json,
    signal: options.signal,
    toast: options.toast,
  });
}

// ─── Endpoints ──────────────────────────────────────────────────────────────

export interface OverviewParams {
  branch?: number | null;
  day?: string | null;
}

export const getOverview = (companyId: number, params: OverviewParams, signal?: AbortSignal) =>
  call<Overview>(companyId, "overview/", { query: { branch: params.branch ?? undefined, day: params.day ?? undefined }, signal });
export const getLive = (companyId: number, branch: number | null, signal?: AbortSignal) => call<Live>(companyId, "live/", { query: { branch: branch ?? undefined }, signal });
/** The latest picture of a camera with its people, or null while there is no fresh one (204). */
export const getFrame = async (companyId: number, cameraId: number, signal?: AbortSignal) => (await call<Frame | undefined>(companyId, `cameras/${cameraId}/frame/`, { signal })) ?? null;
export const listCameras = (companyId: number, branch: number | null, signal?: AbortSignal) => call<Camera[]>(companyId, "cameras/", { query: { branch: branch ?? undefined }, signal });
export const updateCamera = (companyId: number, id: number, patch: CameraPatch, toast = true) => call<Camera>(companyId, `cameras/${id}/`, { method: "PATCH", json: patch, toast });
export const requestSnapshot = (companyId: number, id: number) => call<void>(companyId, `cameras/${id}/snapshot/`, { method: "POST", json: {} });
export const listAlerts = (companyId: number, params: AlertParams, signal?: AbortSignal) => call<Page<Alert>>(companyId, "alerts/", { query: { ...params }, signal });
export const getAlert = (companyId: number, id: number, signal?: AbortSignal) => call<Alert>(companyId, `alerts/${id}/`, { signal });
export const getClip = (companyId: number, id: number, signal?: AbortSignal) => call<Clip>(companyId, `clips/${id}/`, { signal });
/** A clip of an alert (its own window) or of a sale, a camera and a moment. */
export function createClip(companyId: number, body: ClipRequest): Promise<Clip> {
  if ("alert_id" in body) return call<Clip>(companyId, `alerts/${body.alert_id}/clip/`, { method: "POST", json: {}, toast: false });
  return call<Clip>(companyId, "clips/", { method: "POST", json: body, toast: false });
}
export const getSettings = (companyId: number, signal?: AbortSignal) => call<VisionSettings>(companyId, "settings/", { signal });
export const saveSettings = (companyId: number, body: Partial<VisionSettings>) => call<VisionSettings>(companyId, "settings/", { method: "PATCH", json: body });
export const listAgents = (companyId: number, signal?: AbortSignal) => call<Agent[]>(companyId, "agents/", { signal });
export const createAgent = (companyId: number, body: { name: string; branch_id: number }) => call<{ agent: Agent; pairing: Pairing }>(companyId, "agents/", { method: "POST", json: body });
export const newPairing = (companyId: number, id: number) => call<Pairing>(companyId, `agents/${id}/pairing/`, { method: "POST", json: {} });
export const deleteAgent = (companyId: number, id: number) => call<void>(companyId, `agents/${id}/`, { method: "DELETE" });
/** The sales module's tills, to map a counter camera to one (needs the sales module). */
export const listRegisters = (companyId: number, signal?: AbortSignal) =>
  request<Array<{ id: number; name: string; branch: { id: number; name: string }; is_active: boolean }>>(ownerPath(companyId, "sales/registers/"), { signal });
export const getReview = (companyId: number, params: OverviewParams, signal?: AbortSignal) =>
  call<{ items: ReviewItem[] }>(companyId, "review/", { query: { branch: params.branch ?? undefined, day: params.day ?? undefined }, signal });

// ─── Keys ───────────────────────────────────────────────────────────────────

export const visionKeys = {
  all: (companyId: number) => moduleKey(companyId, MODULE),
  overview: (companyId: number, params: object) => qk(companyId, MODULE, "overview", { ...params }),
  live: (companyId: number, branch: number | null) => qk(companyId, MODULE, "live", { branch }),
  cameras: (companyId: number, branch: number | null) => qk(companyId, MODULE, "cameras", { branch }),
  alerts: (companyId: number, params: object) => qk(companyId, MODULE, "alerts", { ...params }),
  alert: (companyId: number, id: number) => qk(companyId, MODULE, "alert", { id }),
  settings: (companyId: number) => qk(companyId, MODULE, "settings"),
  agents: (companyId: number) => qk(companyId, MODULE, "agents"),
  review: (companyId: number, params: object) => qk(companyId, MODULE, "review", { ...params }),
  registers: (companyId: number) => qk(companyId, MODULE, "registers"),
};

// ─── Queries ────────────────────────────────────────────────────────────────

export function useOverview(params: MaybeRefOrGetter<OverviewParams>, enabled: MaybeRefOrGetter<boolean> = true) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => visionKeys.overview(companyId.value, toValue(params))),
    queryFn: ({ signal }) => getOverview(companyId.value, toValue(params), signal),
    enabled: computed(() => companyId.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
    // Today keeps moving: the hours, the open alerts, the boxes' status.
    refetchInterval: 60_000,
  });
}

/** Live numbers of every camera, every 5 s while the page is visible (docs/KOZ.md §6.2). */
export function useLive(branch: MaybeRefOrGetter<number | null>, enabled: MaybeRefOrGetter<boolean> = true) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => visionKeys.live(companyId.value, toValue(branch))),
    queryFn: ({ signal }) => getLive(companyId.value, toValue(branch), signal),
    enabled: computed(() => companyId.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
  });
}

export function useCameras(branch: MaybeRefOrGetter<number | null> = null, enabled: MaybeRefOrGetter<boolean> = true) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => visionKeys.cameras(companyId.value, toValue(branch))),
    queryFn: ({ signal }) => listCameras(companyId.value, toValue(branch), signal),
    enabled: computed(() => companyId.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
  });
}

export function useAlerts(params: MaybeRefOrGetter<AlertParams>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => visionKeys.alerts(companyId.value, toValue(params))),
    queryFn: ({ signal }) => listAlerts(companyId.value, toValue(params), signal),
    enabled: computed(() => companyId.value > 0),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
}

export function useAlert(id: MaybeRefOrGetter<number | null>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => visionKeys.alert(companyId.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => getAlert(companyId.value, toValue(id)!, signal),
    enabled: computed(() => companyId.value > 0 && !!toValue(id)),
    // An open alert's timer and acknowledgement move.
    refetchInterval: 15_000,
  });
}

export function useSettings() {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => visionKeys.settings(companyId.value)),
    queryFn: ({ signal }) => getSettings(companyId.value, signal),
    enabled: computed(() => companyId.value > 0),
  });
}

/** The boxes; polled every 2 s while a pairing waits for its box. */
export function useAgents(poll: MaybeRefOrGetter<boolean> = false, enabled: MaybeRefOrGetter<boolean> = true) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => visionKeys.agents(companyId.value)),
    queryFn: ({ signal }) => listAgents(companyId.value, signal),
    enabled: computed(() => companyId.value > 0 && toValue(enabled)),
    refetchInterval: computed(() => (toValue(poll) ? 2_000 : 60_000)),
  });
}

export function useReview(params: MaybeRefOrGetter<OverviewParams>, enabled: MaybeRefOrGetter<boolean> = true) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => visionKeys.review(companyId.value, toValue(params))),
    queryFn: ({ signal }) => getReview(companyId.value, toValue(params), signal),
    enabled: computed(() => companyId.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
  });
}

export function useRegisters(enabled: MaybeRefOrGetter<boolean> = true) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => visionKeys.registers(companyId.value)),
    queryFn: ({ signal }) => listRegisters(companyId.value, signal),
    enabled: computed(() => companyId.value > 0 && toValue(enabled)),
    staleTime: 5 * 60_000,
  });
}

// ─── Mutations ──────────────────────────────────────────────────────────────

/** Everything Ko‘z shows. */
export function useRefresh() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  return () => void client.invalidateQueries({ queryKey: visionKeys.all(companyId.value) });
}

/**
 * Saves a camera's name, role, switch, register or zones. The lists show the change at once and
 * go back if the server refuses.
 */
export function useUpdateCamera() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, patch, toast }: { id: number; patch: CameraPatch; toast?: boolean }) => updateCamera(companyId.value, id, patch, toast ?? true),
    onMutate: async ({ id, patch }) => {
      const prefix = [companyId.value, MODULE, "cameras"];
      await client.cancelQueries({ queryKey: prefix });
      const before = client.getQueriesData<Camera[]>({ queryKey: prefix });
      const { register_id: _register, ...rest } = patch;
      client.setQueriesData<Camera[]>({ queryKey: prefix }, (list) => list?.map((camera) => (camera.id === id ? { ...camera, ...rest } : camera)));
      return { before };
    },
    onError: (_error, _vars, context) => {
      for (const [key, data] of context?.before ?? []) client.setQueryData(key, data);
    },
    onSettled: refresh,
  });
}
