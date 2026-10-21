import { Check, Phone } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ApiError } from "../api/client";
import { useMe, useOnboard, usePositions } from "../api/hooks";
import type { Membership } from "../api/types";
import { Mark } from "../components/Mark";
import { useI18n } from "../i18n";
import { formatPhone } from "../lib/phone";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { haptic, requestContact, supports, telegramName, useBackButton } from "../telegram";
import { BottomBar, LoadError, Spinner, cx, type BottomAction } from "../ui";

/** How long the bot may take to receive a shared contact before we offer to share it again. */
const SLOW_PHONE_MS = 12_000;

/**
 * Three steps, as in the design: name, phone (verified by Telegram), position. The step's one
 * action is Telegram's main button (outside Telegram, the same button at the foot of the page),
 * so the on-screen keyboard never pushes a button over a field.
 */
export function CreateAccount({ membership }: { membership: Membership }) {
  const { t } = useI18n();
  const { me } = useSession();
  const toast = useToast();
  const fromTelegram = telegramName();
  const [step, setStep] = useState(0);
  const [back, setBack] = useState(false);
  const [first, setFirst] = useState(membership.first_name || me.first_name || fromTelegram.first);
  const [last, setLast] = useState(membership.last_name || me.last_name || fromTelegram.last);
  const [positionId, setPositionId] = useState<number | null>(membership.position?.id ?? null);
  const [asking, setAsking] = useState(false);
  const [sharedAt, setSharedAt] = useState<number | null>(null);
  const [slow, setSlow] = useState(false);
  const [problem, setProblem] = useState<"denied" | "unsupported" | null>(null);
  const lastName = useRef<HTMLInputElement>(null);
  const company = membership.company.id;
  const positions = usePositions(company);
  const onboard = useOnboard(company);
  // While the bot receives the shared contact, keep checking /me.
  const live = useMe({ poll: sharedAt !== null && !me.phone });
  const phone = live.data?.phone || me.phone;

  const goTo = (target: number) => {
    setBack(target < step);
    setStep(target);
  };
  useEffect(
    () =>
      useBackButton(
        step > 0
          ? () => {
              setBack(true);
              setStep(step - 1);
            }
          : null,
      ),
    [step],
  );

  // The bot hasn't heard from Telegram after a while: let the person share again.
  useEffect(() => {
    if (sharedAt === null || phone) return;
    const timer = window.setTimeout(() => setSlow(true), Math.max(0, sharedAt + SLOW_PHONE_MS - Date.now()));
    return () => window.clearTimeout(timer);
  }, [sharedAt, phone]);

  const sharePhone = async () => {
    if (asking) return;
    haptic();
    setProblem(null);
    setSlow(false);
    if (!supports("6.9")) {
      setProblem("unsupported");
      return;
    }
    setAsking(true);
    const shared = await requestContact();
    setAsking(false);
    if (shared) setSharedAt(Date.now());
    else setProblem("denied");
  };

  const positionList = positions.data ?? [];
  const nameReady = first.trim() !== "" && last.trim() !== "";
  const positionReady = positions.isSuccess && (positionList.length === 0 || positionId !== null);

  const next = () => {
    if (onboard.isPending) return;
    if (step === 0 && nameReady) {
      haptic();
      goTo(1);
    } else if (step === 1 && phone) {
      haptic();
      goTo(2);
    } else if (step === 2 && positionReady) {
      haptic();
      onboard.mutate(
        { first_name: first.trim(), last_name: last.trim(), position_id: positionId },
        {
          onSuccess: () => haptic("success"),
          onError: (error) => toast((error instanceof ApiError && error.detail) || t("error.generic")),
        },
      );
    }
  };

  const waitingForPhone = asking || (sharedAt !== null && !slow);
  const action: BottomAction =
    step === 0
      ? { text: t("common.continue"), onClick: next, disabled: !nameReady }
      : step === 1
        ? phone
          ? { text: t("common.continue"), onClick: next }
          : {
              text: waitingForPhone ? t("signup.phone.waiting") : slow ? t("signup.phone.again") : t("signup.phone.share"),
              onClick: () => void sharePhone(),
              loading: waitingForPhone,
              icon: Phone,
            }
        : {
            text: onboard.isPending ? t("signup.sending") : membership.status === "pending" ? t("signup.send") : t("signup.finish"),
            onClick: next,
            disabled: !positionReady,
            loading: onboard.isPending,
            shine: true,
          };

  return (
    <>
      <div className="screen screen--plain signup">
        <div className="signup-head">
          <div className="signup-brand">
            <Mark size={26} />
            <span>{membership.company.name}</span>
          </div>
          <div className="signup-progress">
            <span className="signup-step num">{t("signup.step", { n: step + 1 })}</span>
            <span className="signup-bars" aria-hidden>
              {[0, 1, 2].map((index) => (
                <span key={index} className={cx("signup-bar", index <= step && "signup-bar--on")} />
              ))}
            </span>
          </div>
        </div>

        <div key={step} className={cx("signup-body", back ? "enter-back" : "enter")}>
          {step === 0 && (
            <>
              <div className="signup-title">
                <h1 className="heading title-lg">{t("signup.name.title")}</h1>
                <p className="lede">{t("signup.name.lede")}</p>
              </div>
              <div className="field">
                <label htmlFor="first">{t("signup.first")}</label>
                <input
                  id="first"
                  className="input"
                  autoComplete="given-name"
                  autoCapitalize="words"
                  enterKeyHint="next"
                  maxLength={100}
                  value={first}
                  onChange={(event) => setFirst(event.target.value)}
                  onKeyDown={(event) => event.key === "Enter" && lastName.current?.focus()}
                />
              </div>
              <div className="field">
                <label htmlFor="last">{t("signup.last")}</label>
                <input
                  id="last"
                  ref={lastName}
                  className="input"
                  autoComplete="family-name"
                  autoCapitalize="words"
                  enterKeyHint="go"
                  maxLength={100}
                  value={last}
                  onChange={(event) => setLast(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter") return;
                    event.currentTarget.blur();
                    next();
                  }}
                />
              </div>
            </>
          )}

          {step === 1 && (
            <>
              <div className="signup-title">
                <h1 className="heading title-lg">{t("signup.phone.title")}</h1>
                <p className="lede">{t("signup.phone.lede")}</p>
              </div>
              {phone ? (
                <div className="signup-phone signup-phone--done">
                  <span className="circle signup-phone-icon">
                    <Check size={20} strokeWidth={3} />
                  </span>
                  <span className="signup-phone-text">
                    <span className="signup-phone-title num">{formatPhone(phone)}</span>
                    <span className="signup-phone-note">{t("signup.phone.verified")}</span>
                  </span>
                </div>
              ) : (
                <div className={cx("signup-phone", waitingForPhone && "signup-phone--waiting")} aria-live="polite">
                  <span className="circle signup-phone-icon">
                    {waitingForPhone ? <Spinner size={20} /> : <Phone size={20} strokeWidth={2.4} />}
                  </span>
                  <span className="signup-phone-text">
                    <span className="signup-phone-title">{waitingForPhone ? t("signup.phone.waiting") : t("signup.phone.none")}</span>
                    <span className="signup-phone-note">{waitingForPhone ? t("signup.phone.wait") : t("signup.phone.ask")}</span>
                  </span>
                </div>
              )}
              {!phone && (problem || slow) && (
                <p className="signup-note" role="status">
                  {problem === "unsupported" ? t("signup.phone.unsupported") : problem === "denied" ? t("signup.phone.denied") : t("signup.phone.slow")}
                </p>
              )}
            </>
          )}

          {step === 2 && (
            <>
              <div className="signup-title">
                <h1 className="heading title-lg">{t("signup.role.title")}</h1>
                <p className="lede">{positions.isSuccess && positionList.length === 0 ? t("signup.role.none") : t("signup.role.lede")}</p>
              </div>
              {positions.isError ? (
                <LoadError compact error={positions.error} onRetry={() => void positions.refetch()} />
              ) : (
                <div role="radiogroup" aria-label={t("signup.role.title")} className="signup-choices">
                  {positions.isPending && [0, 1, 2].map((index) => <div key={index} className="skeleton signup-choice-skeleton" />)}
                  {positionList.map((position) => (
                    <button
                      key={position.id}
                      className="choice"
                      role="radio"
                      aria-checked={positionId === position.id}
                      onClick={() => {
                        haptic.select();
                        setPositionId(position.id);
                      }}
                    >
                      <span>{position.name}</span>
                      <span className="dot" />
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
      <BottomBar primary={action} />
    </>
  );
}
