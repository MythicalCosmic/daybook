import { Check, Hourglass, LockKeyhole } from "lucide-react";

import type { Membership } from "../api/types";
import { Mark } from "../components/Mark";
import { useI18n } from "../i18n";
import { formatPhone } from "../lib/phone";
import { clock, daysFromToday, dayMonth } from "../lib/time";
import { useSession } from "../state/session";
import { BottomBar, cx } from "../ui";

type Step = { title: string; sub: string; state: "done" | "current" | "future" };

/**
 * The waiting room after the request is sent, and the welcome once it's approved (the approval
 * lands while the app is open). The request card is only there while it's being checked. Someone
 * a team link let in straight away gets the welcome alone: nobody had anything to check.
 */
export function Waiting({ membership, onOpen }: { membership: Membership; onOpen: () => void }) {
  const { t, locale } = useI18n();
  const { me } = useSession();
  const approved = membership.status === "approved";
  const byLink = approved && membership.joined_by_link === true;
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
    <>
      <div className={cx("screen screen--plain signup waiting fade-in", approved && "waiting--approved")}>
        <div className="signup-brand">
          <Mark size={26} />
          <span>{membership.company.name}</span>
        </div>

        <div className="waiting-hero">
          {approved ? (
            <span className="circle waiting-badge waiting-badge--done">
              <Check size={34} strokeWidth={3} />
            </span>
          ) : (
            <span className="waiting-badge-wrap">
              <span className="pulse" />
              <span className="circle waiting-badge">
                <Hourglass size={32} strokeWidth={2.4} />
              </span>
            </span>
          )}
          <h1 className="heading title-xl">
            {byLink ? t("waiting.linkTitle", { name: membership.first_name }) : approved ? t("waiting.approvedTitle", { name: membership.first_name }) : t("waiting.title")}
          </h1>
          <p className="lede">{byLink ? t("waiting.linkBody", { company: membership.company.name }) : approved ? t("waiting.approvedBody") : t("waiting.body")}</p>
        </div>

        {!approved && (
          <div className="card waiting-request">
            <div className="card-title">{t("waiting.request")}</div>
            <dl className="waiting-facts">
              <dt>{t("waiting.name")}</dt>
              <dd>
                {membership.first_name} {membership.last_name}
              </dd>
              <dt>{t("waiting.phone")}</dt>
              <dd className="num">{me.phone ? formatPhone(me.phone) : "—"}</dd>
              <dt>{t("waiting.role")}</dt>
              <dd>{membership.position?.name ?? "—"}</dd>
            </dl>
          </div>
        )}

        {!byLink && (
        <ol className="waiting-steps">
          {steps.map((step, index) => (
            <li key={step.title} className="waiting-step">
              <span className="waiting-step-rail">
                <StepDot state={step.state} />
                {index < steps.length - 1 && <span className="waiting-step-line" />}
              </span>
              <span className="waiting-step-text">
                <span className="waiting-step-title">{step.title}</span>
                <span className="muted num waiting-step-sub">{step.sub}</span>
              </span>
            </li>
          ))}
        </ol>
        )}

        {!approved && (
          <div className="banner waiting-locked">
            <LockKeyhole size={19} strokeWidth={2.4} style={{ flex: "none" }} aria-hidden />
            <span>{t("waiting.locked")}</span>
          </div>
        )}
      </div>
      {approved && <BottomBar primary={{ text: t("waiting.open"), onClick: onOpen, shine: true }} />}
    </>
  );
}

function StepDot({ state }: { state: Step["state"] }) {
  if (state === "done") {
    return (
      <span className="circle waiting-dot waiting-dot--done">
        <Check size={16} strokeWidth={3} />
      </span>
    );
  }
  if (state === "current") {
    return (
      <span className="waiting-dot waiting-dot--current">
        <span className="pulse" />
        <span className="circle waiting-dot-ring">
          <span className="waiting-dot-core" />
        </span>
      </span>
    );
  }
  return <span className="waiting-dot waiting-dot--future" />;
}
