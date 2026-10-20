import { Ban, Clock3, KeyRound, Send, WifiOff } from "lucide-react";
import type { ReactNode } from "react";

import type { Membership } from "../api/types";
import { Mark } from "../components/Mark";
import { useI18n } from "../i18n";
import { clock, dayMonth } from "../lib/time";
import { close } from "../telegram";

function Message({ icon, title, body, children }: {
  icon: ReactNode;
  title: string;
  body: string;
  children?: ReactNode;
}) {
  return (
    <div className="screen screen--plain fade-in" style={{ paddingTop: "calc(var(--top-inset) + 72px)", gap: 14 }}>
      <Mark size={44} />
      <span className="circle" style={{ width: 76, height: 76, marginTop: 24, background: "var(--color-accent-100)", color: "var(--color-accent-700)" }}>
        {icon}
      </span>
      <h1 className="heading title-xl">{title}</h1>
      <p className="lede" style={{ margin: 0 }}>{body}</p>
      {children}
    </div>
  );
}

export function NoAccess() {
  const { t } = useI18n();
  return (
    <Message icon={<KeyRound size={32} strokeWidth={2.4} />} title={t("gate.noAccess.title")} body={t("gate.noAccess.body")}>
      <button className="btn btn-secondary btn-lg btn-block" style={{ marginTop: 16 }} onClick={close}>
        {t("gate.close")}
      </button>
    </Message>
  );
}

export function Declined({ membership }: { membership: Membership }) {
  const { t, locale } = useI18n();
  const until = membership.rejoin_available_at;
  const zone = membership.company.timezone;
  const body =
    until && new Date(until) > new Date()
      ? t("gate.declined.later", { time: `${dayMonth(until, zone, locale)} ${clock(until, zone, locale)}` })
      : t("gate.declined.now");
  return <Message icon={<Clock3 size={32} strokeWidth={2.4} />} title={t("gate.declined.title")} body={body} />;
}

export function Blocked() {
  const { t } = useI18n();
  return <Message icon={<Ban size={32} strokeWidth={2.4} />} title={t("gate.blocked.title")} body={t("gate.blocked.body")} />;
}

const FAILURES = {
  outside: { icon: Send, title: "error.outsideTitle", body: "error.outsideTelegram" },
  expired: { icon: Clock3, title: "error.expiredTitle", body: "error.expired" },
  network: { icon: WifiOff, title: "error.generic", body: "error.network" },
} as const;

export function Failure({ kind, onRetry }: { kind: keyof typeof FAILURES; onRetry?: () => void }) {
  const { t } = useI18n();
  const { icon: Icon, title, body } = FAILURES[kind];
  return (
    <Message icon={<Icon size={32} strokeWidth={2.4} />} title={t(title)} body={t(body)}>
      {onRetry && (
        <button className="btn btn-primary btn-lg btn-block" style={{ marginTop: 16 }} onClick={onRetry}>
          {t("common.retry")}
        </button>
      )}
    </Message>
  );
}
