/**
 * Stock lookup (PLAN-OWNER §14.17, Must): search the catalogue by name, trade name, INN or
 * barcode, typed or scanned. Each row says what the pharmacist needs at the counter: form and
 * strength, Rx and cold-chain badges, the price per pack and per part, what is here in packs and
 * parts, the nearest expiry and what the other pharmacies hold. Under the search: the way into
 * the expiry check and the other stock screens.
 */
import { CalendarClock, ChevronRight, FilePlus2, ScanBarcode, Search, SearchX, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { EmptyState, IconButton, Input, ListCard, ListRow, LoadError, PageHeader, Screen, cx } from "../../ui";
import { useFeatureOpen } from "../useFeatureOpen";
import { operatesStock } from "./access";
import { useExpiry, useLookup, useMarks, useStockSettings, type LookupRow } from "./api";
import { expirySteps, looksLikeBarcode, num, packDate, qtyText } from "./lib";
import { ProductBadges, RowsSkeleton, formLine, partWord, useMoney, useSettled } from "./parts";
import { useCanScan, useScanResult } from "./scan";
import { useStockT } from "./text";
import "./stock.css";

/** The scan sheet's answer goes to this screen. */
export const LOOKUP_TARGET = "lookup";

export default function StockPage() {
  const t = useStockT();
  const member = useMember();
  const navigation = useNavigation();
  const open = useFeatureOpen("stock");
  const settings = useStockSettings(member.companyId);
  const canScan = useCanScan(settings.data?.camera_scanning === true);
  const [query, setQuery] = useState("");
  /** A scanned code opens its item straight away when exactly one matches. */
  const [scanned, setScanned] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  // A scanned code is searched at once; typing waits for a pause.
  const settled = useSettled(query, scanned === query ? 0 : 250);
  const term = settled.trim();
  const lookup = useLookup(member.companyId, term);

  useScanResult(LOOKUP_TARGET, (code) => {
    setScanned(code);
    setQuery(code);
  });

  useEffect(() => {
    if (!scanned || term !== scanned || !lookup.data || lookup.isPlaceholderData) return;
    setScanned(null);
    if (lookup.data.length === 1) open.page("product", { id: lookup.data[0].id });
  }, [scanned, term, lookup.data, lookup.isPlaceholderData, open]);

  const searching = term.length >= 2;
  return (
    <Screen variant="detail">
      <PageHeader kicker={member.company.name} title={t("page.title")} subtitle={t("page.subtitle")} onBack={navigation.pop} />
      <div className="stk-search" role="search">
        <Search className="stk-search-icon" size={18} strokeWidth={2.5} aria-hidden />
        <Input
          ref={input}
          type="search"
          inputMode="search"
          enterKeyHint="search"
          autoComplete="off"
          className="stk-search-input"
          aria-label={t("search.label")}
          placeholder={t("search.placeholder")}
          value={query}
          onChange={(event) => {
            setScanned(null);
            setQuery(event.target.value);
          }}
        />
        {query && (
          <button
            type="button"
            className="stk-search-clear"
            aria-label={t("search.clear")}
            onClick={() => {
              setQuery("");
              setScanned(null);
              input.current?.focus();
            }}
          >
            <X size={18} strokeWidth={2.5} aria-hidden />
          </button>
        )}
        {canScan && (
          <IconButton
            icon={ScanBarcode}
            size={44}
            variant="primary"
            label={t("search.scan")}
            onClick={() => open.sheet("scan", { target: LOOKUP_TARGET })}
          />
        )}
      </div>
      {searching ? <Results term={term} /> : <Hub />}
    </Screen>
  );
}

function Results({ term }: { term: string }) {
  const t = useStockT();
  const member = useMember();
  const open = useFeatureOpen("stock");
  const lookup = useLookup(member.companyId, term);
  if (lookup.isError && !lookup.data) return <LoadError compact error={lookup.error} onRetry={() => void lookup.refetch()} />;
  if (!lookup.data) return <RowsSkeleton />;
  if (lookup.data.length === 0) {
    const action = operatesStock(member)
      ? { label: t("hub.defektura"), icon: FilePlus2, onClick: () => open.sheet("defektura", looksLikeBarcode(term) ? {} : { name: term }) }
      : undefined;
    return <EmptyState icon={SearchX} tone="sage" title={t("search.emptyTitle")} body={t("search.emptyBody", { q: term })} action={action} />;
  }
  return (
    <div className={cx("stk-list", lookup.isPlaceholderData && "stk-list--stale")} data-testid="stock-results">
      {lookup.data.map((row) => (
        <ProductRow key={row.id} row={row} onOpen={() => open.page("product", { id: row.id })} />
      ))}
    </div>
  );
}

export function ProductRow({ row, onOpen }: { row: LookupRow; onOpen: () => void }) {
  const t = useStockT();
  const money = useMoney();
  const about = [row.trade_name, row.inn, formLine(t, row.dosage_form, row.strength)].filter(Boolean).join(" · ");
  const none = row.quantity !== null && num(row.quantity) <= 0;
  const here =
    row.quantity === null
      ? t("row.untracked")
      : none
        ? t("row.none")
        : t("row.here", { qty: qtyText(row.quantity, row.units_per_pack, row.part_label, t) });
  const nearest = row.nearest_expiry ? t("row.nearest", { day: packDate(row.nearest_expiry) }) : null;
  const elsewhere = row.elsewhere
    .filter((place) => num(place.quantity) > 0)
    .map((place) => `${place.branch} ${qtyText(place.quantity, row.units_per_pack, row.part_label, t)}`);
  return (
    <button type="button" className="row stk-row" onClick={onOpen} data-testid="stock-row">
      <span className="row-main">
        <span className="stk-row-head">
          <span className="row-title stk-row-title">{row.name}</span>
          <span className="stk-row-price num">{money(row.sale_price)}</span>
        </span>
        {about && <span className="row-meta">{about}</span>}
        <span className={cx("stk-row-here", none && "stk-row-here--none")}>{nearest && !none ? `${here} · ${nearest}` : here}</span>
        {elsewhere.length > 0 && <span className="row-meta row-meta--wrap">{t("row.elsewhere", { list: elsewhere.join(", ") })}</span>}
        <span className="stk-row-foot">
          <ProductBadges rx={row.rx_required} storage={row.storage} control={row.control_class} />
          {row.units_per_pack > 1 && <span className="stk-row-part num">{t("row.perPart", { price: money(row.part_price), label: partWord(t, row.part_label) })}</span>}
        </span>
      </span>
      <ChevronRight className="ui-row-chevron" size={19} strokeWidth={2.5} aria-hidden />
    </button>
  );
}

/** The other stock screens, with what waits in each. */
function Hub() {
  const t = useStockT();
  const member = useMember();
  const open = useFeatureOpen("stock");
  const operates = operatesStock(member);
  const settings = useStockSettings(member.companyId);
  const steps = expirySteps(settings.data);
  const expiry = useExpiry(member.companyId, steps[steps.length - 1]);
  const marks = useMarks(member.companyId);
  const urgent = (expiry.data ?? []).filter((row) => row.days_left <= steps[0] && !marks.data?.[row.id]).length;
  return (
    <>
      <p className="ft-quiet stk-hint">{t("search.hint")}</p>
      <ListCard>
        <ListRow icon={CalendarClock} title={t("hub.expiry")} badge={urgent || null} onClick={() => open.page("expiry")} />
        {operates && <ListRow icon={FilePlus2} title={t("hub.defektura")} onClick={() => open.sheet("defektura")} />}
      </ListCard>
    </>
  );
}
