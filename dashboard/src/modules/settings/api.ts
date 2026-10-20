/**
 * Company setup endpoints (plan §4.3–§4.4) as typed functions and vue-query helpers, keyed under
 * `[companyId, "settings"]`: the module's `invalidates` ("companies", "groups") refreshes them when
 * another dashboard changes something. A change that `me` shows (name, logo, modules, currency,
 * timezone) also reloads `me`, so the switcher and the sidebar follow at once.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed } from "vue";

import { http, ownerPath, request } from "@/api/http";
import { qk } from "@/api/keys";
import type { CompanyFeature } from "@/core/features";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

import type {
  Branch,
  BranchInput,
  CompanySettings,
  DeviceSession,
  Features,
  Invite,
  ManagerOption,
  NotificationPreference,
  Revoked,
  SettingsPatch,
} from "./types";

export const MODULE = "settings";

// ─── Endpoints ──────────────────────────────────────────────────────────────

export const getSettings = (cid: number, signal?: AbortSignal) => http.get<CompanySettings>(ownerPath(cid, "settings/"), undefined, { signal });
export const patchSettings = (cid: number, patch: SettingsPatch) => http.patch<CompanySettings>(ownerPath(cid, "settings/"), patch);

export function uploadLogo(cid: number, file: File): Promise<CompanySettings> {
  const form = new FormData();
  form.append("logo", file);
  return http.form<CompanySettings>(ownerPath(cid, "settings/logo/"), form);
}
export const removeLogo = (cid: number) => http.delete<CompanySettings>(ownerPath(cid, "settings/logo/"));

export const getFeatures = (cid: number, signal?: AbortSignal) => http.get<Features>(ownerPath(cid, "features/"), undefined, { signal });
export const setFeatures = (cid: number, features: CompanyFeature[]) => http.patch<Features>(ownerPath(cid, "features/"), { features });

export const listBranches = (cid: number, signal?: AbortSignal) => http.get<Branch[]>(ownerPath(cid, "branches/"), undefined, { signal });
export const createBranch = (cid: number, input: Partial<BranchInput>) => http.post<Branch>(ownerPath(cid, "branches/"), input);
export const updateBranch = (cid: number, id: number, input: Partial<BranchInput>) => http.patch<Branch>(ownerPath(cid, `branches/${id}/`), input);
export const deactivateBranch = (cid: number, id: number) => http.post<Branch>(ownerPath(cid, `branches/${id}/deactivate/`));
export const activateBranch = (cid: number, id: number) => http.post<Branch>(ownerPath(cid, `branches/${id}/activate/`));
export const reorderBranches = (cid: number, ids: number[]) => http.post<Branch[]>(ownerPath(cid, "branches/reorder/"), { ids });
export const listManagers = (cid: number, signal?: AbortSignal) => http.get<ManagerOption[]>(ownerPath(cid, "branches/managers/"), undefined, { signal });

export const getInvite = (cid: number, signal?: AbortSignal) => http.get<Invite>(ownerPath(cid, "invite/"), undefined, { signal });
export const regenerateInvite = (cid: number) => http.post<Invite>(ownerPath(cid, "invite/regenerate/"));

export const getPreferences = (cid: number, signal?: AbortSignal) =>
  http.get<NotificationPreference[]>(ownerPath(cid, "notification-preferences/"), undefined, { signal });
export const putPreferences = (cid: number, rows: Array<Pick<NotificationPreference, "kind" | "in_app" | "telegram">>) =>
  http.put<NotificationPreference[]>(ownerPath(cid, "notification-preferences/"), rows);

export const listSessions = (signal?: AbortSignal) => http.get<DeviceSession[]>("/owner/auth/sessions/", undefined, { signal });
export const revokeSession = (id: number) => http.post<Revoked>(`/owner/auth/sessions/${id}/revoke/`);
export const revokeAllSessions = (keepCurrent: boolean) =>
  request<Revoked>("/owner/auth/sessions/revoke-all/", { method: "POST", json: { keep_current: keepCurrent } });

// ─── Keys and queries ───────────────────────────────────────────────────────

export const settingsKeys = {
  all: (cid: number) => [cid, MODULE] as const,
  settings: (cid: number) => qk(cid, MODULE, "settings"),
  features: (cid: number) => qk(cid, MODULE, "features"),
  branches: (cid: number) => qk(cid, MODULE, "branches"),
  managers: (cid: number) => qk(cid, MODULE, "managers"),
  invite: (cid: number) => qk(cid, MODULE, "invite"),
  preferences: (cid: number) => qk(cid, MODULE, "preferences"),
  sessions: (cid: number) => qk(cid, MODULE, "sessions"),
};

export function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

function useCompanyQuery<T>(key: (cid: number) => readonly unknown[], fetcher: (cid: number, signal?: AbortSignal) => Promise<T>, enabled = computed(() => true)) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => key(cid.value)),
    queryFn: ({ signal }) => fetcher(cid.value, signal),
    enabled: computed(() => cid.value > 0 && enabled.value),
    staleTime: 30_000,
  });
}

export const useSettings = () => useCompanyQuery(settingsKeys.settings, getSettings);
export const useFeatures = () => useCompanyQuery(settingsKeys.features, getFeatures);
export const useBranches = () => useCompanyQuery(settingsKeys.branches, listBranches);
export const useManagers = (enabled = computed(() => true)) => useCompanyQuery(settingsKeys.managers, listManagers, enabled);
export const useInvite = () => useCompanyQuery(settingsKeys.invite, getInvite);
export const usePreferences = () => useCompanyQuery(settingsKeys.preferences, getPreferences);
export const useSessions = () => useCompanyQuery(settingsKeys.sessions, (_cid, signal) => listSessions(signal));

/** After a change `me` shows: the switcher, sidebar and module switches follow at once. */
export function useRefreshMe() {
  const session = useSessionStore();
  return () => session.loadMe().catch(() => undefined);
}

// ─── Mutations ──────────────────────────────────────────────────────────────

export function useSaveSettings() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refreshMe = useRefreshMe();
  return useMutation({
    mutationFn: (patch: SettingsPatch) => patchSettings(cid.value, patch),
    onSuccess: (data) => {
      client.setQueryData(settingsKeys.settings(cid.value), data);
      void refreshMe();
    },
  });
}

export function useLogo() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refreshMe = useRefreshMe();
  return useMutation({
    mutationFn: (file: File | null) => (file ? uploadLogo(cid.value, file) : removeLogo(cid.value)),
    onSuccess: (data) => {
      client.setQueryData(settingsKeys.settings(cid.value), data);
      void refreshMe();
    },
  });
}

/** Flips one module at once on screen; puts it back if the server refuses. */
export function useToggleModule() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refreshMe = useRefreshMe();
  return useMutation({
    mutationFn: (features: CompanyFeature[]) => setFeatures(cid.value, features),
    onMutate: async (features) => {
      const key = settingsKeys.features(cid.value);
      await client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<Features>(key);
      if (before) {
        client.setQueryData<Features>(key, {
          features,
          modules: before.modules.map((m) => ({ ...m, enabled: features.includes(m.key) })),
        });
      }
      return { before };
    },
    onError: (_error, _features, context) => {
      if (context?.before) client.setQueryData(settingsKeys.features(cid.value), context.before);
    },
    onSuccess: (data) => {
      client.setQueryData(settingsKeys.features(cid.value), data);
      void refreshMe();
      void client.invalidateQueries({ queryKey: [cid.value, "setup"] });
    },
  });
}

export function useBranchMutations() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refreshMe = useRefreshMe();
  const done = () => {
    void client.invalidateQueries({ queryKey: settingsKeys.branches(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "setup"] });
    void refreshMe();
  };
  return {
    create: useMutation({ mutationFn: (input: Partial<BranchInput>) => createBranch(cid.value, input), onSuccess: done }),
    update: useMutation({ mutationFn: ({ id, input }: { id: number; input: Partial<BranchInput> }) => updateBranch(cid.value, id, input), onSuccess: done }),
    deactivate: useMutation({ mutationFn: (id: number) => deactivateBranch(cid.value, id), onSuccess: done }),
    activate: useMutation({ mutationFn: (id: number) => activateBranch(cid.value, id), onSuccess: done }),
    reorder: useMutation({
      mutationFn: (ids: number[]) => reorderBranches(cid.value, ids),
      onMutate: async (ids) => {
        const key = settingsKeys.branches(cid.value);
        await client.cancelQueries({ queryKey: key });
        const before = client.getQueryData<Branch[]>(key);
        if (before) {
          const byId = new Map(before.map((b) => [b.id, b]));
          client.setQueryData<Branch[]>(key, ids.map((id) => byId.get(id)!).filter(Boolean));
        }
        return { before };
      },
      onError: (_e, _ids, context) => context?.before && client.setQueryData(settingsKeys.branches(cid.value), context.before),
      onSuccess: (data) => client.setQueryData(settingsKeys.branches(cid.value), data),
    }),
  };
}

export function useRegenerateInvite() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return useMutation({
    mutationFn: () => regenerateInvite(cid.value),
    onSuccess: (data) => client.setQueryData(settingsKeys.invite(cid.value), data),
  });
}

/** Saves one notification kind; the switch moves at once and moves back on an error. */
export function useSavePreference() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return useMutation({
    mutationFn: (row: Pick<NotificationPreference, "kind" | "in_app" | "telegram">) => putPreferences(cid.value, [row]),
    onMutate: async (row) => {
      const key = settingsKeys.preferences(cid.value);
      await client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<NotificationPreference[]>(key);
      if (before) client.setQueryData<NotificationPreference[]>(key, before.map((r) => (r.kind === row.kind ? { ...r, ...row } : r)));
      return { before };
    },
    onError: (_e, _row, context) => context?.before && client.setQueryData(settingsKeys.preferences(cid.value), context.before),
    onSuccess: (data) => client.setQueryData(settingsKeys.preferences(cid.value), data),
  });
}

export function useSessionMutations() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refresh = () => void client.invalidateQueries({ queryKey: settingsKeys.sessions(cid.value) });
  return {
    revoke: useMutation({
      mutationFn: (id: number) => revokeSession(id),
      onMutate: async (id) => {
        const key = settingsKeys.sessions(cid.value);
        await client.cancelQueries({ queryKey: key });
        const before = client.getQueryData<DeviceSession[]>(key);
        if (before) client.setQueryData<DeviceSession[]>(key, before.filter((s) => s.id !== id));
        return { before };
      },
      onError: (_e, _id, context) => context?.before && client.setQueryData(settingsKeys.sessions(cid.value), context.before),
      onSettled: refresh,
    }),
    revokeAll: useMutation({ mutationFn: (keepCurrent: boolean) => revokeAllSessions(keepCurrent), onSettled: refresh }),
  };
}
