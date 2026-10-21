/**
 * The Kassa endpoints (`apps/sales/api.py`, PLAN-OWNER §4.8 E rows), typed by hand until the
 * lead regenerates `schema.d.ts`. Money is a decimal string; moments are ISO 8601. While the
 * blind count is on, the server never sends a cashier the expected cash or the difference of a
 * shift before a manager checked it: `expected_cash` and `difference` stay null.
 */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, apiForm, type FormFields } from "../../api/client";
import type { Page } from "../../api/types";
import type { NoteCounts } from "../../ui";

export type Ref = { id: number; name: string };
export type BranchRef = { id: number; name: string; code: string };
export type MethodKind = "cash" | "card" | "qr" | "transfer" | "credit" | "installment" | "other";
export type ShiftStatus = "open" | "closed" | "verified" | "disputed";
export type MovementKind = "payout" | "deposit" | "handover" | "to_safe" | "from_safe" | "to_bank";
export type AppMovementKind = "payout" | "handover" | "to_safe" | "from_safe";
export type MovementStatus = "pending" | "declined" | "done" | "void";
export type SalesMode = "shift_totals" | "receipts" | "invoices";

export type Method = { id: number; name: string; kind: MethodKind };

/** What a till takes at the counter: sales on credit and in instalments are recorded elsewhere. */
export function tillMethods(methods: readonly Method[]): Method[] {
  return methods.filter((method) => method.kind !== "credit" && method.kind !== "installment");
}

/** A row of my shifts (`shifts/`, `recent`). */
export type Shift = {
  id: number;
  code: string;
  status: ShiftStatus;
  branch: BranchRef;
  register: Ref;
  business_day: string;
  opened_at: string;
  closed_at: string | null;
  opening_float: string;
  net: string;
  receipts: number;
  counted_cash: string | null;
  /** Only once a manager checked the shift (or right after closing when the blind count is off). */
  expected_cash: string | null;
  difference: string | null;
  verified_at: string | null;
  verified_by: Ref | null;
  /** The manager's note on a checked or questioned shift. */
  note: string;
  forced: boolean;
};

export type Movement = {
  id: number;
  kind: MovementKind;
  status: MovementStatus;
  amount: string;
  currency: string;
  branch: BranchRef;
  register: Ref;
  shift: { id: number; code: string } | null;
  receiver: Ref | null;
  to_account: Ref | null;
  category: Ref | null;
  reason: string;
  photo: string | null;
  created_by: Ref;
  created_at: string;
  confirmed_at: string | null;
  confirmed_by: Ref | null;
  declined_at: string | null;
  decline_reason: string;
  voided_at: string | null;
  void_reason: string;
};

export type Entry = {
  id: number;
  kind: "sale" | "refund";
  total: string;
  number: string;
  sold_at: string;
  voided_at: string | null;
  methods: { id: number; name: string; amount: string }[];
};

export type Totals = { sales: string; refunds: string; receipts: number };

export type ShiftDetail = Shift & {
  payments: { method: Method; sales: string; refunds: string; receipts: number }[];
  opening_count: Record<string, number>;
  closing_count: Record<string, number>;
  z_number: string;
  cashier_note: string;
  movements: Movement[];
  moved: Partial<Record<MovementKind, string>>;
  /** Receipts mode: what the single receipts add up to, per method id. */
  receipts_recorded: Record<string, Totals>;
  entries: Entry[];
  photos: { z_photo: string | null; terminal_photo: string | null };
};

export type Handover = {
  id: number;
  amount: string;
  currency: string;
  from: Ref;
  branch: BranchRef;
  register: Ref;
  reason: string;
  created_at: string;
};

export type Till = { id: number; name: string; branch: BranchRef; busy: { code: string; cashier: string } | null };

/** `shifts/current/`: everything the Kassa screen needs in one call. */
export type Kassa = {
  shift: ShiftDetail | null;
  settings: { mode: SalesMode; blind_cash_count: boolean; require_z_photo: boolean; require_terminal_photo: boolean; currency: string };
  registers: Till[];
  methods: Method[];
  receivers: { id: number; name: string; role: string }[];
  categories: { id: number; name: string; code: string }[];
  pending_handovers: Handover[];
  recent: Shift[];
};

export type PaymentLine = { method_id: number; sales: string; refunds: string; receipts?: number };

export const kassaKeys = {
  all: (company: number) => ["kassa", company] as const,
  current: (company: number) => ["kassa", company, "current"] as const,
  shift: (company: number, id: number) => ["kassa", company, "shift", id] as const,
  history: (company: number) => ["kassa", company, "history"] as const,
  handovers: (company: number) => ["kassa", company, "handovers"] as const,
};

const base = (company: number) => `/companies/${company}/sales`;

/** No access or the module is off: retrying won't help, and the screen says so. */
export const isDenied = (error: unknown) => error instanceof ApiError && (error.status === 403 || error.status === 404);

/** A lost connection or a server hiccup, as opposed to an answer saying no. */
export function isNetworkError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  return error.status >= 500 || error.status === 408 || error.status === 429;
}

const retry = (count: number, error: unknown) => !isDenied(error) && count < 2;

export function useKassa(company: number, enabled = true) {
  return useQuery({
    queryKey: kassaKeys.current(company),
    queryFn: () => api<Kassa>(`${base(company)}/shifts/current/`),
    enabled,
    retry,
  });
}

export function useShift(company: number, id: number) {
  return useQuery({
    queryKey: kassaKeys.shift(company, id),
    queryFn: () => api<ShiftDetail>(`${base(company)}/shifts/${id}/`),
    retry,
  });
}

export function useHistory(company: number) {
  return useInfiniteQuery({
    queryKey: kassaKeys.history(company),
    queryFn: ({ pageParam }) => api<Page<Shift>>(`${base(company)}/shifts/?page=${pageParam}&page_size=20`),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (last.next ? pages.length + 1 : undefined),
    retry,
  });
}

/** Cash handed to me that I haven't answered (the "Received?" card). Needs no permission. */
export function useHandovers(company: number, enabled = true) {
  return useQuery({
    queryKey: kassaKeys.handovers(company),
    queryFn: () => api<{ results: Handover[] }>(`${base(company)}/handovers/pending/`).then((page) => page.results),
    enabled,
    retry,
    refetchInterval: 60_000,
  });
}

function useKassaMutation<V, R>(company: number, run: (variables: V) => Promise<R>, after?: (result: R) => void) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: (result) => {
      after?.(result);
      void client.invalidateQueries({ queryKey: kassaKeys.all(company) });
    },
  });
}

export type OpenInput = { register_id: number; opening_count?: NoteCounts; opening_float: string };

export function useOpenShift(company: number) {
  const client = useQueryClient();
  return useKassaMutation(
    company,
    (input: OpenInput) => api<ShiftDetail>(`${base(company)}/shifts/`, { method: "POST", json: input }),
    // Show the open shift at once instead of waiting for the refetch.
    (shift) => client.setQueryData<Kassa>(kassaKeys.current(company), (old) => (old ? { ...old, shift } : old)),
  );
}

export type MovementInput = {
  kind: AppMovementKind;
  amount: string;
  receiver_id?: number | null;
  category_id?: number | null;
  reason?: string;
  photo?: File | null;
};

export function useMovement(company: number, shiftId: number) {
  return useKassaMutation(company, (input: MovementInput) =>
    apiForm<Movement>(`${base(company)}/shifts/${shiftId}/movements/`, input as FormFields),
  );
}

export type SaleInput = { kind: "sale" | "refund"; payments: { method_id: number; amount: string }[]; number?: string };

export function useSale(company: number) {
  return useKassaMutation(company, (input: SaleInput) =>
    api<{ id: number; total: string; kind: string; sold_at: string }>(`${base(company)}/entries/`, { method: "POST", json: input }),
  );
}

export function useVoidSale(company: number) {
  return useKassaMutation(company, ({ id, reason }: { id: number; reason: string }) =>
    api<{ id: number }>(`${base(company)}/entries/${id}/void/`, { method: "POST", json: { reason } }),
  );
}

export function useAnswerHandover(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, answer, reason }: { id: number; answer: "confirm" | "decline"; reason?: string }) =>
      api<{ id: number; status: string }>(`${base(company)}/handovers/${id}/${answer}/`, { method: "POST", json: { reason: reason ?? "" } }),
    // The card goes away at once; a failure brings it back.
    onMutate: async ({ id }) => {
      await client.cancelQueries({ queryKey: kassaKeys.handovers(company) });
      const before = client.getQueryData<Handover[]>(kassaKeys.handovers(company));
      client.setQueryData<Handover[]>(kassaKeys.handovers(company), (old) => old?.filter((row) => row.id !== id));
      return { before };
    },
    onError: (_error, _variables, context) => client.setQueryData(kassaKeys.handovers(company), context?.before),
    onSettled: () => void client.invalidateQueries({ queryKey: kassaKeys.all(company) }),
  });
}

/** The close request: multipart, because the Z-report and the terminal slip travel with it. */
export type CloseInput = {
  payments: PaymentLine[];
  closing_count?: NoteCounts;
  counted_cash: string;
  receipts?: number | null;
  z_number?: string;
  note?: string;
  z_photo?: File | null;
  terminal_photo?: File | null;
};

export function closeShift(company: number, shiftId: number, input: CloseInput): Promise<ShiftDetail> {
  const { payments, closing_count, ...rest } = input;
  return apiForm<ShiftDetail>(`${base(company)}/shifts/${shiftId}/close/`, {
    ...rest,
    payments: JSON.stringify(payments),
    closing_count: closing_count && Object.keys(closing_count).length ? JSON.stringify(closing_count) : undefined,
  });
}

export function fetchShift(company: number, id: number): Promise<ShiftDetail> {
  return api<ShiftDetail>(`${base(company)}/shifts/${id}/`);
}
