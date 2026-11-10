/**
 * The policy endpoints (`hr/policies/…`, backend/apps/hr/policies/owner_api.py) as typed functions
 * and vue-query helpers. Keys start with `[companyId, "hr"]`, so the `hr.policies` pulse (and every
 * other HR change) refreshes them.
 */
import { keepPreviousData, useQuery } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, type Query } from "@/api/http";
import { qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyId } from "@/stores/company";

import { MODULE } from "../api";
import type {
  DraftInput,
  PersonPolicies,
  Policy,
  PolicyAudience,
  PolicyDetail,
  PolicyInput,
  PolicyVersionDetail,
  PublishInput,
  Signature,
  SignatureParams,
} from "./types";

const path = (cid: number, rest: string) => ownerPath(cid, `hr/${rest}`);

export interface PolicyListParams {
  view?: "active" | "drafts" | "archived" | "all";
  category?: string[];
  q?: string;
}

/** A draft with a new file goes as a form; anything else as JSON. */
function draftBody(input: DraftInput): FormData | Record<string, unknown> {
  if (!(input.file instanceof File)) {
    const { file: _file, ...rest } = input;
    return rest;
  }
  const form = new FormData();
  for (const [key, value] of Object.entries(input)) {
    if (value === null || value === undefined) continue;
    form.append(key, value instanceof File ? value : String(value));
  }
  return form;
}

export const policyApi = {
  list: (cid: number, params: PolicyListParams, signal?: AbortSignal) => http.get<Policy[]>(path(cid, "policies/"), params as Query, { signal }),
  get: (cid: number, id: number, signal?: AbortSignal) => http.get<PolicyDetail>(path(cid, `policies/${id}/`), undefined, { signal }),
  create: (cid: number, input: PolicyInput) => http.post<PolicyDetail>(path(cid, "policies/"), input),
  update: (cid: number, id: number, input: PolicyInput) => http.patch<PolicyDetail>(path(cid, `policies/${id}/`), input),
  remove: (cid: number, id: number) => http.delete<void>(path(cid, `policies/${id}/`)),
  saveDraft: (cid: number, id: number, input: DraftInput) => {
    const payload = draftBody(input);
    const url = path(cid, `policies/${id}/draft/`);
    return payload instanceof FormData ? http.form<PolicyVersionDetail>(url, payload, { method: "PUT" }) : http.put<PolicyVersionDetail>(url, payload);
  },
  discardDraft: (cid: number, id: number) => http.delete<void>(path(cid, `policies/${id}/draft/`)),
  publish: (cid: number, id: number, input: PublishInput) => http.post<PolicyDetail>(path(cid, `policies/${id}/publish/`), input),
  version: (cid: number, id: number, number: number, signal?: AbortSignal) => http.get<PolicyVersionDetail>(path(cid, `policies/${id}/versions/${number}/`), undefined, { signal }),
  signatures: (cid: number, id: number, params: SignatureParams, signal?: AbortSignal) =>
    http.get<Page<Signature>>(path(cid, `policies/${id}/acknowledgements/`), params as Query, { signal }),
  remind: (cid: number, id: number, memberIds?: number[]) => http.post<{ reminded: number }>(path(cid, `policies/${id}/remind/`), memberIds ? { member_ids: memberIds } : {}),
  audience: (cid: number, params: { position?: number[]; branch?: number[] }, signal?: AbortSignal) =>
    http.get<PolicyAudience>(path(cid, "policies/audience/"), params as Query, { signal }),
  person: (cid: number, mid: number, signal?: AbortSignal) => http.get<PersonPolicies>(path(cid, `people/${mid}/policies/`), undefined, { signal }),
};

export const policyKeys = {
  list: (cid: number, params: PolicyListParams) => qk(cid, MODULE, "policies", { ...params }),
  detail: (cid: number, id: number) => qk(cid, MODULE, "policy", { id }),
  version: (cid: number, id: number, number: number) => qk(cid, MODULE, "policy-version", { id, number }),
  signatures: (cid: number, id: number, params: SignatureParams) => qk(cid, MODULE, "policy-signatures", { id, ...params }),
  audience: (cid: number, params: { position?: number[]; branch?: number[] }) => qk(cid, MODULE, "policy-audience", { ...params }),
  person: (cid: number, mid: number) => qk(cid, MODULE, "person-policies", { mid }),
};

const enabledFor = (cid: { value: number }, extra: MaybeRefOrGetter<boolean> = true) => computed(() => cid.value > 0 && toValue(extra));

export function usePolicies(params: MaybeRefOrGetter<PolicyListParams>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => policyKeys.list(cid.value, toValue(params))),
    queryFn: ({ signal }) => policyApi.list(cid.value, toValue(params), signal),
    enabled: enabledFor(cid),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function usePolicy(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => policyKeys.detail(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => policyApi.get(cid.value, toValue(id)!, signal),
    enabled: enabledFor(cid, () => !!toValue(id)),
    staleTime: 15_000,
  });
}

export function usePolicyVersion(id: MaybeRefOrGetter<number | null>, number: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => policyKeys.version(cid.value, toValue(id) ?? 0, toValue(number) ?? 0)),
    queryFn: ({ signal }) => policyApi.version(cid.value, toValue(id)!, toValue(number)!, signal),
    enabled: enabledFor(cid, () => !!toValue(id) && !!toValue(number)),
    // A version's text never changes once published; its file link expires, so it is asked again.
    staleTime: 5 * 60_000,
  });
}

export function useSignatures(id: MaybeRefOrGetter<number | null>, params: MaybeRefOrGetter<SignatureParams>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => policyKeys.signatures(cid.value, toValue(id) ?? 0, toValue(params))),
    queryFn: ({ signal }) => policyApi.signatures(cid.value, toValue(id)!, toValue(params), signal),
    enabled: enabledFor(cid, () => !!toValue(id) && toValue(enabled)),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useAudience(params: MaybeRefOrGetter<{ position?: number[]; branch?: number[] }>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => policyKeys.audience(cid.value, toValue(params))),
    queryFn: ({ signal }) => policyApi.audience(cid.value, toValue(params), signal),
    enabled: enabledFor(cid, enabled),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function usePersonPolicies(mid: MaybeRefOrGetter<number>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => policyKeys.person(cid.value, toValue(mid))),
    queryFn: ({ signal }) => policyApi.person(cid.value, toValue(mid), signal),
    enabled: enabledFor(cid, () => toValue(mid) > 0),
    staleTime: 30_000,
  });
}
