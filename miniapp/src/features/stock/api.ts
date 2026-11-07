/**
 * The pharmacist's stock endpoints (`/companies/<id>/stock/…`, backend/apps/inventory/api.py)
 * as react-query hooks. The shapes are written by hand from the serializers there
 * (`AppSettingsSerializer`, `LookupRowSerializer`, `AppBatchSerializer`, …) until the lead
 * regenerates the schema. Quantities are parts as strings ("7.000"), money is a string in the
 * company's base currency, days are YYYY-MM-DD in company time. Costs never reach the app.
 *
 * Fields marked "not served yet" are ones the screens need and the API doesn't send today (the
 * hand-off names them); every screen works without them and shows them once they come.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api, apiForm, ApiError } from "../../api/client";
import { downscale } from "../../lib/image";
import { type Mark, type Marks, readMarks, writeMarks } from "./marks";

// — shapes —

export type Ref = { id: number; name: string };
export type BranchRef = { id: number; name: string; code: string };
export type PersonRef = { id: number; name: string; photo_url: string | null };

export type StorageKind = "room" | "cool" | "cold" | "frozen";
export type ControlClass = "none" | "narcotic" | "psychotropic" | "precursor" | "strong";
export type BatchStatus = "sellable" | "quarantine" | "recalled";

/** GET stock/settings/: what the company allows in the app. */
export interface StockSettings {
  camera_scanning: boolean;
  show_other_branches: boolean;
  rx_log: boolean;
  fefo_strict: boolean;
  /** Not served yet: the company's expiry warning steps in days ([90, 60, 30] by default). */
  expiry_steps?: number[];
}

/** Parts of an item at one of the company's other pharmacies. */
export interface Elsewhere {
  branch_id: number;
  branch: string;
  quantity: string;
}

/** A row of GET stock/lookup/?q= (and the product of GET stock/products/{id}/). */
export interface LookupRow {
  id: number;
  name: string;
  trade_name: string;
  inn: string;
  barcode: string;
  rx_required: boolean;
  control_class: ControlClass;
  storage: StorageKind;
  units_per_pack: number;
  part_label: string;
  /** Per pack. */
  sale_price: string;
  /** Per part. */
  part_price: string;
  /** Parts at my pharmacies; null for an item whose stock isn't kept. */
  quantity: string | null;
  /** At the company's other pharmacies (empty when the company doesn't show them). */
  elsewhere: Elsewhere[];
  /** Not served yet. */
  dosage_form?: string;
  /** Not served yet. */
  strength?: string;
  /** Not served yet: the earliest expiry of what I have. */
  nearest_expiry?: string | null;
}

/** A batch's stock at one pharmacy (GET stock/expiry/, and the batches of a product). */
export interface AppBatch {
  /** The stock row itself: what POST stock/batches/{id}/expiry-action/ names. */
  id: number;
  batch_id: number;
  branch_id: number;
  branch: string;
  series: string;
  expires_on: string;
  days_left: number;
  expired: boolean;
  status: BatchStatus;
  quantity: string;
  retail_price: string;
  part_price: string;
  /** Not served yet by stock/expiry/: the item the batch is of. */
  product?: Ref;
  /** Not served yet by stock/expiry/. */
  units_per_pack?: number;
  /** Not served yet by stock/expiry/. */
  part_label?: string;
}

export interface Analog {
  id: number;
  name: string;
  trade_name: string;
  inn: string;
  dosage_form: string;
  strength: string;
  manufacturer: string;
  /** Sent from J1's 1a52517 on (absent before). */
  units_per_pack?: number;
  /** Sent from J1's 1a52517 on (absent before). */
  part_label?: string;
  rx_required: boolean;
  sale_price: string;
  /** Parts at my pharmacies. */
  quantity: string;
}

/** GET stock/products/{id}/. */
export interface ProductDetail {
  product: LookupRow;
  batches: AppBatch[];
  analogs: Analog[];
}

export type WriteOffReason = "expired" | "damaged" | "recall" | "quality" | "shortage" | "internal_use" | "other";

export interface ExpiryResult {
  action: "on_shelf" | "propose_writeoff";
  writeoff_id: number | null;
}

export type TransferStatus = "draft" | "sent" | "received" | "disputed" | "void";

export interface Transfer {
  id: number;
  number: string;
  status: TransferStatus;
  from_branch: BranchRef;
  to_branch: BranchRef;
  note: string;
  lines_count: number;
  created_at: string;
  sent_at: string | null;
  sent_by: PersonRef | null;
  received_at: string | null;
  received_by: PersonRef | null;
  resolution: string;
  resolved_at: string | null;
  void_reason: string;
}

export interface TransferLine {
  id: number;
  product: Ref;
  units_per_pack: number;
  batch_id: number | null;
  series: string | null;
  expires_on: string | null;
  /** Parts. */
  quantity_sent: string;
  quantity_received: string | null;
}

/** GET stock/transfers/incoming/ rows and the answer of POST …/receive/. */
export interface IncomingTransfer {
  transfer: Transfer;
  lines: TransferLine[];
}

export type MissingStatus = "open" | "ordered" | "fulfilled" | "cancelled";

/** The answer of POST stock/defektura/. */
export interface Defektura {
  id: number;
  branch_ref: BranchRef;
  product_ref: Ref | null;
  name: string;
  packs: string;
  source: "counter" | "mandatory";
  status: MissingStatus;
  customer_phone: string;
  requested_at: string;
  requested_by: PersonRef | null;
}

export type DefekturaInput = { product?: number | null; name?: string; packs?: string; customer_phone?: string };

export type CountKind = "full" | "partial" | "handover";
export type CountStatus = "open" | "submitted" | "applied";

/** A line as a counter sees it: never the expected quantity. */
export interface CountLine {
  id: number;
  product: Ref;
  units_per_pack: number;
  part_label: string;
  batch_id: number | null;
  series: string;
  expires_on: string | null;
  /** Parts, or null while not counted. */
  counted: string | null;
}

/** GET/PATCH stock/counts/{id}/lines/. */
export interface Count {
  id: number;
  kind: CountKind;
  status: CountStatus;
  branch: BranchRef;
  lines: CountLine[];
}

/** Not served yet: GET stock/counts/ (the counts open at my pharmacies). */
export interface CountBrief {
  id: number;
  kind: CountKind;
  status: CountStatus;
  branch: BranchRef;
  lines_count: number;
  counted_count: number;
  created_at: string;
}

export type ReceiptStatus = "draft" | "submitted" | "posted" | "void";

export const RECEIPT_WARNINGS = [
  "short_shelf_life",
  "cost_jump",
  "recalled_series",
  "over_price_cap",
  "registration_expired",
  "rx_flag_mismatch",
  "not_official_dealer",
  "over_month_need",
  "not_licensed_branch",
] as const;
export type ReceiptWarning = (typeof RECEIPT_WARNINGS)[number];

export interface ReceiptLine {
  id: number;
  product: Ref;
  units_per_pack: number;
  series: string;
  expires_on: string;
  packs: string;
  /** Parts (packs × parts in a pack). */
  quantity: string;
  /** As the server computes them (`ReceiptWarning` codes; an unknown one is shown as it is). */
  warnings: string[];
}

/** GET stock/receipts/ rows and every receipt answer. */
export interface Receipt {
  id: number;
  status: ReceiptStatus;
  branch: BranchRef;
  supplier: Ref;
  supplier_invoice_number: string;
  supplier_invoice_date: string;
  lines: ReceiptLine[];
  created_at: string;
}

export type ReceiptInput = {
  supplier: number;
  supplier_invoice_number: string;
  supplier_invoice_date: string;
  file?: File | null;
  branch?: number | null;
};

export type LineInput = {
  product: number;
  series: string;
  expires_on: string;
  /** Packs as a decimal string. */
  packs: string;
  /** Per pack, as the nakladnoy charges it. */
  unit_cost?: string;
};

export type RxKind = "regular" | "benefit" | "narcotic" | "psychotropic" | "listed";
export const RX_KINDS: readonly RxKind[] = ["regular", "benefit", "narcotic", "psychotropic", "listed"];

export type RxInput = {
  product: number;
  /** Parts. */
  quantity: string;
  prescription_number?: string;
  prescribed_on?: string | null;
  prescriber?: string;
  facility?: string;
  rx_kind?: RxKind;
  status?: "dispensed" | "invalid";
  invalid_reason?: string;
  e_prescription_id?: string;
  photo?: File | null;
};

/** The answer of POST stock/rx/. */
export interface RxRecord {
  id: number;
  branch: BranchRef;
  product: Ref;
  series: string | null;
  quantity: string;
  prescription_number: string;
  prescribed_on: string | null;
  prescriber: string;
  facility: string;
  rx_kind: RxKind;
  status: "dispensed" | "invalid";
  invalid_reason: string;
  facility_notified_at: string | null;
  e_prescription_id: string;
  keep_until: string;
  recorded_at: string;
  recorded_by: PersonRef | null;
  /** "no_e_prescription", "past_validity". */
  flags: string[];
}

// — keys —

export const stockKeys = {
  all: (company: number) => ["stock", company] as const,
  settings: (company: number) => ["stock", company, "settings"] as const,
  lookup: (company: number, q: string) => ["stock", company, "lookup", q] as const,
  product: (company: number, id: number) => ["stock", company, "product", id] as const,
  expiry: (company: number, within: number) => ["stock", company, "expiry", within] as const,
  marks: (company: number) => ["stock", company, "marks"] as const,
  incoming: (company: number) => ["stock", company, "incoming"] as const,
  counts: (company: number) => ["stock", company, "counts"] as const,
  count: (company: number, id: number) => ["stock", company, "count", id] as const,
  receipts: (company: number) => ["stock", company, "receipts"] as const,
  suppliers: (company: number) => ["stock", company, "suppliers"] as const,
};

const base = (company: number) => `/companies/${company}/stock`;

/**
 * A list the screens need that the server doesn't serve yet: it answers 404 (or 405), or
 * something that isn't a list. Null then.
 */
async function listUnlessMissing<T>(load: () => Promise<T[]>): Promise<T[] | null> {
  try {
    const rows = await load();
    return Array.isArray(rows) ? rows : null;
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 405)) return null;
    throw error;
  }
}

/** A list endpoint's rows; anything else (a proxy's error page) reads as none, never a crash. */
async function listOf<T>(path: string): Promise<T[]> {
  const rows = await api<T[]>(path);
  return Array.isArray(rows) ? rows : [];
}

/** Anything on screen that came from these endpoints is fetched again. */
const refreshAll = (client: QueryClient, company: number) => client.invalidateQueries({ queryKey: stockKeys.all(company) });

// — reading —

export function useStockSettings(company: number, enabled = true) {
  return useQuery({
    queryKey: stockKeys.settings(company),
    queryFn: () => api<StockSettings>(`${base(company)}/settings/`),
    staleTime: 5 * 60_000,
    enabled,
  });
}

/** Typed (or scanned) search; the server answers nothing for under two characters. */
export function useLookup(company: number, q: string) {
  const term = q.trim();
  return useQuery({
    queryKey: stockKeys.lookup(company, term),
    queryFn: () => listOf<LookupRow>(`${base(company)}/lookup/?${new URLSearchParams({ q: term })}`),
    enabled: term.length >= 2,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

export function useProduct(company: number, id: number) {
  return useQuery({
    queryKey: stockKeys.product(company, id),
    queryFn: () => api<ProductDetail>(`${base(company)}/products/${id}/`),
    staleTime: 30_000,
    enabled: id > 0,
  });
}

/** My pharmacy's batches that expire within `within` days, the expired ones included. */
export function useExpiry(company: number, within: number, enabled = true) {
  return useQuery({
    queryKey: stockKeys.expiry(company, within),
    queryFn: () => listOf<AppBatch>(`${base(company)}/expiry/?within=${within}`),
    staleTime: 60_000,
    enabled,
  });
}

/** What this phone marked on the expiry check (the server keeps it in the audit log only). */
export function useMarks(company: number) {
  // There from the first frame, so a marked row never flashes its buttons.
  return useQuery({ queryKey: stockKeys.marks(company), queryFn: () => readMarks(company), initialData: () => readMarks(company), staleTime: Infinity });
}

export function useIncoming(company: number, enabled = true) {
  return useQuery({
    queryKey: stockKeys.incoming(company),
    queryFn: () => listOf<IncomingTransfer>(`${base(company)}/transfers/incoming/`),
    staleTime: 60_000,
    enabled,
  });
}

/** The counts open at my pharmacies; null while the server has no list for the app yet. */
export function useOpenCounts(company: number, enabled = true) {
  return useQuery({
    queryKey: stockKeys.counts(company),
    queryFn: () => listUnlessMissing(() => api<CountBrief[]>(`${base(company)}/counts/`)),
    staleTime: 60_000,
    enabled,
  });
}

export function useCount(company: number, id: number) {
  return useQuery({
    queryKey: stockKeys.count(company, id),
    queryFn: async () => blind(await api<Count>(`${base(company)}/counts/${id}/lines/`)),
    enabled: id > 0,
  });
}

/** My pharmacies' receipt drafts and those waiting for posting. */
export function useReceipts(company: number, enabled = true) {
  return useQuery({
    queryKey: stockKeys.receipts(company),
    queryFn: () => listOf<Receipt>(`${base(company)}/receipts/`),
    staleTime: 30_000,
    enabled,
  });
}

/**
 * The distributors to receive from; null while the server has no list for the app yet (then the
 * ones on my recent receipts are offered).
 */
export function useSuppliers(company: number, enabled = true) {
  return useQuery({
    queryKey: stockKeys.suppliers(company),
    queryFn: () => listUnlessMissing(() => api<Ref[]>(`${base(company)}/suppliers/`)),
    staleTime: 5 * 60_000,
    enabled,
  });
}

// — the expiry check —

function setMark(client: QueryClient, company: number, id: number, change: Mark | null): Marks {
  const before = client.getQueryData<Marks>(stockKeys.marks(company)) ?? readMarks(company);
  const next = { ...before };
  if (change) next[id] = { ...next[id], ...change };
  else delete next[id];
  client.setQueryData(stockKeys.marks(company), next);
  return before;
}

/**
 * "On the near-expiry shelf": shown at once, and taken back with the server's reason if it
 * refuses. `onFailed` hears the error even when the screen is gone.
 */
export function useShelfMark(company: number, onFailed: (error: unknown) => void) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id }: { id: number; day: string }) =>
      api<ExpiryResult>(`${base(company)}/batches/${id}/expiry-action/`, { method: "POST", json: { action: "on_shelf" } }),
    onMutate: ({ id, day }) => ({ before: setMark(client, company, id, { shelf: day }) }),
    onError: (error, _input, context) => {
      if (context) client.setQueryData(stockKeys.marks(company), context.before);
      onFailed(error);
    },
    onSuccess: () => writeMarks(company, client.getQueryData<Marks>(stockKeys.marks(company)) ?? {}),
  });
}

export type WriteOffInput = { id: number; reason?: WriteOffReason; photo?: File | null };

/**
 * "Propose write-off" (all of the series here, with a photo): the row says so at once, and goes
 * back with the server's reason if it refuses. The head approves it in the dashboard.
 */
export function useProposeWriteOff(company: number, { onFailed, onDone }: { onFailed: (error: unknown) => void; onDone?: () => void }) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, reason, photo }: WriteOffInput) => {
      const path = `${base(company)}/batches/${id}/expiry-action/`;
      if (photo) return apiForm<ExpiryResult>(path, { action: "propose_writeoff", reason, photo: await downscale(photo) });
      return api<ExpiryResult>(path, { method: "POST", json: { action: "propose_writeoff", ...(reason ? { reason } : {}) } });
    },
    onMutate: ({ id }) => ({ before: setMark(client, company, id, { writeoff: "pending" }) }),
    onError: (error, _input, context) => {
      if (context) client.setQueryData(stockKeys.marks(company), context.before);
      onFailed(error);
    },
    onSuccess: (result, { id }) => {
      setMark(client, company, id, { writeoff: result.writeoff_id ?? "pending" });
      writeMarks(company, client.getQueryData<Marks>(stockKeys.marks(company)) ?? {});
      onDone?.();
    },
  });
}

// — transfers, defektura, counts —

/** What arrived, per line in parts (everything as sent when `lines` is left out). */
export function useReceiveTransfer(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, lines }: { id: number; lines?: { line: number; quantity: string }[] }) =>
      api<IncomingTransfer>(`${base(company)}/transfers/${id}/receive/`, { method: "POST", json: lines ? { lines } : {} }),
    onSuccess: (done) => {
      client.setQueryData<IncomingTransfer[]>(stockKeys.incoming(company), (rows) => rows?.filter((row) => row.transfer.id !== done.transfer.id));
      void refreshAll(client, company);
    },
  });
}

export function useAddDefektura(company: number) {
  return useMutation({
    mutationFn: (input: DefekturaInput) => api<Defektura>(`${base(company)}/defektura/`, { method: "POST", json: input }),
  });
}

/**
 * Save what was counted on one line: shown at once, back to what it was if the server refuses.
 * The answer is the whole count again (never with the expected quantity).
 */
export function useSaveCounted(company: number, id: number, onFailed: (error: unknown) => void) {
  const client = useQueryClient();
  const key = stockKeys.count(company, id);
  return useMutation({
    mutationFn: ({ line, counted }: { line: number; counted: string | null }) =>
      api<Count>(`${base(company)}/counts/${id}/lines/`, { method: "PATCH", json: { lines: [{ line, counted }] } }),
    onMutate: async ({ line, counted }) => {
      await client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<Count>(key);
      if (before) client.setQueryData<Count>(key, { ...before, lines: before.lines.map((row) => (row.id === line ? { ...row, counted } : row)) });
      return { before };
    },
    onError: (error, _input, context) => {
      if (context?.before) client.setQueryData(key, context.before);
      onFailed(error);
    },
    onSuccess: (count) => client.setQueryData(key, blind(count)),
  });
}

/** Whatever the server sends, a counter's screen never holds the expected quantity. */
export function blind(count: Count): Count {
  return {
    ...count,
    lines: count.lines.map(({ id, product, units_per_pack, part_label, batch_id, series, expires_on, counted }) => ({
      id,
      product,
      units_per_pack,
      part_label,
      batch_id,
      series,
      expires_on,
      counted,
    })),
  };
}

// — receiving —

export function useCreateReceipt(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, branch, ...fields }: ReceiptInput) =>
      apiForm<Receipt>(`${base(company)}/receipts/`, {
        ...fields,
        branch: branch ?? undefined,
        file: file ? (file.type.startsWith("image/") ? await downscale(file) : file) : undefined,
      }),
    onSuccess: (receipt) => {
      client.setQueryData<Receipt[]>(stockKeys.receipts(company), (rows) => [receipt, ...(rows ?? []).filter((row) => row.id !== receipt.id)]);
    },
  });
}

function keepReceipt(client: QueryClient, company: number, receipt: Receipt) {
  client.setQueryData<Receipt[]>(stockKeys.receipts(company), (rows) => (rows ? rows.map((row) => (row.id === receipt.id ? receipt : row)) : [receipt]));
}

export function useAddLine(company: number, receipt: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (line: LineInput) => api<Receipt>(`${base(company)}/receipts/${receipt}/lines/`, { method: "POST", json: line }),
    onSuccess: (answer) => keepReceipt(client, company, answer),
  });
}

export function useUpdateLine(company: number, receipt: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ line, ...changes }: Partial<LineInput> & { line: number }) =>
      api<Receipt>(`${base(company)}/receipts/${receipt}/lines/${line}/`, { method: "PATCH", json: changes }),
    onSuccess: (answer) => keepReceipt(client, company, answer),
  });
}

export function useRemoveLine(company: number, receipt: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (line: number) => api<Receipt>(`${base(company)}/receipts/${receipt}/lines/${line}/`, { method: "DELETE" }),
    onSuccess: (answer) => keepReceipt(client, company, answer),
  });
}

export function useSubmitReceipt(company: number, receipt: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<Receipt>(`${base(company)}/receipts/${receipt}/submit/`, { method: "POST" }),
    onSuccess: (answer) => keepReceipt(client, company, answer),
  });
}

// — prescriptions —

export function useRecordRx(company: number) {
  return useMutation({
    mutationFn: async ({ photo, prescribed_on, ...fields }: RxInput) =>
      apiForm<RxRecord>(`${base(company)}/rx/`, {
        ...fields,
        prescribed_on: prescribed_on || undefined,
        photo: photo ? await downscale(photo) : undefined,
      }),
  });
}
