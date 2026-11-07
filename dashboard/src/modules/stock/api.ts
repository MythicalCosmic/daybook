/**
 * The stock endpoints (`/api/v1/owner/companies/{cid}/stock/…`) as typed functions, and the
 * vue-query helpers the pages use. Keys start with `[companyId, "stock"]`: the module lists the
 * `inventory` pulse key in `invalidates` (index.ts), so a change anywhere in stock refreshes every
 * query here, and switching company never shows another's stock.
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, type Query } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import { useCompanyId } from "@/stores/company";

import type {
  Analog,
  Batch,
  Category,
  ControlledRegister,
  Count,
  CountDetail,
  CountKind,
  DestroyedInput,
  ExpiryBoard,
  FileLink,
  ImportResult,
  Level,
  Manufacturer,
  MissingRequest,
  MissingRequestInput,
  Movement,
  PricingRule,
  PricingRuleInput,
  ProductCode,
  ProductDetail,
  ProductInput,
  ProductPage,
  Recall,
  RecallInput,
  Receipt,
  ReceiptDetail,
  ReceiptInput,
  ReceiptLineInput,
  RequestStatus,
  Resolution,
  LineImportResult,
  RecallImportResult,
  RxJournal,
  StockBranch,
  StockSettings,
  Summary,
  Supplier,
  Transfer,
  TransferDetail,
  TransferInput,
  WriteOff,
  WriteOffDetail,
  WriteOffFileKind,
  WriteOffInput,
} from "./types";

export const MODULE = "stock";

const path = (cid: number, rest: string) => ownerPath(cid, `stock/${rest}`);

export const stockApi = {
  settings: (cid: number) => http.get<StockSettings>(path(cid, "settings/")),
  updateSettings: (cid: number, input: Partial<StockSettings>) => http.patch<StockSettings>(path(cid, "settings/"), input),
  summary: (cid: number, params: Query = {}) => http.get<Summary>(path(cid, "summary/"), params),
  branches: (cid: number) => http.get<StockBranch[]>(path(cid, "branches/")),
  priceTags: (cid: number, input: { branch: number; products?: number[]; changed_since?: string }) =>
    http.post<FileLink>(path(cid, "price-tags/"), input),
  importLines: (cid: number, id: number, file: File, options: { dryRun: boolean; mapping?: Record<string, string> | null }) => {
    const form = new FormData();
    form.append("file", file);
    form.append("dry_run", options.dryRun ? "true" : "false");
    if (options.mapping) form.append("mapping", JSON.stringify(options.mapping));
    return http.form<LineImportResult>(path(cid, `receipts/${id}/lines/import/`), form);
  },

  products: (cid: number, params: Query = {}, signal?: AbortSignal) => http.get<ProductPage>(path(cid, "products/"), params, { signal }),
  product: (cid: number, id: number) => http.get<ProductDetail>(path(cid, `products/${id}/`)),
  createProduct: (cid: number, input: ProductInput) => http.post<ProductDetail["product"]>(path(cid, "products/"), input),
  updateProduct: (cid: number, id: number, input: ProductInput) => http.patch<ProductDetail>(path(cid, `products/${id}/`), input),
  analogs: (cid: number, id: number) => http.get<Analog[]>(path(cid, `products/${id}/analogs/`)),
  productBatches: (cid: number, id: number, params: Query = {}) => http.get<Batch[]>(path(cid, `products/${id}/batches/`), params),
  productMovements: (cid: number, id: number, params: Query = {}) => http.get<Movement[]>(path(cid, `products/${id}/movements/`), params),
  addCode: (cid: number, id: number, input: { kind: ProductCode["kind"]; code: string; supplier_id?: number | null }) =>
    http.post<ProductCode[]>(path(cid, `products/${id}/codes/`), input),
  removeCode: (cid: number, id: number, codeId: number) => http.delete(path(cid, `products/${id}/codes/${codeId}/`)),
  merge: (cid: number, id: number, other: number) => http.post<ProductDetail["product"]>(path(cid, `products/${id}/merge/`), { other }),
  importProducts: (cid: number, file: File, options: { dryRun: boolean; mapping?: Record<string, string> | null }) => {
    const form = new FormData();
    form.append("file", file);
    form.append("dry_run", options.dryRun ? "true" : "false");
    if (options.mapping) form.append("mapping", JSON.stringify(options.mapping));
    return http.form<ImportResult>(path(cid, "products/import/"), form);
  },

  categories: (cid: number) => http.get<Category[]>(path(cid, "categories/")),
  createCategory: (cid: number, input: { name: string; parent?: number | null }) => http.post<Category[]>(path(cid, "categories/"), input),
  manufacturers: (cid: number) => http.get<Manufacturer[]>(path(cid, "manufacturers/")),
  createManufacturer: (cid: number, input: { name: string; country?: string }) => http.post<Manufacturer>(path(cid, "manufacturers/"), input),
  suppliers: (cid: number) => http.get<Supplier[]>(path(cid, "suppliers/")),
  createSupplier: (cid: number, input: Partial<Supplier> & { name: string }) => http.post<Supplier>(path(cid, "suppliers/"), input),
  updateSupplier: (cid: number, id: number, input: Partial<Supplier>) => http.patch<Supplier>(path(cid, `suppliers/${id}/`), input),

  levels: (cid: number, params: Query = {}, signal?: AbortSignal) => http.get<Level[]>(path(cid, "levels/"), params, { signal }),
  setLimits: (cid: number, id: number, input: { min_qty: string | null; max_qty: string | null }) => http.patch<{ min_qty: string | null; max_qty: string | null }>(path(cid, `levels/${id}/`), input),
  batches: (cid: number, params: Query = {}, signal?: AbortSignal) => http.get<Batch[]>(path(cid, "batches/"), params, { signal }),
  quarantine: (cid: number, stockId: number, reason: string) => http.post<Batch>(path(cid, `batches/${stockId}/quarantine/`), { reason }),
  release: (cid: number, stockId: number, reason = "") => http.post<Batch>(path(cid, `batches/${stockId}/release/`), { reason }),
  markdown: (cid: number, stockId: number, price: string) => http.post<Batch>(path(cid, `batches/${stockId}/markdown/`), { price }),
  opening: (
    cid: number,
    input: { branch: number; product: number; series: string; expires_on: string; made_on?: string | null; packs: string; parts?: string; unit_cost: string; retail_price?: string | null },
  ) => http.post<Batch>(path(cid, "batches/opening/"), input),
  expiry: (cid: number, params: Query = {}) => http.get<ExpiryBoard>(path(cid, "expiry/"), params),
  movements: (cid: number, params: Query = {}) => http.get<Movement[]>(path(cid, "movements/"), params),

  receipts: (cid: number, params: Query = {}, signal?: AbortSignal) => http.get<Receipt[]>(path(cid, "receipts/"), params, { signal }),
  receipt: (cid: number, id: number) => http.get<ReceiptDetail>(path(cid, `receipts/${id}/`)),
  createReceipt: (cid: number, input: ReceiptInput) => http.post<ReceiptDetail>(path(cid, "receipts/"), input),
  updateReceipt: (cid: number, id: number, input: Partial<ReceiptInput>) => http.patch<ReceiptDetail>(path(cid, `receipts/${id}/`), input),
  addLine: (cid: number, id: number, input: ReceiptLineInput) => http.post<ReceiptDetail>(path(cid, `receipts/${id}/lines/`), input),
  updateLine: (cid: number, id: number, lineId: number, input: Partial<ReceiptLineInput>) => http.patch<ReceiptDetail>(path(cid, `receipts/${id}/lines/${lineId}/`), input),
  removeLine: (cid: number, id: number, lineId: number) => http.delete<ReceiptDetail>(path(cid, `receipts/${id}/lines/${lineId}/`)),
  uploadReceiptFile: (cid: number, id: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return http.form<ReceiptDetail>(path(cid, `receipts/${id}/file/`), form);
  },
  submitReceipt: (cid: number, id: number) => http.post<ReceiptDetail>(path(cid, `receipts/${id}/submit/`), {}),
  postReceipt: (cid: number, id: number) => http.post<ReceiptDetail>(path(cid, `receipts/${id}/post/`), {}),
  voidReceipt: (cid: number, id: number, reason: string) => http.post<ReceiptDetail>(path(cid, `receipts/${id}/void/`), { reason }),

  transfers: (cid: number, params: Query = {}) => http.get<Transfer[]>(path(cid, "transfers/"), params),
  transfer: (cid: number, id: number) => http.get<TransferDetail>(path(cid, `transfers/${id}/`)),
  createTransfer: (cid: number, input: TransferInput) => http.post<TransferDetail>(path(cid, "transfers/"), input),
  sendTransfer: (cid: number, id: number) => http.post<TransferDetail>(path(cid, `transfers/${id}/send/`), {}),
  receiveTransfer: (cid: number, id: number, lines?: Array<{ line: number; quantity: string }>) =>
    http.post<TransferDetail>(path(cid, `transfers/${id}/receive/`), lines ? { lines } : {}),
  resolveTransfer: (cid: number, id: number, outcome: Resolution, note = "") => http.post<TransferDetail>(path(cid, `transfers/${id}/resolve/`), { outcome, note }),
  voidTransfer: (cid: number, id: number, reason: string) => http.post<TransferDetail>(path(cid, `transfers/${id}/void/`), { reason }),

  writeoffs: (cid: number, params: Query = {}) => http.get<WriteOff[]>(path(cid, "write-offs/"), params),
  writeoff: (cid: number, id: number) => http.get<WriteOffDetail>(path(cid, `write-offs/${id}/`)),
  proposeWriteoff: (cid: number, input: WriteOffInput) => http.post<WriteOffDetail>(path(cid, "write-offs/"), input),
  approveWriteoff: (cid: number, id: number) => http.post<WriteOffDetail>(path(cid, `write-offs/${id}/approve/`), {}),
  voidWriteoff: (cid: number, id: number, reason: string) => http.post<WriteOffDetail>(path(cid, `write-offs/${id}/void/`), { reason }),
  destroyed: (cid: number, id: number, input: DestroyedInput) => http.post<WriteOffDetail>(path(cid, `write-offs/${id}/destroyed/`), input),
  uploadWriteoffFile: (cid: number, id: number, file: File, kind: WriteOffFileKind) => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    return http.form<WriteOffDetail>(path(cid, `write-offs/${id}/files/`), form);
  },
  act: (cid: number, id: number, language?: string) => http.get<FileLink>(path(cid, `write-offs/${id}/act/`), { language }),

  counts: (cid: number, params: Query = {}) => http.get<Count[]>(path(cid, "counts/"), params),
  count: (cid: number, id: number) => http.get<CountDetail>(path(cid, `counts/${id}/`)),
  startCount: (cid: number, input: { branch: number; kind: CountKind; category?: number | null }) => http.post<CountDetail>(path(cid, "counts/"), input),
  countLines: (cid: number, id: number, lines: Array<{ line: number; counted: string | null }>) => http.post<CountDetail>(path(cid, `counts/${id}/lines/`), { lines }),
  found: (cid: number, id: number, input: { product: number; series: string; expires_on: string; counted: string }) => http.post<CountDetail>(path(cid, `counts/${id}/found/`), input),
  submitCount: (cid: number, id: number) => http.post<CountDetail>(path(cid, `counts/${id}/submit/`), {}),
  applyCount: (cid: number, id: number) => http.post<CountDetail>(path(cid, `counts/${id}/apply/`), {}),

  recalls: (cid: number, params: Query = {}) => http.get<Recall[]>(path(cid, "recalls/"), params),
  recall: (cid: number, id: number) => http.get<Recall>(path(cid, `recalls/${id}/`)),
  createRecall: (cid: number, input: RecallInput) => http.post<Recall>(path(cid, "recalls/"), input),
  importRecalls: (cid: number, file: File, options: { dryRun: boolean; source: string; receivedOn: string; mapping?: Record<string, string> | null }) => {
    const form = new FormData();
    form.append("file", file);
    form.append("dry_run", options.dryRun ? "true" : "false");
    form.append("source", options.source);
    form.append("received_on", options.receivedOn);
    if (options.mapping) form.append("mapping", JSON.stringify(options.mapping));
    return http.form<RecallImportResult>(path(cid, "recalls/import/"), form);
  },
  closeRecall: (cid: number, id: number) => http.post<Recall>(path(cid, `recalls/${id}/close/`), {}),

  pricingRules: (cid: number) => http.get<PricingRule[]>(path(cid, "pricing-rules/")),
  createPricingRule: (cid: number, input: PricingRuleInput) => http.post<PricingRule[]>(path(cid, "pricing-rules/"), input),
  updatePricingRule: (cid: number, id: number, input: PricingRuleInput) => http.patch<PricingRule[]>(path(cid, `pricing-rules/${id}/`), input),
  deletePricingRule: (cid: number, id: number) => http.delete(path(cid, `pricing-rules/${id}/`)),

  requests: (cid: number, params: Query = {}) => http.get<MissingRequest[]>(path(cid, "defektura/"), params),
  addRequest: (cid: number, input: MissingRequestInput) => http.post<MissingRequest>(path(cid, "defektura/"), input),
  setRequestStatus: (cid: number, id: number, status: RequestStatus) => http.patch<MissingRequest>(path(cid, `defektura/${id}/`), { status }),

  controlled: (cid: number, params: Query) => http.get<ControlledRegister>(path(cid, "journals/controlled/"), params),
  controlledPdf: (cid: number, params: Query) => http.get<FileLink>(path(cid, "journals/controlled/pdf/"), params),
  closeMonth: (cid: number, input: { branch: number; month: string; counted?: Array<{ product: number; counted: string }>; note?: string }) =>
    http.post<ControlledRegister>(path(cid, "journals/controlled/close/"), input),
  reported: (cid: number, periodId: number, reportedOn: string) => http.post<unknown>(path(cid, `journals/controlled/${periodId}/reported/`), { reported_on: reportedOn }),
  rxJournal: (cid: number, params: Query) => http.get<RxJournal>(path(cid, "journals/rx/"), params),
  rxPdf: (cid: number, params: Query) => http.get<FileLink>(path(cid, "journals/rx/pdf/"), params),
};

export const stockKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  of: (cid: number, resource: string, params: Record<string, unknown> = {}) => qk(cid, MODULE, resource, params),
};

function useResource<T>(
  resource: string,
  params: MaybeRefOrGetter<Record<string, unknown>>,
  fetcher: (cid: number, params: Record<string, unknown>, signal: AbortSignal) => Promise<T>,
  options: { enabled?: MaybeRefOrGetter<boolean>; keepPrevious?: boolean; staleTime?: number } = {},
) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => stockKeys.of(cid.value, resource, toValue(params))),
    queryFn: ({ signal }) => fetcher(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && (options.enabled === undefined || toValue(options.enabled))),
    placeholderData: options.keepPrevious ? keepPreviousData : undefined,
    staleTime: options.staleTime ?? 20_000,
  });
}

const asQuery = (params: Record<string, unknown>) => params as Query;

export const useStockSettings = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("settings", {}, (cid) => stockApi.settings(cid), { enabled, staleTime: 60_000 });
export const useStockBranches = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("branches", {}, (cid) => stockApi.branches(cid), { enabled, staleTime: 300_000 });
export const useSummary = (params: MaybeRefOrGetter<Query>) => useResource("summary", () => ({ ...toValue(params) }), (cid, p) => stockApi.summary(cid, asQuery(p)), { keepPrevious: true });
export const useProducts = (params: MaybeRefOrGetter<Query>) =>
  useResource("products", () => ({ ...toValue(params) }), (cid, p, signal) => stockApi.products(cid, asQuery(p), signal), { keepPrevious: true });
export const useProduct = (id: MaybeRefOrGetter<number>) => useResource("product", () => ({ id: toValue(id) }), (cid, p) => stockApi.product(cid, Number(p.id)), { enabled: () => toValue(id) > 0 });
export const useProductBatches = (id: MaybeRefOrGetter<number>) =>
  useResource("product-batches", () => ({ id: toValue(id) }), (cid, p) => stockApi.productBatches(cid, Number(p.id)), { enabled: () => toValue(id) > 0 });
export const useProductMovements = (id: MaybeRefOrGetter<number>, enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource("product-movements", () => ({ id: toValue(id) }), (cid, p) => stockApi.productMovements(cid, Number(p.id)), { enabled: () => toValue(id) > 0 && toValue(enabled) });
export const useCategories = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("categories", {}, (cid) => stockApi.categories(cid), { enabled, staleTime: 60_000 });
export const useManufacturers = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("manufacturers", {}, (cid) => stockApi.manufacturers(cid), { enabled, staleTime: 60_000 });
export const useSuppliers = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("suppliers", {}, (cid) => stockApi.suppliers(cid), { enabled, staleTime: 60_000 });
export const useLevels = (params: MaybeRefOrGetter<Query>) =>
  useResource("levels", () => ({ ...toValue(params) }), (cid, p, signal) => stockApi.levels(cid, asQuery(p), signal), { keepPrevious: true });
export const useBatches = (params: MaybeRefOrGetter<Query>, enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource("batches", () => ({ ...toValue(params) }), (cid, p, signal) => stockApi.batches(cid, asQuery(p), signal), { keepPrevious: true, enabled });
export const useExpiry = (params: MaybeRefOrGetter<Query>) => useResource("expiry", () => ({ ...toValue(params) }), (cid, p) => stockApi.expiry(cid, asQuery(p)), { keepPrevious: true });
export const useReceipts = (params: MaybeRefOrGetter<Query>) =>
  useResource("receipts", () => ({ ...toValue(params) }), (cid, p, signal) => stockApi.receipts(cid, asQuery(p), signal), { keepPrevious: true });
export const useReceipt = (id: MaybeRefOrGetter<number>) => useResource("receipt", () => ({ id: toValue(id) }), (cid, p) => stockApi.receipt(cid, Number(p.id)), { enabled: () => toValue(id) > 0 });
export const useTransfers = (params: MaybeRefOrGetter<Query>) => useResource("transfers", () => ({ ...toValue(params) }), (cid, p) => stockApi.transfers(cid, asQuery(p)), { keepPrevious: true });
export const useTransfer = (id: MaybeRefOrGetter<number | null>) =>
  useResource("transfer", () => ({ id: toValue(id) }), (cid, p) => stockApi.transfer(cid, Number(p.id)), { enabled: () => !!toValue(id) });
export const useWriteoffs = (params: MaybeRefOrGetter<Query>) => useResource("writeoffs", () => ({ ...toValue(params) }), (cid, p) => stockApi.writeoffs(cid, asQuery(p)), { keepPrevious: true });
export const useWriteoff = (id: MaybeRefOrGetter<number>) => useResource("writeoff", () => ({ id: toValue(id) }), (cid, p) => stockApi.writeoff(cid, Number(p.id)), { enabled: () => toValue(id) > 0 });
export const useCounts = (params: MaybeRefOrGetter<Query>) => useResource("counts", () => ({ ...toValue(params) }), (cid, p) => stockApi.counts(cid, asQuery(p)), { keepPrevious: true });
export const useCount = (id: MaybeRefOrGetter<number>) => useResource("count", () => ({ id: toValue(id) }), (cid, p) => stockApi.count(cid, Number(p.id)), { enabled: () => toValue(id) > 0 });
export const useRecalls = (params: MaybeRefOrGetter<Query>) => useResource("recalls", () => ({ ...toValue(params) }), (cid, p) => stockApi.recalls(cid, asQuery(p)), { keepPrevious: true });
export const usePricingRules = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("pricing-rules", {}, (cid) => stockApi.pricingRules(cid), { enabled, staleTime: 60_000 });
export const useRequests = (params: MaybeRefOrGetter<Query>) => useResource("defektura", () => ({ ...toValue(params) }), (cid, p) => stockApi.requests(cid, asQuery(p)), { keepPrevious: true });
export const useControlled = (params: MaybeRefOrGetter<Query>, enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource("controlled", () => ({ ...toValue(params) }), (cid, p) => stockApi.controlled(cid, asQuery(p)), { keepPrevious: true, enabled });
export const useRxJournal = (params: MaybeRefOrGetter<Query>, enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource("rx", () => ({ ...toValue(params) }), (cid, p) => stockApi.rxJournal(cid, asQuery(p)), { keepPrevious: true, enabled });

/** Refetch every stock query and the sidebar pulse (after a write). */
export function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: stockKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "shell", "pulse"] });
  };
}

/** Products for a picker (name, INN, barcode), as ComboBox options. */
export async function searchProducts(cid: number, q: string, signal?: AbortSignal) {
  const page = await stockApi.products(cid, { q: q || undefined, page_size: 20 }, signal);
  return page.results;
}
