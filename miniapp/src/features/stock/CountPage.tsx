/**
 * The blind count (PLAN-OWNER §14.17): every batch line the count holds, with its product, series
 * and expiry, and what the counter found, typed as packs and loose parts. The expected quantity
 * never reaches this screen (the server leaves it out and `blind()` drops it if it came). Find a
 * line by typing or scanning; each save shows at once and goes back if the server refuses.
 */
import { Check, ClipboardCheck, ClipboardList, Pencil, ScanBarcode, Search } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Banner, Button, Card, EmptyState, IconButton, Input, LoadError, PageHeader, ProgressBar, Screen, Segmented } from "../../ui";
import type { PageProps } from "../registry";
import { useFeedback } from "../states";
import { useFeatureOpen } from "../useFeatureOpen";
import { useCount, useLookup, useSaveCounted, useStockSettings, type CountLine } from "./api";
import { decimalText, looksLikeBarcode, num, packDate, qtyText } from "./lib";
import { QtyInput, RowsSkeleton, useSettled } from "./parts";
import { useCanScan, useScanResult } from "./scan";
import { useStockT } from "./text";
import "./stock.css";

const COUNT_TARGET = "count";

type Filter = "left" | "all";

export default function CountPage({ params }: PageProps) {
  const t = useStockT();
  const member = useMember();
  const navigation = useNavigation();
  const id = Number(params.id) || 0;
  const count = useCount(member.companyId, id);
  if (!count.data) {
    return (
      <Screen variant="detail">
        <PageHeader title={t("count.title")} onBack={navigation.pop} />
        {count.isError ? <LoadError error={count.error} onRetry={() => void count.refetch()} onBack={navigation.pop} /> : <RowsSkeleton rows={5} />}
      </Screen>
    );
  }
  const data = count.data;
  const header = <PageHeader kicker={data.branch.name} title={t(`count.kind.${data.kind}`)} subtitle={t("count.intro")} onBack={navigation.pop} />;
  if (data.status !== "open") {
    return (
      <Screen variant="detail">
        {header}
        <EmptyState icon={ClipboardCheck} tone="sage" title={t("count.closedTitle")} body={t("count.closedBody")} />
      </Screen>
    );
  }
  return <Counting id={id} lines={data.lines} header={header} />;
}

function Counting({ id, lines, header }: { id: number; lines: CountLine[]; header: ReactNode }) {
  const t = useStockT();
  const member = useMember();
  const open = useFeatureOpen("stock");
  const feedback = useFeedback();
  const settings = useStockSettings(member.companyId);
  const canScan = useCanScan(settings.data?.camera_scanning === true);
  const save = useSaveCounted(member.companyId, id, feedback.fail);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("left");
  const [editing, setEditing] = useState<{ line: number; parts: number } | null>(null);
  useScanResult(COUNT_TARGET, (code) => {
    setFilter("all");
    setQuery(code);
  });
  const term = useSettled(query.trim(), 200);
  // A barcode names a product, which the lines know only by id: the lookup says which.
  const coded = useLookup(member.companyId, looksLikeBarcode(term) ? term : "");
  const shown = useMemo(() => {
    const ids = looksLikeBarcode(term) ? new Set((coded.data ?? []).map((row) => row.id)) : null;
    const text = term.toLocaleLowerCase();
    return lines.filter((line) => {
      if (filter === "left" && line.counted !== null && editing?.line !== line.id) return false;
      if (!text) return true;
      if (ids) return ids.has(line.product.id);
      return line.product.name.toLocaleLowerCase().includes(text) || line.series.toLocaleLowerCase().includes(text);
    });
  }, [lines, filter, term, coded.data, editing]);
  const done = lines.filter((line) => line.counted !== null).length;

  const store = (line: CountLine, parts: number) => {
    save.mutate({ line: line.id, counted: decimalText(parts) });
    // On to the next line still to count.
    const next = lines.find((other) => other.id !== line.id && other.counted === null);
    setEditing(next && filter === "left" ? { line: next.id, parts: 0 } : null);
  };

  return (
    <Screen variant="detail">
      {header}
      <ProgressBar value={done} total={Math.max(1, lines.length)} tone="sage" label={t("count.progress", { done, total: lines.length })} />
      {done === lines.length && lines.length > 0 && <Banner tone="sage" icon={Check} title={t("count.allDone")} />}
      <div className="stk-search" role="search">
        <Search className="stk-search-icon" size={18} strokeWidth={2.5} aria-hidden />
        <Input type="search" className="stk-search-input" aria-label={t("count.search")} placeholder={t("count.search")} value={query} onChange={(event) => setQuery(event.target.value)} />
        {canScan && <IconButton icon={ScanBarcode} variant="primary" label={t("search.scan")} onClick={() => open.sheet("scan", { target: COUNT_TARGET })} />}
      </div>
      <Segmented
        value={filter}
        onChange={setFilter}
        label={t("count.title")}
        options={[
          { value: "left", label: t("count.filterLeft"), count: lines.length - done },
          { value: "all", label: t("count.filterAll") },
        ]}
      />
      {shown.length === 0 ? (
        <p className="ft-quiet">{t(filter === "left" && !term ? "count.allDone" : "count.nothingFound")}</p>
      ) : (
        <div className="stk-list">
          {shown.map((line) => (
            <LineCard
              key={line.id}
              line={line}
              editing={editing?.line === line.id ? editing.parts : null}
              onEdit={(parts) => setEditing({ line: line.id, parts })}
              onSave={(parts) => store(line, parts)}
            />
          ))}
        </div>
      )}
    </Screen>
  );
}

function LineCard({ line, editing, onEdit, onSave }: { line: CountLine; editing: number | null; onEdit: (parts: number) => void; onSave: (parts: number) => void }) {
  const t = useStockT();
  const batch = [t("product.series", { series: line.series }), line.expires_on ? t("product.expires", { day: packDate(line.expires_on) }) : null].filter(Boolean).join(" · ");
  return (
    <Card className="stk-exp-card" data-testid="count-line">
      <span className="stk-exp-title">{line.product.name}</span>
      <span className="stk-exp-meta num">{batch}</span>
      {editing !== null ? (
        <div className="stk-count-edit">
          <QtyInput label={line.product.name} value={editing} onChange={onEdit} unitsPerPack={line.units_per_pack} partLabel={line.part_label} />
          <Button variant="primary" icon={Check} onClick={() => onSave(editing)}>
            {t("count.save")}
          </Button>
        </div>
      ) : line.counted !== null ? (
        <div className="stk-exp-actions">
          <span className="stk-row-here num">{t("count.counted", { qty: qtyText(line.counted, line.units_per_pack, line.part_label, t) })}</span>
          <Button variant="ghost" icon={Pencil} onClick={() => onEdit(num(line.counted))}>
            {t("count.edit")}
          </Button>
        </div>
      ) : (
        <div className="stk-exp-actions">
          <span className="stk-exp-meta">{t("count.clear")}</span>
          <Button variant="secondary" icon={ClipboardList} onClick={() => onEdit(0)}>
            {t("count.countLine")}
          </Button>
        </div>
      )}
    </Card>
  );
}
