import { Check, Hourglass, LockKeyhole } from "lucide-react";

import type { Membership } from "../api/types";
import { useI18n } from "../i18n";
import { clock, daysFromToday, dayMonth } from "../lib/time";
import { useSession } from "../state/session";

type Step = { title: string; sub: string; state: "done" | "current" | "future" };

export function Waiting({ membership, onOpen }: { membership: Membership; onOpen: () => void }) {
  const { t, locale } = useI18n();
  const { me } = useSession();
  const approved = membership.status === "approved";
  const zone = membership.company.timezone;
  const sentAt = membership.onboarded_at;
  const sentLabel = sentAt
    ? `${daysFromToday(sentAt, new Date(), zone) === 0 ? t("day.today") : dayMonth(sentAt, zone, locale)}, ${clock(sentAt, zone, locale)}`
    : "";
  const steps: Step[] = [
    { title: t("waiting.sent"), sub: sentLabel, state: "done" },
    {
      title: t("waiting.check"),
      sub: approved ? t("waiting.checkDone") : t("waiting.checkPending"),
      state: approved ? "done" : "current",
    },
    {
      title: t("waiting.access"),
      sub: approved ? t("waiting.accessDone") : t("waiting.accessPending"),
      state: approved ? "done" : "future",
    },
  ];

  return (
    <div className="screen screen--plain fade-in" style={{ paddingTop: "calc(var(--top-inset) + 56px)", paddingInline: 24, gap: "var(--space-6)" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {approved ? (
          <span className="circle" style={{ width: 76, height: 76, background: "var(--color-accent-2)", color: "var(--color-bg)" }}>
            <Check size={34} strokeWidth={3} />
          </span>
        ) : (
          <div style={{ position: "relative", width: 76, height: 76 }}>
            <span className="pulse" style={{ background: "var(--color-accent-200)" }} />
            <span className="circle" style={{ position: "absolute", inset: 0, background: "var(--color-accent-100)", color: "var(--color-accent-700)" }}>
              <Hourglass size={32} strokeWidth={2.4} />
            </span>
          </div>
        )}
        <h1 className="heading title-xl">
          {approved ? t("waiting.approvedTitle", { name: membership.first_name }) : t("waiting.title")}
        </h1>
        <p className="lede" style={{ margin: 0, lineHeight: 1.55 }}>
          {approved ? t("waiting.approvedBody") : t("waiting.body")}
        </p>
      </div>

      <div className="card" style={{ gap: 12 }}>
        <div className="card-title">{t("waiting.request")}</div>
        <div style={{ display: "grid", gridTemplateColumns: "72px minmax(0, 1fr)", gap: "10px 14px", fontSize: 16, alignItems: "baseline" }}>
          <span className="muted" style={{ fontSize: 14 }}>{t("waiting.name")}</span>
          <span style={{ fontWeight: 600 }}>{membership.first_name} {membership.last_name}</span>
          <span className="muted" style={{ fontSize: 14 }}>{t("waiting.phone")}</span>
          <span className="num" style={{ fontWeight: 600 }}>{me.phone || "—"}</span>
          <span className="muted" style={{ fontSize: 14 }}>{t("waiting.role")}</span>
          <span style={{ fontWeight: 600 }}>{membership.position?.name ?? "—"}</span>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column" }}>
        {steps.map((step, index) => (
          <div key={step.title} style={{ display: "grid", gridTemplateColumns: "30px minmax(0, 1fr)", gap: "0 14px" }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
              <StepDot state={step.state} />
              {index < steps.length - 1 && (
                <span style={{ flex: 1, width: 3, minHeight: 22, margin: "4px 0", borderRadius: 3, background: "color-mix(in srgb, var(--color-text) 12%, transparent)" }} />
              )}
            </div>
            <div style={{ padding: "3px 0 var(--space-4)" }}>
              <div style={{ fontSize: 16, fontWeight: 700, lineHeight: "22px" }}>{step.title}</div>
              <div className="muted num" style={{ fontSize: 14 }}>{step.sub}</div>
            </div>
          </div>
        ))}
      </div>

      {approved ? (
        <button className="btn btn-primary btn-lg btn-block" onClick={onOpen}>
          {t("waiting.open")}
        </button>
      ) : (
        <div className="banner" style={{ fontSize: 14.5 }}>
          <LockKeyhole size={19} strokeWidth={2.4} style={{ flex: "none" }} />
          <span>{t("waiting.locked")}</span>
        </div>
      )}
    </div>
  );
}

function StepDot({ state }: { state: Step["state"] }) {
  if (state === "done") {
    return (
      <span className="circle" style={{ width: 30, height: 30, background: "var(--color-accent-2)", color: "var(--color-bg)" }}>
        <Check size={16} strokeWidth={3} />
      </span>
    );
  }
  if (state === "current") {
    return (
      <span style={{ flex: "none", position: "relative", width: 30, height: 30 }}>
        <span className="pulse" style={{ background: "var(--color-accent-300)" }} />
        <span className="circle" style={{ position: "absolute", inset: 0, background: "var(--color-bg)", boxShadow: "inset 0 0 0 3px var(--color-accent)" }}>
          <span style={{ width: 10, height: 10, borderRadius: "50%", background: "var(--color-accent)" }} />
        </span>
      </span>
    );
  }
  return (
    <span style={{ flex: "none", width: 30, height: 30, borderRadius: "50%", boxShadow: "inset 0 0 0 2.5px color-mix(in srgb, var(--color-text) 20%, transparent)" }} />
  );
}
