/**
 * The check-in card (Home's hero and the top of the attendance page, plan §1.8): today's shift
 * and a slide to check in or out.
 *
 * A slide asks for the position of that moment only (Telegram's LocationManager, the browser's
 * geolocation as the fallback; nothing is tracked in between), compares it with the branch's
 * geofence like the server does, and then: outside a "flag" fence it asks to confirm, outside a
 * "reject" fence it explains; a company that wants a selfie gets one before the check-in is sent.
 */
import { ChevronRight, Clock3, LogIn, MapPin, MapPinOff, RotateCcw, Settings2, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { useI18n, type Lang } from "../../i18n";
import { errorText } from "../../lib/actions";
import { formatDistance, getLocation, openLocationSettings, type LocationFailure } from "../../lib/location";
import { useNow } from "../../lib/useNow";
import { useMember } from "../../state/session";
import { haptic } from "../../telegram";
import { Badge, Button, Card, CardTitle, IconButton, PhotoInput, Skeleton, SlideToConfirm, useToast, type CardTone, type SlideState } from "../../ui";
import { useCheck, useToday, type Tap } from "./api";
import { fenceCheck, minutesBetween, shiftDay, shiftLine, wallClock, type FenceCheck } from "./lib";
import { duration, useT, whereLabel, type T } from "./text";
import type { CheckResult, MyDay } from "./types";
import "./attendance.css";

type Direction = "in" | "out";

type Step =
  | { kind: "idle" }
  | { kind: "locating"; direction: Direction }
  | { kind: "nowhere"; direction: Direction; reason: LocationFailure; canOpenSettings: boolean }
  | { kind: "outside"; tap: Tap; fence: FenceCheck; reject: boolean }
  | { kind: "selfie"; tap: Tap }
  | { kind: "sending"; direction: Direction }
  | { kind: "failed"; message: string };

const IDLE: Step = { kind: "idle" };

/** How long the knob shows "Checked in" before the card turns to what comes next. */
const DONE_FLASH_MS = 1400;

/** Which way a slide goes in each state (none while the shift hasn't opened or is done). */
function directionOf(day: MyDay): Direction | null {
  if (day.state === "in") return "out";
  if (day.state === "due" || day.state === "late") return "in";
  return null;
}

function hasFence(day: MyDay): boolean {
  return Boolean(day.branch && day.branch.latitude !== null && day.branch.longitude !== null);
}

export function CheckInCard({ onOpen }: { onOpen?: () => void }) {
  const t = useT();
  const { lang, locale } = useI18n();
  const member = useMember();
  const toast = useToast();
  const now = useNow();
  const today = useToday(member.companyId);
  const check = useCheck(member.companyId);
  const [step, setStep] = useState<Step>(IDLE);
  const [flash, setFlash] = useState<Direction | null>(null);
  const [photo, setPhoto] = useState<File | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    if (!flash) return;
    const timer = window.setTimeout(() => setFlash(null), DONE_FLASH_MS);
    return () => window.clearTimeout(timer);
  }, [flash]);

  if (today.isPending) {
    return (
      <Card padding="lg" className="att-hero" aria-busy>
        <Skeleton height={18} width="62%" />
        <Skeleton height={14} width="40%" />
        <Skeleton height={64} radius={999} />
      </Card>
    );
  }
  if (today.isError || !today.data) {
    return (
      <Card padding="lg" className="att-hero">
        <div className="att-hero-box-title">
          <TriangleAlert size={18} strokeWidth={2.5} aria-hidden />
          {t("ui.failed.title")}
        </div>
        <div className="att-hero-actions">
          <Button icon={RotateCcw} onClick={() => today.refetch()}>
            {t("common.retry")}
          </Button>
        </div>
      </Card>
    );
  }

  const day = today.data;
  const natural = directionOf(day);
  const direction = flash ?? (step.kind === "locating" || step.kind === "sending" ? step.direction : natural);

  const send = (dir: Direction, tap: Tap, selfie: File | null) => {
    setStep({ kind: "sending", direction: dir });
    check.mutate(
      { direction: dir, tap, photo: selfie },
      {
        onSuccess: (result) => {
          haptic.notify("success");
          setPhoto(null);
          setStep(IDLE);
          setFlash(dir);
          toast(successText(dir, result));
        },
        onError: (error) => {
          haptic.notify("error");
          setStep({ kind: "failed", message: errorText(error, t) });
        },
      },
    );
  };

  const successText = (dir: Direction, result: CheckResult) => {
    const record = result.record;
    if (dir === "in") return t(result.outside ? "toast.inOutside" : "toast.in", { time: record.check_in_at ? wallClock(record.check_in_at) : "" });
    return t("toast.out", { time: record.check_out_at ? wallClock(record.check_out_at) : "", worked: duration(t, record.worked_minutes) });
  };

  /** After the geofence: a selfie when the company wants one, else straight to the server. */
  const proceed = (dir: Direction, tap: Tap) => {
    if (dir === "in" && day.settings.require_photo) {
      setStep({ kind: "selfie", tap });
      return;
    }
    send(dir, tap, null);
  };

  const start = async (dir: Direction) => {
    const required = day.settings.require_location;
    if (!required && !hasFence(day)) {
      proceed(dir, null);
      return;
    }
    setStep({ kind: "locating", direction: dir });
    const where = await getLocation({ timeoutMs: required ? 15_000 : 8_000 });
    if (!alive.current) return;
    if (!where.ok) {
      if (required) {
        haptic.notify("warning");
        setStep({ kind: "nowhere", direction: dir, reason: where.reason, canOpenSettings: where.canOpenSettings });
        return;
      }
      proceed(dir, null);
      return;
    }
    const tap: Tap = { lat: where.fix.latitude, lng: where.fix.longitude, accuracy: where.fix.accuracy };
    const fence = dir === "in" ? fenceCheck(day.branch, where.fix) : null;
    if (fence?.outside) {
      haptic.notify("warning");
      setStep({ kind: "outside", tap, fence, reject: day.settings.outside_action === "reject" });
      return;
    }
    proceed(dir, tap);
  };

  const slideState: SlideState = flash ? "done" : step.kind === "locating" || step.kind === "sending" ? "loading" : "idle";
  const look = describe(day, now, t, { timeZone: member.timeZone, locale, lang });
  const chevron = onOpen && !natural ? <IconButton icon={ChevronRight} label={t("card.open")} size={36} variant="ghost" onClick={onOpen} /> : null;

  return (
    <Card tone={look.tone} padding="lg" className="att-hero">
      <CardTitle action={chevron}>{look.title}</CardTitle>
      {look.badge && <div className="att-hero-badges">{look.badge}</div>}
      {look.lines.map((line) => (
        <p key={line} className="att-hero-line num">
          {line}
        </p>
      ))}

      {step.kind === "nowhere" ? (
        <div className="att-hero-box" role="alert">
          <div className="att-hero-box-title">
            <MapPinOff size={18} strokeWidth={2.5} aria-hidden />
            {whereLabel(t, step.reason)}
          </div>
          <div className="att-hero-actions">
            {step.canOpenSettings && (
              <Button variant="primary" icon={Settings2} onClick={() => openLocationSettings()}>
                {t("where.settings")}
              </Button>
            )}
            <Button icon={RotateCcw} onClick={() => void start(step.direction)}>
              {t("common.retry")}
            </Button>
            <Button variant="ghost" onClick={() => setStep(IDLE)}>
              {t("action.cancel")}
            </Button>
          </div>
        </div>
      ) : step.kind === "outside" ? (
        <div className="att-hero-box" role="alert">
          <div className="att-hero-box-title">
            <MapPin size={18} strokeWidth={2.5} aria-hidden />
            {t("outside.title", { distance: formatDistance(step.fence.distance, lang), branch: day.branch?.name ?? "" })}
          </div>
          <p className="att-hero-box-body">{t(step.reject ? "outside.rejectBody" : "outside.flagBody")}</p>
          <div className="att-hero-actions">
            {step.reject ? (
              <Button variant="primary" icon={RotateCcw} onClick={() => void start("in")}>
                {t("common.retry")}
              </Button>
            ) : (
              <Button variant="primary" icon={LogIn} onClick={() => proceed("in", step.tap)}>
                {t("outside.confirm")}
              </Button>
            )}
            <Button variant="ghost" onClick={() => setStep(IDLE)}>
              {t("action.cancel")}
            </Button>
          </div>
        </div>
      ) : step.kind === "selfie" ? (
        <div className="att-hero-box">
          <div className="att-hero-box-title">{t("selfie.title")}</div>
          <p className="att-hero-box-body">{t("selfie.body")}</p>
          <PhotoInput value={photo} onChange={setPhoto} capture="user" label={t("selfie.label")} />
          <div className="att-hero-actions">
            <Button variant="primary" icon={LogIn} disabled={!photo} onClick={() => send("in", step.tap, photo)}>
              {t("selfie.send")}
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setPhoto(null);
                setStep(IDLE);
              }}
            >
              {t("action.cancel")}
            </Button>
          </div>
        </div>
      ) : direction ? (
        <>
          <SlideToConfirm
            key={direction}
            label={t(direction === "in" ? "card.slideIn" : "card.slideOut")}
            doneLabel={t(direction === "in" ? "card.checkedIn" : "card.checkedOut")}
            tone={direction === "out" ? "sage" : "accent"}
            state={slideState}
            onConfirm={() => void start(direction)}
          />
          {step.kind === "locating" && <p className="att-hero-status">{t("card.locating")}</p>}
          {step.kind === "failed" && (
            <p className="att-hero-error" role="alert">
              {step.message}
            </p>
          )}
        </>
      ) : day.state === "off" ? (
        <>
          <div className="att-hero-actions">
            <Button icon={LogIn} onClick={() => void start("in")}>
              {t("card.anyway")}
            </Button>
          </div>
          {step.kind === "failed" && (
            <p className="att-hero-error" role="alert">
              {step.message}
            </p>
          )}
        </>
      ) : null}
    </Card>
  );
}

type Look = { tone: CardTone; title: string; lines: string[]; badge?: ReactNode };
type LookContext = { timeZone: string; locale: string; lang: Lang };

/** The card's tone, title, lines and badge for today's state. */
function describe(day: MyDay, now: Date, t: T, { timeZone, locale, lang }: LookContext): Look {
  const { shift, record } = day;
  const next = day.next_shift ? t("card.next", { day: shiftDay(day.next_shift, timeZone, locale), line: shiftLine(day.next_shift) }) : t("card.noNext");
  const shiftTitle = shift ? t("card.shiftTitle", { line: shiftLine(shift) }) : t("card.offTitle");
  switch (day.state) {
    case "in": {
      const since = record?.check_in_at;
      const lines = [
        since && minutesBetween(since, now) > 0 ? t("card.soFar", { time: duration(t, minutesBetween(since, now)) }) : "",
        shift ? t("card.endsAt", { time: shift.end }) : "",
      ].filter(Boolean);
      return {
        tone: "sage",
        title: since ? t("card.inSince", { time: wallClock(since) }) : shiftTitle,
        lines: [lines.join(" · ")].filter(Boolean),
        badge:
          record?.in_distance_m !== null && record?.in_distance_m !== undefined ? (
            <Badge tone="sage" size="small" icon={MapPin}>
              {formatDistance(record.in_distance_m, lang)}
            </Badge>
          ) : undefined,
      };
    }
    case "done": {
      const worked = record?.worked_minutes ?? 0;
      const from = record?.check_in_at ? wallClock(record.check_in_at) : "";
      const to = record?.check_out_at ? wallClock(record.check_out_at) : "";
      return {
        tone: "sage",
        title: t("card.doneTitle"),
        lines: [from && to ? t("card.doneBody", { from, to, time: duration(t, worked) }) : "", next].filter(Boolean),
      };
    }
    case "late":
      return {
        tone: "accent",
        title: shiftTitle,
        lines: [t("card.startsAt", { time: shift?.start ?? "" })],
        badge: shift ? (
          <Badge tone="accent" size="small" icon={Clock3}>
            {t("card.late", { time: duration(t, minutesBetween(shift.starts_at, now)) })}
          </Badge>
        ) : undefined,
      };
    case "due":
      return { tone: "accent", title: shiftTitle, lines: [t("card.startsAt", { time: shift?.start ?? "" })] };
    case "upcoming":
      return {
        tone: "plain",
        title: shiftTitle,
        lines: [shift ? t("card.startsIn", { time: duration(t, minutesBetween(now, shift.starts_at)) }) : ""].filter(Boolean),
      };
    default:
      return { tone: "plain", title: t("card.offTitle"), lines: [next] };
  }
}
