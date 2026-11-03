/**
 * The employee's own disciplinary records (`/companies/<id>/lifecycle/records/…`,
 * backend/apps/lifecycle/api.py, PLAN-OWNER §13.4 "My record") as react-query hooks. Opening one
 * marks it read; acknowledging says "I was told" (it isn't agreeing); an explanation is the
 * person's side, written once here.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";
import type { components } from "../../api/schema";

export type DisciplinaryRecord = components["schemas"]["LifecycleMyRecord"];

export const recordKeys = {
  all: (company: number) => ["lifecycle", company] as const,
  list: (company: number) => ["lifecycle", company, "records"] as const,
  one: (company: number, id: number) => ["lifecycle", company, "record", id] as const,
};

const base = (company: number) => `/companies/${company}/lifecycle/records`;

/** A fresher record replaces its copy in the list (read, acknowledged, explained). */
function store(client: QueryClient, company: number, record: DisciplinaryRecord): void {
  client.setQueryData(recordKeys.one(company, record.id), record);
  client.setQueryData<DisciplinaryRecord[]>(recordKeys.list(company), (rows) => rows?.map((row) => (row.id === record.id ? record : row)));
}

/** My records, newest first. */
export function useRecords(company: number, enabled = true) {
  return useQuery({ queryKey: recordKeys.list(company), queryFn: () => api<DisciplinaryRecord[]>(`${base(company)}/`), staleTime: 60_000, enabled });
}

/** One record; opening it marks it read, so the list and Home let go of "new". */
export function useRecord(company: number, id: number) {
  const client = useQueryClient();
  return useQuery({
    queryKey: recordKeys.one(company, id),
    queryFn: async () => {
      const record = await api<DisciplinaryRecord>(`${base(company)}/${id}/`);
      store(client, company, record);
      return record;
    },
  });
}

/** "Tanishdim": I was told about it. */
export function useAcknowledgeRecord(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<DisciplinaryRecord>(`${base(company)}/${id}/acknowledge/`, { method: "POST" }),
    onSuccess: (record) => store(client, company, record),
  });
}

/** My explanation, with the text as I wrote it. */
export function useExplain(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, text }: { id: number; text: string }) => api<DisciplinaryRecord>(`${base(company)}/${id}/explain/`, { json: { text } }),
    onSuccess: (record) => store(client, company, record),
  });
}
