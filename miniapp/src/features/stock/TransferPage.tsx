/**
 * Count what arrived (PLAN-OWNER §14.17), then receive: each line of the transfer with what was
 * sent, the same batch (series and expiry), and what arrived, as sent until the pharmacist
 * changes it. Less than sent makes the transfer "arrived short": both heads hear and a manager
 * settles it. Opened from Transfers in, the Home card and the notice's [Open]
 * (`stock.transfer:<id>`).
 */
import { PackageCheck, SearchX } from "lucide-react";
import { useState } from "react";

import { useDraftGuard } from "../../lib/useDraftGuard";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { BottomBar, Card, EmptyState, LoadError, PageHeader, Screen } from "../../ui";
import type { PageProps } from "../registry";
import { useFeedback } from "../states";
import { useIncoming, useReceiveTransfer, type IncomingTransfer, type TransferLine } from "./api";
import { decimalText, num, packDate, qtyText } from "./lib";
import { QtyInput, RowsSkeleton } from "./parts";
import { useStockT } from "./text";
import "./stock.css";

export default function TransferPage({ params }: PageProps) {
  const t = useStockT();
  const member = useMember();
  const navigation = useNavigation();
  const incoming = useIncoming(member.companyId);
  const id = Number(params.id) || 0;
  const found = incoming.data?.find((row) => row.transfer.id === id);
  if (!found) {
    return (
      <Screen variant="detail">
        <PageHeader title={t("transfer.title")} onBack={navigation.pop} />
        {incoming.isError ? (
          <LoadError error={incoming.error} onRetry={() => void incoming.refetch()} onBack={navigation.pop} />
        ) : incoming.data ? (
          <EmptyState icon={SearchX} tone="sage" title={t("transfer.goneTitle")} body={t("transfer.goneBody")} />
        ) : (
          <RowsSkeleton rows={3} />
        )}
      </Screen>
    );
  }
  return <Counting key={found.transfer.id} incoming={found} />;
}

function Counting({ incoming }: { incoming: IncomingTransfer }) {
  const t = useStockT();
  const member = useMember();
  const navigation = useNavigation();
  const feedback = useFeedback();
  const receive = useReceiveTransfer(member.companyId);
  const { transfer, lines } = incoming;
  const [arrived, setArrived] = useState<Record<number, number>>(() => Object.fromEntries(lines.map((line) => [line.id, num(line.quantity_sent)])));
  const short = lines.filter((line) => (arrived[line.id] ?? 0) < num(line.quantity_sent));
  useDraftGuard(short.length > 0);

  const submit = () => {
    receive.mutate(
      { id: transfer.id, lines: lines.map((line) => ({ line: line.id, quantity: decimalText(arrived[line.id] ?? 0) })) },
      {
        onSuccess: (done) => {
          feedback.ok(t(done.transfer.status === "disputed" ? "transfer.doneShort" : "transfer.done"));
          navigation.pop();
        },
        onError: feedback.fail,
      },
    );
  };

  return (
    <Screen variant="detail">
      <PageHeader kicker={`${transfer.number} · ${t("transfers.from", { branch: transfer.from_branch.name })}`} title={t("transfer.title")} subtitle={t("transfer.intro")} onBack={navigation.pop} />
      <div className="stk-list">
        {lines.map((line) => (
          <LineCard key={line.id} line={line} value={arrived[line.id] ?? 0} onChange={(parts) => setArrived((before) => ({ ...before, [line.id]: parts }))} />
        ))}
      </div>
      {short.length > 0 && <p className="ft-hint stk-note">{t("transfer.shortNote", { count: short.length })}</p>}
      <BottomBar primary={{ text: t(short.length ? "transfer.receiveShort" : "transfer.receive"), icon: PackageCheck, onClick: submit, loading: receive.isPending }} />
    </Screen>
  );
}

function LineCard({ line, value, onChange }: { line: TransferLine; value: number; onChange: (parts: number) => void }) {
  const t = useStockT();
  const sent = num(line.quantity_sent);
  const batch = [line.series ? t("product.series", { series: line.series }) : null, line.expires_on ? t("product.expires", { day: packDate(line.expires_on) }) : null].filter(Boolean).join(" · ");
  return (
    <Card className="stk-exp-card" data-testid="transfer-line">
      <span className="stk-exp-title">{line.product.name}</span>
      {batch && <span className="stk-exp-meta num">{batch}</span>}
      <span className="stk-exp-meta num">{t("transfer.sent", { qty: qtyText(sent, line.units_per_pack, "", t) })}</span>
      <QtyInput label={`${t("transfer.arrived")}: ${line.product.name}`} value={value} onChange={onChange} unitsPerPack={line.units_per_pack} partLabel="" max={sent} />
    </Card>
  );
}
