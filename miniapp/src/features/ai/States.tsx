import { Check, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { can } from "../../api/permissions";
import { useFeatureT } from "../../i18n/feature";
import { useMember } from "../../state/session";
import { renderIcon, type IconLike } from "../../ui/icon";
import { cx } from "../../ui/cx";
import { messages } from "./messages";

/** A whole-sheet state: an icon in a soft circle, a heading, a sentence, and its buttons. */
export function StateView({
  icon,
  tone = "accent",
  title,
  body,
  children,
}: {
  icon: IconLike;
  tone?: "accent" | "sage" | "warn";
  title: ReactNode;
  body?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="ai-stage fade-in">
      <div className="ai-state">
        <span className={cx("ai-state-icon", tone !== "accent" && `ai-state-icon--${tone}`)} aria-hidden>
          {renderIcon(icon, 28, 2.3)}
        </span>
        <div className="heading title-sm">{title}</div>
        {body && <p className="ai-state-body">{body}</p>}
      </div>
      {children && <div className="ai-actions">{children}</div>}
    </div>
  );
}

export type WorkingPhase = "sending" | "listening" | "thinking";

/**
 * While the AI works: a breathing orb, "Listening…" then "Thinking…", the two steps ticking off,
 * what was heard as soon as it is written down, and the cards to come as shimmering outlines.
 */
export function Working({ phase, voice = true, heard }: { phase: WorkingPhase; voice?: boolean; heard?: string }) {
  const t = useFeatureT(messages);
  const title = phase === "sending" ? t("sending") : phase === "listening" ? t("work.listening") : t("work.thinking");
  const steps: { key: string; label: string; state: "done" | "active" | "next" }[] = [];
  if (voice) steps.push({ key: "listen", label: t("work.stepListen"), state: phase === "thinking" ? "done" : phase === "listening" ? "active" : "next" });
  steps.push({ key: "think", label: t("work.stepThink"), state: phase === "thinking" ? "active" : "next" });
  return (
    <div className="ai-stage ai-working fade-in" aria-busy="true">
      <div className="ai-orb" aria-hidden>
        <span className="ai-orb-ring" />
        <span className="ai-orb-core">
          <Sparkles size={26} strokeWidth={2.2} />
        </span>
      </div>
      <div className="heading title-sm ai-shimmer-text" role="status" aria-live="polite">
        {title}
      </div>
      <ol className="ai-steps">
        {steps.map((step) => (
          <li key={step.key} className={cx("ai-step", `ai-step--${step.state}`)}>
            <span className="ai-step-mark" aria-hidden>
              {step.state === "done" ? <Check size={14} strokeWidth={3} /> : step.state === "active" ? <span className="ui-spinner" /> : null}
            </span>
            <span>{step.label}</span>
          </li>
        ))}
      </ol>
      {heard && (
        <blockquote className="ai-quote ai-quote--live fade-in">
          <span className="ai-quote-label">{t("review.heard")}</span>
          <span className="ai-quote-text">{heard}</span>
        </blockquote>
      )}
      <div className="ai-ghosts" aria-hidden>
        <span className="ai-ghost skeleton" />
        <span className="ai-ghost ai-ghost--short skeleton" />
      </div>
    </div>
  );
}

/** AI is off for this company: owners are told where to turn it on, others whom to ask. */
export function AIOff() {
  const t = useFeatureT(messages);
  const member = useMember();
  return <StateView icon={Sparkles} tone="sage" title={t("off.title")} body={t(can(member, "ai.configure") ? "off.owner" : "off.member")} />;
}
