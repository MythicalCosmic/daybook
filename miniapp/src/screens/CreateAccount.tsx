import { Check, Phone } from "lucide-react";
import { useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { useMe, useOnboard, usePositions } from "../api/hooks";
import type { Membership } from "../api/types";
import { useI18n } from "../i18n";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { haptic, requestContact, telegramName, useBackButton } from "../telegram";

/** Three steps, as in the design: name, phone (verified by Telegram), role. */
export function CreateAccount({ membership }: { membership: Membership }) {
  const { t } = useI18n();
  const { me } = useSession();
  const toast = useToast();
  const fromTelegram = telegramName();
  const [step, setStep] = useState(0);
  const [first, setFirst] = useState(membership.first_name || me.first_name || fromTelegram.first);
  const [last, setLast] = useState(membership.last_name || me.last_name || fromTelegram.last);
  const [positionId, setPositionId] = useState<number | null>(membership.position?.id ?? null);
  const [askedForPhone, setAskedForPhone] = useState(false);
  const [phoneDenied, setPhoneDenied] = useState(false);
  const company = membership.company.id;
  const positions = usePositions(company);
  const onboard = useOnboard(company);
  // While we wait for the bot to receive the shared contact, keep checking /me.
  const live = useMe({ poll: askedForPhone && !me.phone });
  const phone = live.data?.phone || me.phone;

  useEffect(() => useBackButton(step > 0 ? () => setStep((value) => value - 1) : null), [step]);

  const sharePhone = async () => {
    haptic();
    setPhoneDenied(false);
    const shared = await requestContact();
    if (shared) setAskedForPhone(true);
    else setPhoneDenied(true);
  };

  const positionList = positions.data ?? [];
  const canContinue = [
    first.trim() !== "" && last.trim() !== "",
    Boolean(phone),
    positionList.length === 0 || positionId !== null,
  ][step];

  const next = () => {
    if (!canContinue || onboard.isPending) return;
    haptic();
    if (step < 2) {
      setStep(step + 1);
      return;
    }
    onboard.mutate(
      { first_name: first.trim(), last_name: last.trim(), position_id: positionId },
      {
        onSuccess: () => haptic("success"),
        onError: (error) => toast((error instanceof ApiError && error.detail) || t("error.generic")),
      },
    );
  };

  const cta =
    step < 2
      ? t("common.continue")
      : onboard.isPending
        ? t("signup.sending")
        : membership.status === "pending"
          ? t("signup.send")
          : t("signup.finish");

  return (
    <div
      className="screen screen--plain"
      style={{ paddingTop: "calc(var(--top-inset) + 40px)", paddingInline: 24, gap: 0 }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div className="num" style={{ fontSize: 14, fontWeight: 700, color: "var(--color-accent-700)" }}>
          {t("signup.step", { n: step + 1 })}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {[0, 1, 2].map((index) => (
            <div
              key={index}
              style={{
                flex: 1,
                height: 6,
                borderRadius: 999,
                background:
                  index <= step
                    ? "var(--color-accent)"
                    : "color-mix(in srgb, var(--color-text) 10%, transparent)",
                transition: "background 0.3s ease",
              }}
            />
          ))}
        </div>
      </div>

      <div key={step} className="enter" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: "var(--space-4)", marginTop: "var(--space-6)" }}>
        {step === 0 && (
          <>
            <div>
              <h1 className="heading title-lg">{t("signup.name.title")}</h1>
              <p className="lede">{t("signup.name.lede")}</p>
            </div>
            <div className="field">
              <label htmlFor="first">{t("signup.first")}</label>
              <input id="first" className="input" autoComplete="given-name" value={first} onChange={(e) => setFirst(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="last">{t("signup.last")}</label>
              <input id="last" className="input" autoComplete="family-name" value={last} onChange={(e) => setLast(e.target.value)} />
            </div>
          </>
        )}

        {step === 1 && (
          <>
            <div>
              <h1 className="heading title-lg">{t("signup.phone.title")}</h1>
              <p className="lede">{t("signup.phone.lede")}</p>
            </div>
            {phone ? (
              <div className="banner banner--sage">
                <span className="banner-icon">
                  <Check size={18} strokeWidth={3} />
                </span>
                <span style={{ display: "flex", flexDirection: "column" }}>
                  <span className="num" style={{ fontSize: 17, fontWeight: 700 }}>{phone}</span>
                  <span style={{ fontSize: 14 }}>{t("signup.phone.verified")}</span>
                </span>
              </div>
            ) : (
              <button className="btn btn-secondary btn-lg btn-block" onClick={sharePhone} disabled={askedForPhone}>
                <Phone size={19} strokeWidth={2.5} />
                {askedForPhone ? t("signup.phone.waiting") : t("signup.phone.share")}
              </button>
            )}
            {phoneDenied && <p className="muted" style={{ margin: 0, fontSize: 15 }}>{t("signup.phone.denied")}</p>}
          </>
        )}

        {step === 2 && (
          <>
            <div>
              <h1 className="heading title-lg">{t("signup.role.title")}</h1>
              <p className="lede">{positionList.length ? t("signup.role.lede") : t("signup.role.none")}</p>
            </div>
            <div role="radiogroup" style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8, padding: 2 }}>
              {positions.isPending && <div className="skeleton" style={{ height: 56 }} />}
              {positionList.map((position) => (
                <button
                  key={position.id}
                  className="choice"
                  role="radio"
                  aria-checked={positionId === position.id}
                  onClick={() => {
                    haptic();
                    setPositionId(position.id);
                  }}
                >
                  <span>{position.name}</span>
                  <span className="dot" />
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      <button className="btn btn-primary btn-lg btn-block" style={{ marginTop: "var(--space-4)" }} disabled={!canContinue || onboard.isPending} onClick={next}>
        {cta}
      </button>
    </div>
  );
}
