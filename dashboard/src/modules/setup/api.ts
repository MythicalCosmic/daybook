/**
 * "Get started" (`setup/`) and "New company" (`/owner/companies/`) as typed functions and
 * vue-query helpers. Setup queries live under `[companyId, "setup"]`, so the module's
 * `invalidates` ("companies", "groups") refreshes the checklist when a step gets done elsewhere.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed } from "vue";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

import type { CreatedCompany, NewCompanyInfo, NewCompanyInput, Setup } from "./types";

export const MODULE = "setup";

export const getSetup = (cid: number, signal?: AbortSignal) => http.get<Setup>(ownerPath(cid, "setup/"), undefined, { signal });
export const dismissSetup = (cid: number) => http.post<Setup>(ownerPath(cid, "setup/dismiss/"));
export const resumeSetup = (cid: number) => http.post<Setup>(ownerPath(cid, "setup/resume/"));
export const getNewCompanyInfo = (signal?: AbortSignal) => http.get<NewCompanyInfo>("/owner/companies/new/", undefined, { signal });
export const createCompany = (input: NewCompanyInput) => http.post<CreatedCompany>("/owner/companies/", input, { toast: false });

export const setupKeys = {
  steps: (cid: number) => qk(cid, MODULE, "steps"),
  newCompany: () => qk(0, MODULE, "new-company"),
};

/** The checklist of the current company (`enabled` lets the sidebar pill wait until it's needed). */
export function useSetup(enabled = computed(() => true)) {
  const company = useCompanyStore();
  const cid = computed(() => company.currentId ?? 0);
  return useQuery({
    queryKey: computed(() => setupKeys.steps(cid.value)),
    queryFn: ({ signal }) => getSetup(cid.value, signal),
    enabled: computed(() => cid.value > 0 && enabled.value),
    staleTime: 30_000,
  });
}

export function useSetupVisibility() {
  const client = useQueryClient();
  const company = useCompanyStore();
  const session = useSessionStore();
  const cid = computed(() => company.currentId ?? 0);
  const settle = (data: Setup) => {
    client.setQueryData(setupKeys.steps(cid.value), data);
    void session.loadMe().catch(() => undefined);
  };
  return {
    dismiss: useMutation({ mutationFn: () => dismissSetup(cid.value), onSuccess: settle }),
    resume: useMutation({ mutationFn: () => resumeSetup(cid.value), onSuccess: settle }),
  };
}

export function useNewCompanyInfo() {
  return useQuery({ queryKey: setupKeys.newCompany(), queryFn: ({ signal }) => getNewCompanyInfo(signal), staleTime: 0 });
}
