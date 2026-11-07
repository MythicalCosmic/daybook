/**
 * Receiving, Kirim (nakladnoy) (PLAN-OWNER §14.17): a distributor's delivery entered for checking.
 * Start with the distributor, the nakladnoy's number and date and its photo; add each line by
 * search or scan with the series, the expiry (month and year, as the pack prints it), packs and
 * the cost per pack; the server's warnings show on each line (short shelf life, a recalled series,
 * a cost jump…); then send it for posting, which the head does. Costs are written, never read.
 */
import { PackagePlus, Pill, Plus, ScanBarcode, Send, Trash2, TriangleAlert, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { ApiError } from "../../api/client";
import { amountFromTyping } from "../../lib/money";
import { dayKey } from "../../lib/time";
import { useDraftGuard } from "../../lib/useDraftGuard";
import { baseCurrency } from "../../api/membership";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import {
  Badge,
  Banner,
  BottomBar,
  Button,
  Card,
  DateInput,
  EmptyState,
  Field,
  IconButton,
  Input,
  ListCard,
  ListRow,
  LoadError,
  MoneyInput,
  PageHeader,
  PhotoInput,
  Screen,
  SectionHead,
  Select,
  Stepper,
} from "../../ui";
import type { PageProps } from "../registry";
import { useFeedback } from "../states";
import { useFeatureOpen } from "../useFeatureOpen";
import {
  RECEIPT_WARNINGS,
  useAddLine,
  useCreateReceipt,
  useLookup,
  useReceipts,
  useRemoveLine,
  useStockSettings,
  useSubmitReceipt,
  useSuppliers,
  type Receipt,
  type ReceiptLine,
  type Ref,
} from "./api";
import { decimalText, lastDayOfMonth, packDate, qtyText } from "./lib";
import { RowsSkeleton, useSettled } from "./parts";
import { useCanScan, useScanResult } from "./scan";
import { useStockT, type StockKey, type StockT } from "./text";
import "./stock.css";

const RECEIVE_TARGET = "receive";

export default function ReceivePage({ params }: PageProps) {
  const t = useStockT();
  const member = useMember();
  const navigation = useNavigation();
  const receipts = useReceipts(member.companyId);
  const id = Number(params.id) || 0;
  const header = <PageHeader kicker={member.home_branch?.name ?? member.company.name} title={t("receive.title")} subtitle={t("receive.subtitle")} onBack={navigation.pop} />;
  if (!receipts.data) {
    return (
      <Screen variant="detail">
        {header}
        {receipts.isError ? <LoadError error={receipts.error} onRetry={() => void receipts.refetch()} onBack={navigation.pop} /> : <RowsSkeleton rows={2} />}
      </Screen>
    );
  }
  if (!id) return <Start receipts={receipts.data} header={header} />;
  const receipt = receipts.data.find((row) => row.id === id);
  if (!receipt) {
    return (
      <Screen variant="detail">
        {header}
        <LoadError error={new ApiError(404, null)} onBack={navigation.pop} />
      </Screen>
    );
  }
  return <Draft key={receipt.id} receipt={receipt} />;
}

/** The started receipts, and a new one. */
function Start({ receipts, header }: { receipts: Receipt[]; header: ReactNode }) {
  const t = useStockT();
  const open = useFeatureOpen("stock");
  return (
    <Screen variant="detail">
      {header}
      {receipts.length > 0 && (
        <>
          <SectionHead count={receipts.length}>{t("receive.drafts")}</SectionHead>
          <div className="stk-list">
            {receipts.map((receipt) => (
              <ReceiptRow key={receipt.id} receipt={receipt} onOpen={() => open.page("receive", { id: receipt.id })} />
            ))}
          </div>
        </>
      )}
      <NewReceipt receipts={receipts} />
    </Screen>
  );
}

function ReceiptRow({ receipt, onOpen }: { receipt: Receipt; onOpen: () => void }) {
  const t = useStockT();
  return (
    <ListRow
      variant="card"
      icon={PackagePlus}
      tone={receipt.status === "draft" ? "accent" : "sage"}
      title={receipt.supplier.name}
      subtitle={[
        t("receive.invoice", { number: receipt.supplier_invoice_number || `#${receipt.id}`, day: packDate(receipt.supplier_invoice_date) }),
        t("receive.lineCount", { count: receipt.lines.length }),
        t(`receive.status.${receipt.status}`),
      ].join(" · ")}
      onClick={onOpen}
    />
  );
}

/** The distributors to pick from: the app's list, or until the server has one, those of recent receipts. */
function useDistributors(receipts: Receipt[]): Ref[] {
  const member = useMember();
  const suppliers = useSuppliers(member.companyId);
  if (suppliers.data) return suppliers.data;
  const seen = new Map<number, Ref>();
  for (const receipt of receipts) seen.set(receipt.supplier.id, receipt.supplier);
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
}

function NewReceipt({ receipts }: { receipts: Receipt[] }) {
  const t = useStockT();
  const member = useMember();
  const navigation = useNavigation();
  const feedback = useFeedback();
  const create = useCreateReceipt(member.companyId);
  const distributors = useDistributors(receipts);
  const today = dayKey(new Date(), member.timeZone);
  const [supplier, setSupplier] = useState<number | null>(null);
  const [number, setNumber] = useState("");
  const [day, setDay] = useState(today);
  const [photo, setPhoto] = useState<File | null>(null);
  useDraftGuard(Boolean(number.trim() || photo));
  const chosen = supplier ?? (distributors.length === 1 ? distributors[0].id : null);

  const start = () => {
    if (!chosen || create.isPending) return;
    create.mutate(
      { supplier: chosen, supplier_invoice_number: number.trim(), supplier_invoice_date: day, file: photo },
      { onSuccess: (receipt) => navigation.replace({ feature: "stock", page: "receive", params: { id: receipt.id } }), onError: feedback.fail },
    );
  };

  return (
    <Card className="stk-form">
      <div className="card-title">{t("receive.new")}</div>
      {distributors.length === 0 ? (
        <p className="ft-hint">{t("receive.noSuppliers")}</p>
      ) : (
        <Field label={t("receive.supplier")}>
          <Select value={chosen ?? ""} onChange={(event) => setSupplier(Number(event.target.value) || null)}>
            <option value="" disabled>
              {t("receive.pickSupplier")}
            </option>
            {distributors.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <Field label={t("receive.invoiceNumber")}>
        <Input value={number} onChange={(event) => setNumber(event.target.value)} maxLength={40} autoComplete="off" />
      </Field>
      <Field label={t("receive.invoiceDate")}>
        <DateInput value={day} onChange={setDay} label={t("receive.invoiceDate")} max={today} today={today} />
      </Field>
      <Field label={t("receive.photo")} optional>
        <PhotoInput value={photo} onChange={setPhoto} capture="environment" label={t("photo.cta")} />
      </Field>
      <Button variant="primary" size="lg" block icon={PackagePlus} disabled={!chosen} loading={create.isPending} onClick={start}>
        {t("receive.start")}
      </Button>
    </Card>
  );
}

function Draft({ receipt }: { receipt: Receipt }) {
  const t = useStockT();
  const member = useMember();
  const navigation = useNavigation();
  const feedback = useFeedback();
  const submit = useSubmitReceipt(member.companyId, receipt.id);
  const [adding, setAdding] = useState(receipt.lines.length === 0);
  const draft = receipt.status === "draft";

  const send = () =>
    submit.mutate(undefined, {
      onSuccess: () => feedback.ok(t("receive.submitted")),
      onError: feedback.fail,
    });

  return (
    <Screen variant="detail">
      <PageHeader
        kicker={receipt.supplier.name}
        title={t("receive.title")}
        subtitle={t("receive.invoice", { number: receipt.supplier_invoice_number || `#${receipt.id}`, day: packDate(receipt.supplier_invoice_date) })}
        onBack={navigation.pop}
      />
      {!draft && <Banner tone="sage" icon={Send} title={t("receive.waiting")} />}
      <SectionHead count={receipt.lines.length}>{t("receive.lines")}</SectionHead>
      {receipt.lines.length === 0 && !adding && <p className="ft-quiet">{t("receive.noLines")}</p>}
      {receipt.lines.length > 0 && (
        <div className="stk-list">
          {receipt.lines.map((line) => (
            <LineRow key={line.id} receipt={receipt.id} line={line} editable={draft} />
          ))}
        </div>
      )}
      {draft &&
        (adding ? (
          <AddLine receipt={receipt.id} onClose={() => setAdding(false)} />
        ) : (
          <Button variant="secondary" block icon={Plus} onClick={() => setAdding(true)}>
            {t("receive.addLine")}
          </Button>
        ))}
      {draft && receipt.lines.length > 0 && !adding && <BottomBar primary={{ text: t("receive.submit"), icon: Send, onClick: send, loading: submit.isPending }} />}
      {receipt.lines.length === 0 && !draft && <EmptyState compact icon={PackagePlus} tone="sage" title={t("receive.noLines")} />}
    </Screen>
  );
}

function warningText(t: StockT, code: string): string {
  return (RECEIPT_WARNINGS as readonly string[]).includes(code) ? t(`warning.${code}` as StockKey) : code;
}

function LineRow({ receipt, line, editable }: { receipt: number; line: ReceiptLine; editable: boolean }) {
  const t = useStockT();
  const member = useMember();
  const feedback = useFeedback();
  const remove = useRemoveLine(member.companyId, receipt);
  return (
    <Card className="stk-exp-card" data-testid="receipt-line">
      <div className="stk-exp-head">
        <span className="stk-exp-title">{line.product.name}</span>
        {editable && <IconButton icon={Trash2} size={40} variant="ghost" label={t("receive.removeLine")} disabled={remove.isPending} onClick={() => remove.mutate(line.id, { onError: feedback.fail })} />}
      </div>
      <span className="stk-exp-meta num">
        {[t("product.series", { series: line.series }), t("product.expires", { day: packDate(line.expires_on) }), qtyText(line.quantity, line.units_per_pack, "", t)].join(" · ")}
      </span>
      {line.warnings.length > 0 && (
        <span className="stk-badges">
          {line.warnings.map((code) => (
            <Badge key={code} tone="accent" size="small" icon={TriangleAlert}>
              {warningText(t, code)}
            </Badge>
          ))}
        </span>
      )}
    </Card>
  );
}

const MONTHS = Array.from({ length: 12 }, (_, index) => index + 1);

function AddLine({ receipt, onClose }: { receipt: number; onClose: () => void }) {
  const t = useStockT();
  const member = useMember();
  const open = useFeatureOpen("stock");
  const feedback = useFeedback();
  const add = useAddLine(member.companyId, receipt);
  const settings = useStockSettings(member.companyId);
  const canScan = useCanScan(settings.data?.camera_scanning === true);
  const year = Number(dayKey(new Date(), member.timeZone).slice(0, 4));
  const [query, setQuery] = useState("");
  const [product, setProduct] = useState<Ref | null>(null);
  const [series, setSeries] = useState("");
  const [month, setMonth] = useState(0);
  const [expiryYear, setExpiryYear] = useState(0);
  const [packs, setPacks] = useState(1);
  const [cost, setCost] = useState("");
  useDraftGuard(Boolean(product || series.trim() || cost));
  const typed = useSettled(product ? "" : query, 250);
  const found = useLookup(member.companyId, typed);
  useScanResult(RECEIVE_TARGET, (code) => {
    setProduct(null);
    setQuery(code);
  });
  // A scanned or typed barcode that names one item picks it.
  const only = !product && found.data?.length === 1 && found.data[0].barcode && found.data[0].barcode === typed.trim() ? found.data[0] : null;
  useEffect(() => {
    if (only) setProduct({ id: only.id, name: only.name });
  }, [only]);
  const valid = Boolean(product && series.trim() && month && expiryYear && packs > 0);

  const save = () => {
    if (!product || !valid || add.isPending) return;
    add.mutate(
      {
        product: product.id,
        series: series.trim(),
        expires_on: lastDayOfMonth(expiryYear, month),
        packs: decimalText(packs),
        unit_cost: amountFromTyping(cost) ?? "0",
      },
      {
        onSuccess: () => {
          // Ready for the next line of the nakladnoy.
          setProduct(null);
          setQuery("");
          setSeries("");
          setPacks(1);
          setCost("");
        },
        onError: feedback.fail,
      },
    );
  };

  return (
    <Card className="stk-form" data-testid="add-line">
      <div className="ui-card-head">
        <span className="card-title">{t("receive.addLine")}</span>
        <IconButton icon={X} size={40} variant="ghost" label={t("common.close")} onClick={onClose} />
      </div>
      <Field label={t("receive.product")}>
        {product ? (
          <div className="stk-picked">
            <Pill size={18} strokeWidth={2.5} aria-hidden />
            <span className="stk-picked-name">{product.name}</span>
            <Button variant="ghost" icon={X} onClick={() => setProduct(null)}>
              {t("defektura.change")}
            </Button>
          </div>
        ) : (
          <div className="stk-search">
            <Input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("search.placeholder")} aria-label={t("receive.product")} autoComplete="off" />
            {canScan && <IconButton icon={ScanBarcode} size={44} variant="primary" label={t("search.scan")} onClick={() => open.sheet("scan", { target: RECEIVE_TARGET })} />}
          </div>
        )}
      </Field>
      {!product && (found.data?.length ?? 0) > 0 && typed.trim().length >= 2 && (
        <ListCard>
          {found.data!.slice(0, 5).map((row) => (
            <ListRow key={row.id} icon={Pill} title={row.name} subtitle={row.inn || undefined} onClick={() => setProduct({ id: row.id, name: row.name })} />
          ))}
        </ListCard>
      )}
      <Field label={t("receive.series")}>
        <Input value={series} onChange={(event) => setSeries(event.target.value.toUpperCase())} maxLength={40} autoComplete="off" autoCapitalize="characters" />
      </Field>
      <Field label={t("receive.expiry")}>
        <div className="stk-expiry-pick">
          <Select value={month || ""} onChange={(event) => setMonth(Number(event.target.value))} aria-label={t("receive.month")}>
            <option value="" disabled>
              {t("receive.month")}
            </option>
            {MONTHS.map((value) => (
              <option key={value} value={value}>
                {String(value).padStart(2, "0")}
              </option>
            ))}
          </Select>
          <Select value={expiryYear || ""} onChange={(event) => setExpiryYear(Number(event.target.value))} aria-label={t("receive.year")}>
            <option value="" disabled>
              {t("receive.year")}
            </option>
            {Array.from({ length: 8 }, (_, index) => year + index).map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Select>
        </div>
      </Field>
      <Field label={t("receive.packs")}>
        <Stepper value={packs} onChange={setPacks} min={1} max={9999} editable label={t("receive.packs")} />
      </Field>
      <Field label={t("receive.cost")} hint={t("receive.costHint")} optional>
        <MoneyInput value={cost} onChange={setCost} currency={baseCurrency(member)} aria-label={t("receive.cost")} />
      </Field>
      <Button variant="primary" block icon={Plus} disabled={!valid} loading={add.isPending} onClick={save}>
        {t("receive.saveLine")}
      </Button>
    </Card>
  );
}
