/**
 * The employee's own disciplinary records (`/companies/<id>/lifecycle/records/…`,
 * backend/apps/lifecycle/api.py, PLAN-OWNER §13.4 "My record") as react-query hooks. Opening one
 * marks it read; acknowledging says "I was told" (it isn't agreeing); an explanation is the
 * person's side, written once here. Below them: my leaving (the resignation request, the day
 * agreed, the handover list, my answers before I go) and my career (my job changes).
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

// — Leaving ("Ishdan ketish arizasi") and my career —
// `/companies/<id>/lifecycle/leaving/…` and `…/lifecycle/career/` (backend/apps/lifecycle/api.py,
// MyLeaving* and MyCareer* serializers). Hand-written: the generated schema doesn't have them yet.

export const EXIT_REASONS = ["pay", "schedule", "workload", "team", "growth", "moving", "studies", "health", "family", "other"] as const;
export type ExitReason = (typeof EXIT_REASONS)[number];
export const RECOMMEND = ["yes", "maybe", "no"] as const;
export type Recommend = (typeof RECOMMEND)[number];

export type HandoverKind = "equipment" | "tasks" | "keys" | "documents" | "other";

/** One thing to hand over, as I read it (HR ticks them off). */
export type MyHandoverItem = {
  id: number;
  kind: HandoverKind;
  /** Empty for the standard items (keys, documents, tasks): the app names them. */
  title: string;
  done: boolean;
  /** The tasks item: how many of my tasks are still open (null for the others). */
  open_tasks: number | null;
};

export type ExitAnswers = { reason: ExitReason; better: string; recommend: Recommend | ""; answered_at: string };

export type LeavingStatus = "requested" | "agreed" | "completed" | "withdrawn" | "declined";

/** My leaving: the request I made (or HR started), the day agreed, the handover, my answers. */
export type MyLeaving = {
  id: number;
  kind: "resignation" | "company" | "contract_end" | "other";
  status: LeavingStatus;
  /** I asked for it in the app. */
  mine: boolean;
  wished_last_day: string | null;
  last_day: string | null;
  left_on: string | null;
  reason: string;
  requested_at: string;
  agreed_at: string | null;
  /** Who agreed my last day. */
  agreed_by: string | null;
  /** Why it was declined or called off. */
  close_reason: string;
  closed_by_me: boolean;
  notice_days: number | null;
  handover: MyHandoverItem[];
  exit_interview: ExitAnswers | null;
  can_withdraw: boolean;
  can_answer: boolean;
};

/** `GET lifecycle/leaving/`: my open leaving (or the last one closed in 30 days) and whether I may ask. */
export type LeavingState = {
  current: MyLeaving | null;
  can_request: boolean;
  /** The usual notice, in days (two weeks). */
  notice_days: number;
  /** Today in the company (YYYY-MM-DD). */
  today: string;
};

export type JobPart = "position" | "branch" | "department" | "pay";
export type JobRef = { id: number; name: string };
export type JobPay = { amount: string; currency: string; pay_type: "monthly" | "daily" | "hourly" | "per_task" };
export type JobSide = {
  position: JobRef | null;
  branch: JobRef | null;
  branches: JobRef[];
  department: JobRef | null;
  role: JobRef | null;
  pay: JobPay | null;
};

/** One of my job changes: applied, or approved and waiting for its day. My own pay is in it. */
export type MyJobChange = {
  id: number;
  effective_on: string;
  status: "approved" | "applied";
  parts: JobPart[];
  before: JobSide;
  after: JobSide;
  applied_at: string | null;
};

export type MyCareer = {
  hired_on: string | null;
  position: string | null;
  branch: string | null;
  department: string | null;
  changes: MyJobChange[];
};

export const leavingKeys = {
  state: (company: number) => ["lifecycle", company, "leaving"] as const,
  career: (company: number) => ["lifecycle", company, "career"] as const,
};

const leaving = (company: number) => `/companies/${company}/lifecycle/leaving`;

/** My leaving now. Home, Me and the page share one copy. */
export function useLeaving(company: number, enabled = true) {
  return useQuery({ queryKey: leavingKeys.state(company), queryFn: () => api<LeavingState>(`${leaving(company)}/`), staleTime: 60_000, enabled });
}

/** Every write answers with the whole state: it replaces the copy everyone reads. */
function useLeavingWrite<V>(company: number, run: (variables: V) => Promise<LeavingState>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: run, onSuccess: (state) => client.setQueryData(leavingKeys.state(company), state) });
}

/** "Ishdan ketish arizasi": I ask to leave from a day, with my reason (optional). */
export function useRequestLeaving(company: number) {
  return useLeavingWrite(company, (body: { wished_last_day: string; reason: string }) => api<LeavingState>(`${leaving(company)}/`, { json: body }));
}

/** I stay after all (before my last day). */
export function useWithdrawLeaving(company: number) {
  return useLeavingWrite(company, (id: number) => api<LeavingState>(`${leaving(company)}/${id}/withdraw/`, { method: "POST" }));
}

/** My answers before I go (optional; I can change them until I leave). */
export function useExitAnswers(company: number) {
  return useLeavingWrite(company, ({ id, ...body }: { id: number; reason: ExitReason; better: string; recommend: Recommend | "" }) =>
    api<LeavingState>(`${leaving(company)}/${id}/exit/`, { json: body }),
  );
}

/** My job here: now, the changes to come and those that took effect. */
export function useCareer(company: number) {
  return useQuery({ queryKey: leavingKeys.career(company), queryFn: () => api<MyCareer>(`/companies/${company}/lifecycle/career/`), staleTime: 60_000 });
}
