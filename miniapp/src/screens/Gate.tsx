import { Ban, CirclePause, Clock3, DoorOpen, KeyRound, MessageCircle, Mic, Send, SendHorizontal, WifiOff, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { suspendedUntil } from "../api/membership";
import type { Membership } from "../api/types";
import { Mark } from "../components/Mark";
import { useI18n } from "../i18n";
import { clock, dayMonth, dayMonthLong } from "../lib/time";
import { close, insideTelegram, sendToBot } from "../telegram";
import { cx } from "../ui";

/** What the app sends the bot from a keyboard-button launch: "send me a button that signs me in". */
export const OPEN_APP_REQUEST = "open_app";

/** "26 Oct" stays on one line: a date broken after the day reads badly in a centred sentence. */
const whole = (text: string) => text.replace(/ /g, "\u00a0");

/**
 * One calm screen for every "you can't get in" state: the brand's sun with the reason's icon,
 * a Caprasimo line, a sentence and at most two actions, centred a little above the middle, with
 * the Daybook mark at the foot.
 */
function Message({
  icon: Icon,
  tone = "accent",
  title,
  body,
  children,
}: {
  icon: LucideIcon;
  /** accent: something to do; sage: nothing to do but wait or ask. */
  tone?: "accent" | "sage";
  title: string;
  body: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="screen screen--plain gate fade-in">
      <div className="gate-main">
        <span className={cx("ui-empty-art gate-art", tone === "sage" && "ui-empty--sage")} aria-hidden>
          <span className="ui-empty-sun">
            <Icon size={30} strokeWidth={2.4} />
          </span>
          <span className="ui-empty-pebble" />
        </span>
        <h1 className="heading gate-title">{title}</h1>
        <p className="gate-body">{body}</p>
        {children}
      </div>
      <div className="gate-brand" aria-hidden>
        <Mark size={22} />
        <span className="heading">Daybook</span>
      </div>
    </div>
  );
}

function CloseButton({ variant = "secondary" }: { variant?: "primary" | "secondary" }) {
  const { t } = useI18n();
  if (!insideTelegram()) return null;
  return (
    <button className={`btn btn-${variant} btn-lg btn-block gate-action`} onClick={close}>
      {t("gate.close")}
    </button>
  );
}

export function NoAccess() {
  const { t } = useI18n();
  return (
    <Message icon={KeyRound} title={t("gate.noAccess.title")} body={t("gate.noAccess.body")}>
      <CloseButton />
    </Message>
  );
}

/** Someone who used to work here: thanks, and how to come back. */
export function Left({ membership }: { membership: Membership }) {
  const { t } = useI18n();
  return (
    <Message icon={DoorOpen} tone="sage" title={t("gate.left.title")} body={t("gate.left.body", { company: membership.company.name })}>
      <CloseButton />
    </Message>
  );
}

export function Declined({ membership }: { membership: Membership }) {
  const { t, locale } = useI18n();
  const until = membership.rejoin_available_at;
  const zone = membership.company.timezone;
  const body =
    until && new Date(until) > new Date()
      ? t("gate.declined.later", { time: `${whole(dayMonth(until, zone, locale))} ${clock(until, zone, locale)}` })
      : t("gate.declined.now");
  return (
    <Message icon={Clock3} tone="sage" title={t("gate.declined.title")} body={body}>
      <CloseButton />
    </Message>
  );
}

export function Blocked() {
  const { t } = useI18n();
  return (
    <Message icon={Ban} tone="sage" title={t("gate.blocked.title")} body={t("gate.blocked.body")}>
      <CloseButton />
    </Message>
  );
}

/**
 * Shown to a suspended person when no feature brings its own "Access paused" screen: until when,
 * as the bot says it ("until 12 Nov", or until further notice).
 */
export function Suspended({ membership }: { membership: Membership }) {
  const { t, locale } = useI18n();
  const until = suspendedUntil(membership);
  // A date without a time: read it at noon UTC so no timezone moves the day.
  const body = until ? t("gate.suspended.until", { date: whole(dayMonthLong(`${until}T12:00:00Z`, "UTC", locale)) }) : t("gate.suspended.body");
  return (
    <Message icon={CirclePause} tone="sage" title={t("gate.suspended.title")} body={body}>
      <CloseButton />
    </Message>
  );
}

const FAILURES = {
  outside: { icon: Send, title: "error.outsideTitle", body: "error.outsideTelegram" },
  unsigned: { icon: MessageCircle, title: "error.unsignedTitle", body: "error.unsigned" },
  expired: { icon: Clock3, title: "error.expiredTitle", body: "error.expired" },
  network: { icon: WifiOff, title: "error.generic", body: "error.network" },
} as const;

/**
 * Why the app couldn't start: outside Telegram (a browser), inside Telegram without a sign-in (a
 * keyboard button opened it), an expired sign-in, or no connection.
 */
export function Failure({ kind, onRetry }: { kind: keyof typeof FAILURES; onRetry?: () => void }) {
  const { t } = useI18n();
  const { icon, title, body } = FAILURES[kind];
  return (
    <Message icon={icon} title={t(title)} body={t(body)}>
      {kind === "unsigned" && <ChatBarHint />}
      {kind === "unsigned" && (
        <button className="btn btn-primary btn-lg btn-block gate-action" onClick={() => sendToBot(OPEN_APP_REQUEST) || close()}>
          <SendHorizontal size={19} strokeWidth={2.5} aria-hidden />
          {t("error.unsignedSend")}
        </button>
      )}
      {kind === "unsigned" && (
        <button className="btn btn-secondary btn-lg btn-block gate-action gate-action--next" onClick={close}>
          {t("error.unsignedBack")}
        </button>
      )}
      {kind === "expired" && <CloseButton variant="primary" />}
      {onRetry && (
        <button className="btn btn-primary btn-lg btn-block gate-action" onClick={onRetry}>
          {t("common.retry")}
        </button>
      )}
    </Message>
  );
}

/** Where the app's button is: the chat's message bar, with the menu button on the left lit up. */
function ChatBarHint() {
  const { t } = useI18n();
  return (
    <div className="gate-hint" aria-hidden>
      <span className="gate-hint-app">
        <span className="gate-hint-ring" />
        📱 {t("error.unsignedButton")}
      </span>
      <span className="gate-hint-field">{t("error.unsignedField")}</span>
      <Mic size={20} strokeWidth={2.2} className="gate-hint-mic" />
    </div>
  );
}
