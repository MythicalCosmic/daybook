/**
 * The expiry check (PLAN-OWNER §14.17, Must): my pharmacy's batches that expired or expire
 * within the company's steps (90 / 60 / 30 days by default), a group at a time. Each batch:
 * "On the near-expiry shelf" once it is put there, and "Propose write-off" with a photo. Both
 * show at once and go back, with the server's reason, if it refuses. Opened from the Stock page,
 * the Home card, the monthly "Expiry shelf check" task and the expiry notices (`stock.expiry`).
 */
import { CalendarCheck, Check, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { dayKey } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Badge, Button, Card, EmptyState, LoadError, PageHeader, Screen, Segmented, Spinner, cx } from "../../ui";
import { useScrollEdges } from "../../ui/useScrollEdges";
import { useFeedback } from "../states";
import { useFeatureOpen } from "../useFeatureOpen";
import { operatesStock } from "./access";
import { useExpiry, useMarks, useShelfMark, useStockSettings, type AppBatch } from "./api";
import { expiryGroup, expirySteps, packDate, qtyText, type ExpiryGroup } from "./lib";
import type { Mark } from "./marks";
import { BatchState, ExpirySkeleton } from "./parts";
import { useStockT } from "./text";
import "./stock.css";

/** The batches of each group, expired first and then by step, each soonest first. */
export function groupRows(rows: readonly AppBatch[], steps: readonly number[]): Map<ExpiryGroup, AppBatch[]> {
  const groups = new Map<ExpiryGroup, AppBatch[]>([["expired", []], ...steps.map((step) => [`${step}` as ExpiryGroup, [] as AppBatch[]] as const)]);
  for (const row of [...rows].sort((a, b) => a.days_left - b.days_left || a.id - b.id)) {
    const group = expiryGroup(row.days_left, steps);
    if (group) groups.get(group)?.push(row);
  }
  return groups;
}

export default function ExpiryPage() {
  const t = useStockT();
  const member = useMember();
  const navigation = useNavigation();
  const settings = useStockSettings(member.companyId);
  const steps = expirySteps(settings.data);
  const within = steps[steps.length - 1];
  // Wait for the company's steps, so the list isn't asked for twice.
  const expiry = useExpiry(member.companyId, within, !settings.isPending);
  const [picked, setPicked] = useState<ExpiryGroup | null>(null);
  const strip = useScrollEdges<HTMLDivElement>();
  const groups = useMemo(() => groupRows(expiry.data ?? [], steps), [expiry.data, steps]);
  const branch = expiry.data?.[0]?.branch ?? member.home_branch?.name ?? member.company.name;
  const header = <PageHeader kicker={branch} title={t("expiry.title")} subtitle={t("expiry.subtitle")} onBack={navigation.pop} />;

  if (!expiry.data) {
    return (
      <Screen variant="detail">
        {header}
        {expiry.isError ? <LoadError error={expiry.error} onRetry={() => void expiry.refetch()} onBack={navigation.pop} /> : <ExpirySkeleton />}
      </Screen>
    );
  }
  const order = [...groups.keys()];
  const current = picked ?? order.find((key) => (groups.get(key)?.length ?? 0) > 0) ?? null;
  if (current === null) {
    return (
      <Screen variant="detail">
        {header}
        <EmptyState icon={CalendarCheck} tone="sage" title={t("expiry.emptyTitle")} body={t("expiry.emptyBody", { days: within })} />
      </Screen>
    );
  }
  const rows = groups.get(current) ?? [];
  const at = steps.indexOf(Number(current));
  const note =
    current === "expired"
      ? t("expiry.noteExpired")
      : at <= 0
        ? t("expiry.noteFirst", { days: current })
        : t("expiry.noteRange", { from: steps[at - 1] + 1, to: current });
  return (
    <Screen variant="detail">
      {header}
      {/* Four groups with counts don't fit every phone in every language: the strip scrolls. */}
      <Segmented
        ref={strip.ref}
        role="tablist"
        className="seg--scroll"
        label={t("expiry.title")}
        value={current}
        onChange={setPicked}
        options={order.map((key) => ({
          value: key,
          label: key === "expired" ? t("expiry.groupExpired") : t("expiry.groupDays", { days: key }),
          count: groups.get(key)?.length ?? 0,
        }))}
      />
      <p className="ft-hint stk-note">{note}</p>
      {rows.length === 0 ? (
        <p className="ft-quiet">{t("expiry.groupEmpty")}</p>
      ) : (
        <div className="stk-list">
          {rows.map((row) => (
            <ExpiryRow key={row.id} row={row} within={within} urgent={row.days_left <= steps[0]} />
          ))}
        </div>
      )}
    </Screen>
  );
}

function ExpiryRow({ row, within, urgent }: { row: AppBatch; within: number; urgent: boolean }) {
  const t = useStockT();
  const member = useMember();
  const open = useFeatureOpen("stock");
  const feedback = useFeedback();
  const marks = useMarks(member.companyId);
  const shelf = useShelfMark(member.companyId, feedback.fail);
  const mark: Mark | undefined = marks.data?.[row.id];
  const operates = operatesStock(member);
  const qty = row.units_per_pack ? qtyText(row.quantity, row.units_per_pack, row.part_label ?? "", t) : t("qty.parts", { count: Number(row.quantity) || 0 });
  const series = t("product.series", { series: row.series });
  const when = row.days_left < 0 ? t("product.expiredOn", { day: packDate(row.expires_on) }) : t("product.expires", { day: packDate(row.expires_on) });
  return (
    <Card className={cx("stk-exp-card", mark?.writeoff && "stk-exp-card--done")} data-testid="expiry-row">
      <div className="stk-exp-head">
        <span className="stk-exp-title">{row.product?.name ?? series}</span>
        <Badge tone={urgent ? "accent" : "neutral"} size="small">
          {row.days_left < 0 ? t("badge.expired") : t("product.daysLeft", { count: row.days_left })}
        </Badge>
      </div>
      <div className="stk-exp-meta num">{[row.product ? series : null, when, t("expiry.onHand", { qty })].filter(Boolean).join(" · ")}</div>
      {row.status !== "sellable" && (
        <div>
          <BatchState expired={false} status={row.status} />
        </div>
      )}
      {operates && (
        <div className="stk-exp-actions">
          {mark?.writeoff ? (
            <Badge tone="sage" size="small" icon={mark.writeoff === "pending" ? undefined : Check}>
              {mark.writeoff === "pending" ? (
                <span className="stk-sending">
                  <Spinner size={13} />
                  {t("expiry.sending")}
                </span>
              ) : (
                t("expiry.proposed")
              )}
            </Badge>
          ) : (
            <>
              {row.days_left >= 0 &&
                (mark?.shelf ? (
                  <Badge tone="sage" icon={Check}>
                    {t("expiry.onShelfDone")}
                  </Badge>
                ) : (
                  <Button
                    variant="secondary"
                    icon={Check}
                    haptic="light"
                    onClick={() => shelf.mutate({ id: row.id, day: dayKey(new Date(), member.timeZone) })}
                  >
                    {t("expiry.onShelf")}
                  </Button>
                ))}
              <Button variant={row.days_left < 0 ? "primary" : "ghost"} icon={Trash2} onClick={() => open.sheet("writeoff", { id: row.id, within })}>
                {t("expiry.writeOff")}
              </Button>
            </>
          )}
        </div>
      )}
    </Card>
  );
}
