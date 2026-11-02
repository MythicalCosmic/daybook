/**
 * The HR endpoints (plan §4.10, prefix `hr/`) as typed functions, and the vue-query helpers. Keys
 * start with `[companyId, "hr"]`, so the `hr` pulse version refreshes everything here.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, type Query } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyId } from "@/stores/company";

import type {
  Celebration,
  Compliance,
  Contract,
  ContractAction,
  ContractInput,
  ContractParams,
  ContractTemplate,
  DocumentInput,
  DocumentParams,
  EmergencyContact,
  EmergencyContactInput,
  HrDocument,
  HrOverview,
  HrProfile,
  HrSensitive,
  HrSettings,
  ProfileInput,
  RequiredDocument,
  TemplateInput,
  TemplatePreview,
} from "./types";

export const MODULE = "hr";

const path = (cid: number, rest: string) => ownerPath(cid, `hr/${rest}`);

/** A JSON body, or a form when a file goes with it (the file under `field`). */
function body(input: Record<string, unknown>, field: string): FormData | Record<string, unknown> {
  const file = input[field];
  if (!(file instanceof File)) {
    const { [field]: _skip, ...rest } = input;
    return rest;
  }
  const form = new FormData();
  for (const [key, value] of Object.entries(input)) {
    if (value === null || value === undefined) continue;
    form.append(key, value instanceof File ? value : String(value));
  }
  return form;
}

const send = <T>(method: "post" | "patch", url: string, payload: FormData | Record<string, unknown>) =>
  payload instanceof FormData ? http.form<T>(url, payload, method === "patch" ? { method: "PATCH" } : undefined) : http[method]<T>(url, payload);

// ─── Endpoints ──────────────────────────────────────────────────────────────

export const hrApi = {
  overview: (cid: number, signal?: AbortSignal) => http.get<HrOverview>(path(cid, "overview/"), undefined, { signal }),

  profile: (cid: number, mid: number, signal?: AbortSignal) => http.get<HrProfile>(path(cid, `people/${mid}/profile/`), undefined, { signal }),
  updateProfile: (cid: number, mid: number, input: ProfileInput) => http.patch<HrProfile>(path(cid, `people/${mid}/profile/`), input),
  sensitive: (cid: number, mid: number) => http.get<HrSensitive>(path(cid, `people/${mid}/sensitive/`)),

  contacts: (cid: number, mid: number, signal?: AbortSignal) => http.get<EmergencyContact[] | Page<EmergencyContact>>(path(cid, `people/${mid}/emergency-contacts/`), undefined, { signal }),
  addContact: (cid: number, mid: number, input: EmergencyContactInput) => http.post<EmergencyContact>(path(cid, `people/${mid}/emergency-contacts/`), input),
  updateContact: (cid: number, mid: number, id: number, input: Partial<EmergencyContactInput>) => http.patch<EmergencyContact>(path(cid, `people/${mid}/emergency-contacts/${id}/`), input),
  removeContact: (cid: number, mid: number, id: number) => http.delete<void>(path(cid, `people/${mid}/emergency-contacts/${id}/`)),

  documents: (cid: number, params: DocumentParams, signal?: AbortSignal) => http.get<Page<HrDocument>>(path(cid, "documents/"), params as Query, { signal }),
  document: (cid: number, id: number, signal?: AbortSignal) => http.get<HrDocument>(path(cid, `documents/${id}/`), undefined, { signal }),
  uploadDocument: (cid: number, input: DocumentInput) => send<HrDocument>("post", path(cid, "documents/"), body({ ...input }, "file")),
  updateDocument: (cid: number, id: number, input: Partial<DocumentInput>) => send<HrDocument>("patch", path(cid, `documents/${id}/`), body({ ...input }, "file")),
  removeDocument: (cid: number, id: number) => http.delete<void>(path(cid, `documents/${id}/`)),
  verifyDocument: (cid: number, id: number) => http.post<HrDocument>(path(cid, `documents/${id}/verify/`)),
  compliance: (cid: number, params: { branch?: number[]; position?: number[] }, signal?: AbortSignal) => http.get<Compliance>(path(cid, "documents/compliance/"), params as Query, { signal }),

  required: (cid: number, signal?: AbortSignal) => http.get<RequiredDocument[] | Page<RequiredDocument>>(path(cid, "required-documents/"), { page_size: 200 }, { signal }),
  addRequired: (cid: number, input: { kind: string; position_id: number | null }) => http.post<RequiredDocument>(path(cid, "required-documents/"), input),
  removeRequired: (cid: number, id: number) => http.delete<void>(path(cid, `required-documents/${id}/`)),

  contracts: (cid: number, params: ContractParams, signal?: AbortSignal) => http.get<Page<Contract>>(path(cid, "contracts/"), params as Query, { signal }),
  contract: (cid: number, id: number, signal?: AbortSignal) => http.get<Contract>(path(cid, `contracts/${id}/`), undefined, { signal }),
  createContract: (cid: number, input: ContractInput) => send<Contract>("post", path(cid, "contracts/"), body({ ...input }, "file")),
  updateContract: (cid: number, id: number, input: Partial<ContractInput>) => send<Contract>("patch", path(cid, `contracts/${id}/`), body({ ...input }, "file")),
  removeContract: (cid: number, id: number) => http.delete<void>(path(cid, `contracts/${id}/`)),
  contractAction: (cid: number, id: number, action: ContractAction, payload: Record<string, unknown> = {}) => http.post<Contract>(path(cid, `contracts/${id}/${action}/`), payload),

  templates: (cid: number, signal?: AbortSignal) => http.get<ContractTemplate[] | Page<ContractTemplate>>(path(cid, "contract-templates/"), { page_size: 200 }, { signal }),
  template: (cid: number, id: number, signal?: AbortSignal) => http.get<ContractTemplate>(path(cid, `contract-templates/${id}/`), undefined, { signal }),
  createTemplate: (cid: number, input: TemplateInput) => http.post<ContractTemplate>(path(cid, "contract-templates/"), input),
  updateTemplate: (cid: number, id: number, input: Partial<TemplateInput>) => http.patch<ContractTemplate>(path(cid, `contract-templates/${id}/`), input),
  removeTemplate: (cid: number, id: number) => http.delete<void>(path(cid, `contract-templates/${id}/`)),
  /** A saved template filled in for a person, or unsaved text (`id` null: `body` is required). */
  previewTemplate: (cid: number, id: number | null, input: { member_id: number | null; body?: string; language?: string }, signal?: AbortSignal) =>
    http.post<TemplatePreview>(path(cid, id ? `contract-templates/${id}/preview/` : "contract-templates/preview/"), input, { signal, toast: false }),

  celebrations: (cid: number, range: { from: string; to: string }, signal?: AbortSignal) => http.get<Celebration[] | Page<Celebration>>(path(cid, "celebrations/"), range, { signal }),

  settings: (cid: number, signal?: AbortSignal) => http.get<HrSettings>(path(cid, "settings/"), undefined, { signal }),
  saveSettings: (cid: number, input: Partial<HrSettings>) => http.patch<HrSettings>(path(cid, "settings/"), input),
};

/** Lists that may come paginated or plain. */
export function rowsOf<T>(body: T[] | Page<T> | undefined | null): T[] {
  if (!body) return [];
  return Array.isArray(body) ? body : body.results;
}

// ─── Keys and queries ──────────────────────────────────────────────────────

export const hrKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  overview: (cid: number) => qk(cid, MODULE, "overview"),
  profile: (cid: number, mid: number) => qk(cid, MODULE, "profile", { mid }),
  contacts: (cid: number, mid: number) => qk(cid, MODULE, "contacts", { mid }),
  documents: (cid: number, params: DocumentParams) => qk(cid, MODULE, "documents", { ...params }),
  document: (cid: number, id: number) => qk(cid, MODULE, "document", { id }),
  compliance: (cid: number, params: Record<string, unknown>) => qk(cid, MODULE, "compliance", params),
  required: (cid: number) => qk(cid, MODULE, "required"),
  contracts: (cid: number, params: ContractParams) => qk(cid, MODULE, "contracts", { ...params }),
  contract: (cid: number, id: number) => qk(cid, MODULE, "contract", { id }),
  templates: (cid: number) => qk(cid, MODULE, "templates"),
  template: (cid: number, id: number) => qk(cid, MODULE, "template", { id }),
  celebrations: (cid: number, range: { from: string; to: string }) => qk(cid, MODULE, "celebrations", { ...range }),
  settings: (cid: number) => qk(cid, MODULE, "settings"),
};

const enabledFor = (cid: { value: number }, extra: MaybeRefOrGetter<boolean> = true) => computed(() => cid.value > 0 && toValue(extra));

export function useOverview() {
  const cid = useCompanyId();
  return useQuery({ queryKey: computed(() => hrKeys.overview(cid.value)), queryFn: ({ signal }) => hrApi.overview(cid.value, signal), enabled: enabledFor(cid), staleTime: 30_000 });
}

export function useProfile(mid: MaybeRefOrGetter<number>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => hrKeys.profile(cid.value, toValue(mid))),
    queryFn: ({ signal }) => hrApi.profile(cid.value, toValue(mid), signal),
    enabled: enabledFor(cid, () => toValue(mid) > 0),
    staleTime: 30_000,
  });
}

export function useDocuments(params: MaybeRefOrGetter<DocumentParams>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => hrKeys.documents(cid.value, toValue(params))),
    queryFn: ({ signal }) => hrApi.documents(cid.value, toValue(params), signal),
    enabled: enabledFor(cid, enabled),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useDocument(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => hrKeys.document(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => hrApi.document(cid.value, toValue(id)!, signal),
    enabled: enabledFor(cid, () => !!toValue(id)),
    staleTime: 15_000,
  });
}

export function useCompliance(params: MaybeRefOrGetter<{ branch?: number[]; position?: number[] }>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => hrKeys.compliance(cid.value, { ...toValue(params) })),
    queryFn: ({ signal }) => hrApi.compliance(cid.value, toValue(params), signal),
    enabled: enabledFor(cid, enabled),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useRequired(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => hrKeys.required(cid.value)),
    queryFn: async ({ signal }) => rowsOf(await hrApi.required(cid.value, signal)),
    enabled: enabledFor(cid, enabled),
    staleTime: 60_000,
  });
}

export function useContracts(params: MaybeRefOrGetter<ContractParams>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => hrKeys.contracts(cid.value, toValue(params))),
    queryFn: ({ signal }) => hrApi.contracts(cid.value, toValue(params), signal),
    enabled: enabledFor(cid, enabled),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useContract(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => hrKeys.contract(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => hrApi.contract(cid.value, toValue(id)!, signal),
    enabled: enabledFor(cid, () => !!toValue(id)),
    staleTime: 15_000,
  });
}

export function useTemplates(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => hrKeys.templates(cid.value)),
    queryFn: async ({ signal }) => rowsOf(await hrApi.templates(cid.value, signal)),
    enabled: enabledFor(cid, enabled),
    staleTime: 60_000,
  });
}

export function useTemplate(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => hrKeys.template(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => hrApi.template(cid.value, toValue(id)!, signal),
    enabled: enabledFor(cid, () => !!toValue(id)),
    staleTime: 60_000,
  });
}

export function useCelebrations(range: MaybeRefOrGetter<{ from: string; to: string }>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => hrKeys.celebrations(cid.value, toValue(range))),
    queryFn: async ({ signal }) => rowsOf(await hrApi.celebrations(cid.value, toValue(range), signal)),
    enabled: enabledFor(cid),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useHrSettings(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({ queryKey: computed(() => hrKeys.settings(cid.value)), queryFn: ({ signal }) => hrApi.settings(cid.value, signal), enabled: enabledFor(cid, enabled), staleTime: 60_000 });
}

/** The company's warning windows (Settings › HR), the defaults until they load. */
export function useWarnDays() {
  const settings = useHrSettings();
  return computed(() => {
    const row = settings.data.value;
    return { documents: row?.document_warn_days ?? 30, contracts: row?.contract_warn_days ?? 30, probation: row?.probation_warn_days ?? 7 };
  });
}

// ─── Mutations ─────────────────────────────────────────────────────────────

/** Everything HR shows again, plus the people pages (a profile feeds Person 360) and the shell's pulse. */
export function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: hrKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "people"] });
    void client.invalidateQueries({ queryKey: [cid.value, "shell"] });
  };
}

/** A mutation on the current company that refreshes HR when it settles. */
export function useHrMutation<I, O>(run: (cid: number, input: I) => Promise<O>) {
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({ mutationFn: (input: I) => run(cid.value, input), onSettled: refresh });
}
