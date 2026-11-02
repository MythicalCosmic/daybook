/**
 * The employee HR endpoints (`/companies/<id>/hr/…`, backend/apps/hr/api.py, PLAN-OWNER §4.10
 * prefix E) as react-query hooks: my profile and emergency contacts, my documents (and uploading
 * one), my contract (and "I've read it"). Every key starts with ["hr", company].
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, apiForm, ApiError } from "../../api/client";
import type { components } from "../../api/schema";
import { downscale } from "../../lib/image";

type Schemas = components["schemas"];

export type Profile = Schemas["HrMyProfile"];
export type ProfileChanges = Schemas["PatchedHrMyProfileUpdateRequest"];
export type Contact = Schemas["HrEmergencyContact"];
export type ContactDraft = Schemas["HrEmergencyContactRequest"];
export type HrDocument = Schemas["HrMyDocument"];
export type DocumentKind = Schemas["HrDocumentKindEnum"];
export type DocumentState = Schemas["HrDocumentStateEnum"];
export type Contract = Schemas["HrMyContract"];

/** An upload: the kind, the file, and what the person could read off it. */
export type DocumentUpload = { kind: DocumentKind; file: File; number?: string; expires_on?: string | null };

export const hrKeys = {
  all: (company: number) => ["hr", company] as const,
  profile: (company: number) => ["hr", company, "profile"] as const,
  documents: (company: number) => ["hr", company, "documents"] as const,
  contract: (company: number) => ["hr", company, "contract"] as const,
};

const base = (company: number) => `/companies/${company}/hr`;
const STALE = 60_000;

/** My profile: details, masked IDs and card, emergency contacts. */
export function useProfile(company: number, enabled = true) {
  return useQuery({ queryKey: hrKeys.profile(company), queryFn: () => api<Profile>(`${base(company)}/profile/`), staleTime: STALE, enabled });
}

/** Change what a person may change on their own profile; the answer is the whole profile again. */
export function useUpdateProfile(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: ProfileChanges) => api<Profile>(`${base(company)}/profile/`, { method: "PATCH", json: changes }),
    onSuccess: (profile) => client.setQueryData(hrKeys.profile(company), profile),
  });
}

/** Add, change or remove an emergency contact (three at most); the profile carries the list. */
export function useSaveContact(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, draft }: { id: number | null; draft: ContactDraft }) =>
      id === null
        ? api<Contact>(`${base(company)}/profile/emergency-contacts/`, { json: draft })
        : api<Contact>(`${base(company)}/profile/emergency-contacts/${id}/`, { method: "PATCH", json: draft }),
    onSuccess: () => client.invalidateQueries({ queryKey: hrKeys.profile(company) }),
  });
}

export function useRemoveContact(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`${base(company)}/profile/emergency-contacts/${id}/`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: hrKeys.profile(company) }),
  });
}

/** My documents (those HR shows me), by kind. */
export function useDocuments(company: number, enabled = true) {
  return useQuery({ queryKey: hrKeys.documents(company), queryFn: () => api<HrDocument[]>(`${base(company)}/documents/`), staleTime: STALE, enabled });
}

/** Upload a document (a renewed medical book, a new certificate): HR checks it afterwards. */
export function useUploadDocument(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ kind, file, number, expires_on }: DocumentUpload) =>
      // A phone photo of a page is 3-5 MB: made smaller first, as receipts are; a PDF goes as it is.
      apiForm<HrDocument>(`${base(company)}/documents/`, { kind, number: number || undefined, expires_on: expires_on ?? undefined, file: await downscale(file, 2400) }),
    onSuccess: () => client.invalidateQueries({ queryKey: hrKeys.documents(company) }),
  });
}

/**
 * My contract (in force, else the latest), or null when there is none on file yet: the server
 * says so with a 404, which is an answer here, not a failure.
 */
export function useContract(company: number, enabled = true) {
  return useQuery({
    queryKey: hrKeys.contract(company),
    queryFn: () =>
      api<Contract>(`${base(company)}/contract/`).catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }),
    staleTime: STALE,
    enabled,
  });
}

/** A fresh signed link to the contract's file (they expire within minutes, so asked for on tap). */
export function contractPdf(company: number): () => Promise<string> {
  return () => api<{ url: string }>(`${base(company)}/contract/pdf/`).then((link) => link.url);
}

/** "I've read it" for the contract in force. */
export function useAcknowledgeContract(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<Contract>(`${base(company)}/contract/${id}/acknowledge/`, { method: "POST" }),
    onSuccess: (contract) => client.setQueryData(hrKeys.contract(company), contract),
  });
}
