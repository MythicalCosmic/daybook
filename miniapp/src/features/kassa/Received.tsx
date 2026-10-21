import { Check, HandCoins } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { useNow } from "../../lib/useNow";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Button, Card, Field, Input } from "../../ui";
import type { SlotProps } from "../registry";
import { useAnswerHandover, useHandovers, type Handover } from "./api";
import { ago, useKassaT, useMoney } from "./lib";
import "./kassa.css";

/**
 * "Did you get 1 300 000 so‘m?": cash a colleague handed to me, waiting for my answer. Yes books
 * it into my cash; No asks what happened and tells the cashier and the owner. Shown on Home
 * and on the Kassa screen, to anyone who receives cash (no till permission needed).
 */
export function ReceivedCards({ member }: SlotProps) {
  const handovers = useHandovers(member.companyId);
  const list = handovers.data ?? [];
  if (!list.length) return null;
  return (
    <>
      {list.map((handover) => (
        <ReceivedCard key={handover.id} handover={handover} />
      ))}
    </>
  );
}

/** The same cards inside the Kassa screen. */
export function ReceivedList() {
  const member = useMember();
  return <ReceivedCards member={member} summary={undefined} />;
}

function ReceivedCard({ handover }: { handover: Handover }) {
  const t = useKassaT();
  const { t: appT, locale } = useI18n();
  const member = useMember();
  const toast = useToast();
  const now = useNow();
  const money = useMoney(handover.currency);
  const answer = useAnswerHandover(member.companyId);
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState("");
  const amount = money(handover.amount);

  const send = (kind: "confirm" | "decline") => {
    answer.mutate(
      { id: handover.id, answer: kind, reason: kind === "decline" ? reason.trim() : "" },
      {
        onSuccess: () => {
          haptic.notify(kind === "confirm" ? "success" : "warning");
          toast(kind === "confirm" ? t("received.confirmed", { amount }) : t("received.declined", { name: handover.from.name }), {
            tone: kind === "confirm" ? "success" : "default",
          });
        },
        onError: (error) => {
          haptic.notify("error");
          toast(errorText(error, appT), { tone: "error" });
        },
      },
    );
  };

  return (
    <Card tone="accent" className="kassa-received">
      <div className="kassa-received-head">
        <span className="circle kassa-received-icon">
          <HandCoins size={21} strokeWidth={2.4} aria-hidden />
        </span>
        <div className="kassa-received-text">
          <span className="kassa-kicker">{t("received.kicker")}</span>
          <span className="kassa-received-title num">{t("received.title", { amount })}</span>
          <span className="kassa-received-meta">
            {t("received.from", {
              name: handover.from.name,
              place: `${handover.branch.name}, ${handover.register.name}`,
              ago: ago(t, handover.created_at, now, member.timeZone, locale),
            })}
          </span>
          {handover.reason && <span className="kassa-quote">{t("quote", { text: handover.reason })}</span>}
        </div>
      </div>
      {declining ? (
        <div className="kassa-received-decline">
          <Field label={t("received.reason")} optional>
            <Input value={reason} onChange={(event) => setReason(event.target.value)} placeholder={t("received.reasonPlaceholder")} maxLength={300} autoFocus />
          </Field>
          <div className="kassa-received-actions">
            <Button variant="ghost" onClick={() => setDeclining(false)} disabled={answer.isPending}>
              {t("received.cancel")}
            </Button>
            <Button variant="primary" loading={answer.isPending} onClick={() => send("decline")}>
              {t("received.send")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="kassa-received-actions">
          <Button variant="secondary" onClick={() => setDeclining(true)} disabled={answer.isPending}>
            {t("received.no")}
          </Button>
          <Button variant="primary" icon={Check} loading={answer.isPending} onClick={() => send("confirm")}>
            {t("received.yes")}
          </Button>
        </div>
      )}
    </Card>
  );
}
