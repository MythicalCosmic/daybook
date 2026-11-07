/**
 * What stock puts on Home, Me and the task screen: "4 batches expire within 30 days here" for
 * someone who works with stock, the incoming transfers to count, the Me row's badge, and the way
 * from the monthly "Expiry shelf check" task into the expiry check.
 */
import { CalendarClock, Truck } from "lucide-react";

import { Banner, Button, Card } from "../../ui";
import type { MeItemStatus, SlotProps, TaskSlotProps } from "../registry";
import { useFeatureOpen } from "../useFeatureOpen";
import { operatesStock } from "./access";
import { useExpiry, useIncoming, useMarks, useStockSettings, type AppBatch } from "./api";
import { expirySteps, isShelfCheckTask, num } from "./lib";
import type { Marks } from "./marks";
import { useStockT } from "./text";
import "./stock.css";

/** Expired batches still here, and those within the first step, that nobody marked on this phone yet. */
export function needsLook(rows: readonly AppBatch[] | undefined, marks: Marks | undefined): { expired: AppBatch[]; soon: AppBatch[] } {
  const left = (rows ?? []).filter((row) => num(row.quantity) > 0);
  return {
    expired: left.filter((row) => row.days_left < 0 && !marks?.[row.id]?.writeoff),
    soon: left.filter((row) => row.days_left >= 0 && !marks?.[row.id]?.shelf && !marks?.[row.id]?.writeoff),
  };
}

export function ExpiryCard({ member }: SlotProps) {
  const t = useStockT();
  const go = useFeatureOpen("stock");
  const settings = useStockSettings(member.companyId);
  const days = expirySteps(settings.data)[0];
  const expiry = useExpiry(member.companyId, days, !settings.isPending);
  const marks = useMarks(member.companyId);
  const { expired, soon } = needsLook(expiry.data, marks.data);
  if (!expired.length && !soon.length) return null;
  const branch = (expired[0] ?? soon[0]).branch;
  return expired.length ? (
    <Banner
      size="lg"
      iconTone="accent"
      icon={CalendarClock}
      title={t("home.expired", { count: expired.length })}
      body={t("home.expiredBody", { branch })}
      wrap
      onClick={() => go.page("expiry")}
    />
  ) : (
    <Banner
      size="lg"
      iconTone="accent"
      icon={CalendarClock}
      title={t("home.expiring", { count: soon.length, days })}
      body={t("home.expiringBody", { branch })}
      wrap
      onClick={() => go.page("expiry")}
    />
  );
}

/** "Incoming from Chilonzor: 8 items": the transfers on their way here, to count. */
export function IncomingCard({ member }: SlotProps) {
  const t = useStockT();
  const go = useFeatureOpen("stock");
  const incoming = useIncoming(member.companyId);
  const rows = incoming.data ?? [];
  if (!rows.length) return null;
  return (
    <>
      {rows.slice(0, 2).map(({ transfer }) => (
        <Banner
          key={transfer.id}
          size="lg"
          iconTone="sage"
          icon={Truck}
          title={t("home.incomingTitle", { branch: transfer.from_branch.name })}
          body={t("home.incomingBody", { count: transfer.lines_count })}
          wrap
          onClick={() => go.page("transfer", { id: transfer.id })}
        />
      ))}
    </>
  );
}

/** Me → Stock: how many transfers wait to be counted here. */
export function useMeStatus({ member }: SlotProps): MeItemStatus {
  const incoming = useIncoming(member.companyId, operatesStock(member));
  return { badge: incoming.data?.length || null };
}

/** On the monthly "Expiry shelf check" task: the expiry check itself is one tap away. */
export function ShelfCheckBlock({ task }: TaskSlotProps) {
  const t = useStockT();
  const go = useFeatureOpen("stock");
  if (!isShelfCheckTask(task)) return null;
  return (
    <Card className="stk-task-card">
      <p className="ft-hint">{t("task.expiryHint")}</p>
      <Button variant="primary" block icon={CalendarClock} onClick={() => go.page("expiry")}>
        {t("task.openExpiry")}
      </Button>
    </Card>
  );
}
