/**
 * The rules I read and sign (`/companies/<id>/hr/policies/…`, backend/apps/hr/policies/api.py) as
 * react-query hooks, with their shapes written by hand until the lead regenerates the schema. Keys
 * start with ["hr", company], so the HR feature's refreshes reach them.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";

export type PolicyCategory = "dispensing" | "storage" | "safety" | "conduct" | "other";
/** Where I stand: to sign (in time or late), signed, or a rule that only asks to be read. */
export type PolicyState = "waiting" | "late" | "signed" | "to_read";

export type MyPolicy = {
  id: number;
  title: string;
  category: PolicyCategory;
  /** The version in force. */
  number: number;
  published_at: string;
  state: PolicyState;
  due_on: string | null;
  signed_at: string | null;
  signed_number: number | null;
  has_file: boolean;
};

export type MyPolicyDetail = MyPolicy & {
  /** Sign this version. */
  version_id: number;
  body: string;
  change_note: string;
  /** False when the version in force is a small edit of the one signed. */
  asks_again: boolean;
  file_type: "pdf" | "image" | null;
};

export const policyKeys = {
  list: (company: number) => ["hr", company, "policies"] as const,
  one: (company: number, id: number) => ["hr", company, "policies", id] as const,
};

const base = (company: number) => `/companies/${company}/hr/policies`;
const STALE = 60_000;

/** Late first, then waiting by the deadline, then signed and to read (the server's order). */
export function useMyPolicies(company: number, enabled = true) {
  return useQuery({
    queryKey: policyKeys.list(company),
    queryFn: () => api<MyPolicy[]>(`${base(company)}/`).then((rows) => (Array.isArray(rows) ? rows : [])),
    staleTime: STALE,
    enabled,
  });
}

export function useMyPolicy(company: number, id: number) {
  return useQuery({
    queryKey: policyKeys.one(company, id),
    queryFn: () => api<MyPolicyDetail>(`${base(company)}/${id}/`),
    staleTime: STALE,
    enabled: id > 0,
  });
}

/** A fresh signed link to the rule's file (they expire within minutes, so asked for on tap). */
export function policyFile(company: number, id: number): () => Promise<string> {
  return () => api<{ url: string }>(`${base(company)}/${id}/file/`).then((link) => link.url);
}

/** "O‘qidim va roziman" for the version in force; signing twice changes nothing. */
export function useSignPolicy(company: number, id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (versionId: number) => api<MyPolicyDetail>(`${base(company)}/versions/${versionId}/acknowledge/`, { method: "POST" }),
    onSuccess: (policy) => {
      client.setQueryData(policyKeys.one(company, id), policy);
      void client.invalidateQueries({ queryKey: policyKeys.list(company) });
    },
  });
}

export const toSign = (rows: readonly MyPolicy[] | undefined): MyPolicy[] => (rows ?? []).filter((row) => row.state === "waiting" || row.state === "late");
