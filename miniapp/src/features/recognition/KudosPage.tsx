/**
 * Thanks received and given (PLAN-LEARNING §7.5, §12.2), newest first, with "Say thanks back" on
 * the ones received. Opening the received ones marks them seen (Home's card goes).
 */
import { HeartHandshake, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useI18n } from "../../i18n";
import { dayMonth } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Avatar, Button, Card, EmptyState, LoadError, PageHeader, Screen, Segmented, SkeletonList } from "../../ui";
import type { PageProps } from "../registry";
import { useKudosBox, useMarkSeen, useRecognitionMe, type Kudos } from "./api";
import { kudosIcon, useRecognitionT } from "./parts";
import "./recognition.css";

type Box = "received" | "given";

export default function KudosPage(_: PageProps) {
  const t = useRecognitionT();
  const member = useMember();
  const navigation = useNavigation();
  const [box, setBox] = useState<Box>("received");
  const rows = useKudosBox(member.companyId, box);
  const me = useRecognitionMe(member.companyId);
  const seen = useMarkSeen(member.companyId);
  const marked = useRef(false);
  const unseen = (rows.data ?? []).some((row) => box === "received" && !row.seen);

  useEffect(() => {
    if (!unseen || marked.current) return;
    marked.current = true;
    seen.mutate({ kudos: true });
  }, [unseen, seen]);

  const thank = (to?: number) =>
    navigation.openSheet({ kind: "feature", feature: "recognition", sheet: "kudos", params: to ? { to } : {} });

  return (
    <Screen variant="detail" className="rcg-screen">
      <PageHeader
        title={t("feed.title")}
        kicker={member.company.name}
        onBack={navigation.pop}
        actions={
          me.data?.kudos_enabled ? (
            <Button variant="primary" icon={Send} onClick={() => thank()}>
              {t("plus.thank")}
            </Button>
          ) : undefined
        }
      />
      <Segmented
        role="tablist"
        options={[
          { value: "received", label: t("feed.received") },
          { value: "given", label: t("feed.given") },
        ]}
        value={box}
        onChange={setBox}
      />
      {rows.isPending ? (
        <SkeletonList count={3} height={96} />
      ) : !rows.data ? (
        <LoadError error={rows.error} onRetry={() => void rows.refetch()} />
      ) : rows.data.length === 0 ? (
        <EmptyState icon={HeartHandshake} tone="sage" title={t("feed.title")} body={box === "received" ? t("feed.emptyReceived") : t("feed.emptyGiven")} />
      ) : (
        <div className="rcg-feed" data-testid={`feed-${box}`}>
          {rows.data.map((row) => (
            <KudosCard key={row.id} row={row} box={box} onThankBack={() => thank(row.from.id)} canThank={!!me.data?.kudos_enabled} />
          ))}
        </div>
      )}
    </Screen>
  );
}

function KudosCard({ row, box, onThankBack, canThank }: { row: Kudos; box: Box; onThankBack: () => void; canThank: boolean }) {
  const t = useRecognitionT();
  const member = useMember();
  const { locale } = useI18n();
  const other = box === "received" ? row.from : row.to;
  const Icon = kudosIcon(row.badge);
  return (
    <Card className="rcg-feed-card">
      <div className="rcg-feed-head">
        <Avatar name={other.name} src={other.avatar_url} size="md" />
        <span className="rcg-feed-who">
          <span className="rcg-feed-name">{box === "received" ? t("feed.from", { name: other.name }) : t("feed.to", { name: other.name })}</span>
          <span className="rcg-feed-when">{dayMonth(row.at, member.timeZone, locale)}</span>
        </span>
        <span className={`rcg-feed-badge rcg-kudos-badge--${row.badge}`}>
          <Icon size={16} strokeWidth={2.4} aria-hidden />
          {t(`kudos.badge.${row.badge}`)}
        </span>
      </div>
      {row.message && <p className="rcg-feed-message">«{row.message}»</p>}
      {row.task && <p className="rcg-feed-task">{row.task.title}</p>}
      {box === "received" && canThank && (
        <Button variant="ghost" className="rcg-feed-back" onClick={onThankBack}>
          {t("feed.thankBack")}
        </Button>
      )}
    </Card>
  );
}
