import { useQueryClient } from "@tanstack/react-query";
import { Check, ChevronRight, CircleAlert, EyeOff, FileText, RotateCw, ShieldCheck, WifiOff } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { amountFromTyping, compareMoney, isZero, subtractMoney, sumMoney, type DecimalString } from "../../lib/money";
import { clock } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { confirm, haptic } from "../../telegram";
import {
  Banner,
  BottomBar,
  Button,
  Card,
  CardTitle,
  countedTotal,
  cx,
  Field,
  Input,
  MoneyText,
  NumberPad,
  PageHeader,
  PhotoInput,
  Screen,
  ScreenSkeleton,
  Segmented,
  SlideToConfirm,
  Textarea,
} from "../../ui";
import type { PageProps } from "../registry";
import { closeShift, fetchShift, isDenied, isNetworkError, kassaKeys, tillMethods, useKassa, useShift, type Kassa, type PaymentLine, type ShiftDetail } from "./api";
import { clearDraft, emptyDraft, STEPS, useCloseDraft, type CloseDraft, type Line, type PhotoKind, type Step } from "./draft";
import { downscale } from "./image";
import { digits, useKassaT, useMoney, type KassaT } from "./lib";
import { CashCount, Denied, ErrorScreen, Line as Row, Lines } from "./parts";

/**
 * Closing a shift, in four steps: sales per payment method on the keypad, the Z-report and
 * terminal slip photos, the blind cash count, then a last look and a slide to close. Every
 * keystroke is kept on the phone, and a close that can't get through is retried until it does.
 */
export default function ClosePage({ params }: PageProps) {
  const member = useMember();
  const shiftId = Number(params.id);
  const kassa = useKassa(member.companyId);
  const [result, setResult] = useState<ShiftDetail | null>(null);
  if (result) return <CloseResult shift={result} kassa={kassa.data ?? null} />;
  if (kassa.isPending) {
    return (
      <Screen variant="detail">
        <ScreenSkeleton variant="detail" delay={150} />
      </Screen>
    );
  }
  if (kassa.isError) {
    return <Screen variant="detail">{isDenied(kassa.error) ? <Denied /> : <ErrorScreen error={kassa.error} retry={() => kassa.refetch()} />}</Screen>;
  }
  const shift = kassa.data.shift;
  if (!shift || shift.id !== shiftId) return <AlreadyClosed shiftId={shiftId} kassa={kassa.data} />;
  return <CloseWizard kassa={kassa.data} shift={shift} onClosed={setResult} />;
}

/** The shift isn't open any more (closed on another phone, or by a manager). */
function AlreadyClosed({ shiftId, kassa }: { shiftId: number; kassa: Kassa }) {
  const member = useMember();
  const shift = useShift(member.companyId, shiftId);
  if (shift.isPending) {
    return (
      <Screen variant="detail">
        <ScreenSkeleton variant="detail" delay={150} />
      </Screen>
    );
  }
  if (shift.isError) return <Screen variant="detail">{isDenied(shift.error) ? <Denied /> : <ErrorScreen error={shift.error} retry={() => shift.refetch()} />}</Screen>;
  return <CloseResult shift={shift.data} kassa={kassa} />;
}

const DELAYS = [3_000, 8_000, 20_000, 45_000, 60_000];
type SendState = "idle" | "sending" | "waiting" | "failed";

/**
 * Send the close, and keep sending it while the network is the problem: backing off, and at
 * once when the phone says it is online again. The server answers a repeated close of the same
 * shift with the shift itself, so a retry after a lost answer is harmless.
 */
function useCloseSubmit(
  company: number,
  shiftId: number,
  handlers: { build: () => Parameters<typeof closeShift>[2]; onDone: (shift: ShiftDetail) => void; setPending: (pending: boolean) => void },
) {
  const { t: appT } = useI18n();
  const [state, setState] = useState<SendState>("idle");
  const [error, setError] = useState<string | null>(null);
  const current = useRef<SendState>("idle");
  const attempts = useRef(0);
  const timer = useRef<number | undefined>(undefined);
  const latest = useRef(handlers);
  latest.current = handlers;
  const move = (next: SendState) => {
    current.current = next;
    setState(next);
  };

  const send = useCallback(async (): Promise<void> => {
    window.clearTimeout(timer.current);
    if (current.current === "sending") return;
    move("sending");
    setError(null);
    latest.current.setPending(true);
    try {
      const shift = await closeShift(company, shiftId, latest.current.build());
      attempts.current = 0;
      move("idle");
      latest.current.onDone(shift);
    } catch (failure) {
      if (isNetworkError(failure)) {
        const delay = DELAYS[Math.min(attempts.current, DELAYS.length - 1)];
        attempts.current += 1;
        move("waiting");
        timer.current = window.setTimeout(() => void send(), delay);
        return;
      }
      // A "no" may come from an earlier try that did close the shift: then it's done.
      try {
        const shift = await fetchShift(company, shiftId);
        if (shift.status !== "open") {
          move("idle");
          latest.current.onDone(shift);
          return;
        }
      } catch {
        // Keep the first answer.
      }
      latest.current.setPending(false);
      setError(errorText(failure, appT));
      move("failed");
    }
  }, [company, shiftId, appT]);

  useEffect(() => {
    const online = () => {
      if (current.current === "waiting") void send();
    };
    window.addEventListener("online", online);
    return () => {
      window.removeEventListener("online", online);
      window.clearTimeout(timer.current);
    };
  }, [send]);

  return { state, error, send };
}

const amountOf = (typing: string): DecimalString => amountFromTyping(typing) ?? "0";

function freshDraft(kassa: Kassa, shift: ShiftDetail): CloseDraft {
  // Receipts mode starts from what the receipts add up to; the cashier corrects from the Z-report.
  const lines: Record<string, Line> = {};
  if (kassa.settings.mode === "receipts") {
    for (const [id, totals] of Object.entries(shift.receipts_recorded)) {
      lines[id] = { sales: isZero(totals.sales) ? "" : String(Number(totals.sales)), refunds: isZero(totals.refunds) ? "" : String(Number(totals.refunds)) };
    }
  }
  return emptyDraft(lines, tillMethods(kassa.methods)[0]?.id ?? null);
}

function CloseWizard({ kassa, shift, onClosed }: { kassa: Kassa; shift: ShiftDetail; onClosed: (shift: ShiftDetail) => void }) {
  const t = useKassaT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const client = useQueryClient();
  const currency = kassa.settings.currency;
  const money = useMoney(currency);
  const fresh = useCallback(() => freshDraft(kassa, shift), [kassa, shift]);
  const store = useCloseDraft(member.companyId, shift.id, fresh);
  const { draft, update, photos } = store;
  const [field, setField] = useState<keyof Line>("sales");
  const latestPhotos = useRef(photos);
  latestPhotos.current = photos;

  const methods = tillMethods(kassa.methods);
  const lineOf = (id: number): Line => draft.lines[String(id)] ?? { sales: "", refunds: "" };
  const netOf = (id: number) => subtractMoney(amountOf(lineOf(id).sales), amountOf(lineOf(id).refunds));
  const net = sumMoney(methods.map((method) => netOf(method.id)));
  const takesCards = methods.some((method) => (method.kind === "card" || method.kind === "qr") && !isZero(amountOf(lineOf(method.id).sales)));
  const counted = draft.typedCash !== null ? amountOf(draft.typedCash) : countedTotal(draft.counts);
  const needZ = kassa.settings.require_z_photo && !photos.z;
  const needTerminal = kassa.settings.require_terminal_photo && takesCards && !photos.terminal;
  const selected = methods.find((method) => method.id === draft.method) ?? methods[0];
  const nextMethod = selected ? methods[methods.indexOf(selected) + 1] : undefined;
  const strip = useRef<HTMLDivElement>(null);
  const choose = (id: number) => {
    haptic.select();
    update({ method: id });
    setField("sales");
  };
  // Keep the method being typed in view as the strip scrolls sideways.
  useEffect(() => {
    strip.current?.querySelector<HTMLElement>(".kassa-method.is-selected")?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [selected?.id]);

  const payments: PaymentLine[] = methods
    .map((method) => ({ method_id: method.id, sales: amountOf(lineOf(method.id).sales), refunds: amountOf(lineOf(method.id).refunds) }))
    .filter((line) => !isZero(line.sales) || !isZero(line.refunds));

  const submit = useCloseSubmit(member.companyId, shift.id, {
    build: () => ({
      payments,
      closing_count: draft.typedCash === null ? draft.counts : undefined,
      counted_cash: counted,
      receipts: draft.receipts ? Number(draft.receipts) : null,
      z_number: draft.zNumber.trim(),
      note: draft.note.trim(),
      z_photo: photos.z,
      terminal_photo: takesCards ? photos.terminal : null,
    }),
    onDone: (closed) => {
      clearDraft(member.companyId, shift.id);
      haptic.notify("success");
      void client.invalidateQueries({ queryKey: kassaKeys.all(member.companyId) });
      onClosed(closed);
    },
    setPending: (pending) => update({ pending }),
  });

  // A close that didn't get through before a reload goes again as soon as the screen is back.
  const resumed = useRef(false);
  const send = submit.send;
  useEffect(() => {
    if (draft.pending && !resumed.current) {
      resumed.current = true;
      void send();
    }
  }, [draft.pending, send]);

  const go = (step: Step) => {
    update({ step });
    haptic.select();
    document.querySelector(".kassa-close-screen")?.scrollTo?.({ top: 0 });
  };
  const index = STEPS.indexOf(draft.step);

  const pick = (kind: PhotoKind) => (file: File | null) => {
    store.setPhoto(kind, file);
    if (!file) return;
    void downscale(file).then((small) => {
      if (small !== file && latestPhotos.current[kind] === file) store.setPhoto(kind, small);
    });
  };

  const setLine = (value: string) => {
    if (!selected) return;
    update((old) => ({ lines: { ...old.lines, [String(selected.id)]: { ...(old.lines[String(selected.id)] ?? { sales: "", refunds: "" }), [field]: value } } }));
  };

  const next = async () => {
    if (draft.step === "sales") go("z");
    else if (draft.step === "z") go("cash");
    else if (draft.step === "cash") {
      if (isZero(counted) && !(await confirm(t("close.emptyAsk")))) return;
      go("review");
    }
  };

  const busy = submit.state === "sending" || submit.state === "waiting";
  const stepLabels: Record<Step, string> = { sales: t("close.step.sales"), z: t("close.step.z"), cash: t("close.step.cash"), review: t("close.step.review") };
  const primary: Record<Exclude<Step, "review">, { text: string; disabled?: boolean }> = {
    sales: { text: t("close.next.z") },
    z: { text: t("close.next.cash"), disabled: needZ || needTerminal },
    cash: { text: t("close.next.review") },
  };

  return (
    <>
      <Screen variant="detail" className="kassa-close-screen">
        <PageHeader
          kicker={`${shift.register.name} · ${t("close.stepOf", { step: index + 1, total: STEPS.length })}`}
          title={t("close.title", { code: shift.code })}
          onBack={navigation.pop}
        />
        <ol className="kassa-steps" aria-label={t("close.stepOf", { step: index + 1, total: STEPS.length })}>
          {STEPS.map((step, position) => (
            <li key={step}>
              <button
                type="button"
                className={cx("kassa-step", position < index && "is-done", position === index && "is-current")}
                disabled={position > index || busy}
                aria-current={position === index ? "step" : undefined}
                onClick={() => go(step)}
              >
                <span className="kassa-step-dot">{position < index ? <Check size={13} strokeWidth={3.4} aria-hidden /> : position + 1}</span>
                <span className="kassa-step-label">{stepLabels[step]}</span>
              </button>
            </li>
          ))}
        </ol>

        {store.restoredAt && (
          <div className="kassa-restored">
            <FileText size={16} strokeWidth={2.5} aria-hidden />
            <span className="num">{t("close.restored", { time: clock(store.restoredAt, member.timeZone, locale) })}</span>
            <button
              type="button"
              className="btn btn-ghost kassa-restored-reset"
              onClick={async () => {
                if (await confirm(t("close.startOverAsk"))) store.reset();
              }}
            >
              {t("close.startOver")}
            </button>
          </div>
        )}

        {draft.step === "sales" && selected && (
          <>
            <p className="kassa-help">{t("close.salesHint")}</p>
            <div className="kassa-methods" role="tablist" aria-label={t("close.salesTitle")} ref={strip}>
              {methods.map((method) => {
                const line = lineOf(method.id);
                const filled = Boolean(line.sales || line.refunds);
                return (
                  <button
                    key={method.id}
                    type="button"
                    role="tab"
                    aria-selected={method.id === selected.id}
                    className={cx("kassa-method", method.id === selected.id && "is-selected", filled && "is-filled")}
                    onClick={() => choose(method.id)}
                  >
                    <span className="kassa-method-name">{method.name}</span>
                    <span className="kassa-method-amount num">{filled ? money(netOf(method.id), { bare: true }) : "—"}</span>
                  </button>
                );
              })}
            </div>
            <div className="kassa-pad-tools">
              <Segmented
                size="small"
                label={selected.name}
                value={field}
                onChange={setField}
                options={[
                  { value: "sales", label: t("close.sales") },
                  { value: "refunds", label: t("close.refunds") },
                ]}
              />
              {nextMethod && (
                <button type="button" className="btn btn-ghost kassa-next-method" onClick={() => choose(nextMethod.id)}>
                  <span>{nextMethod.name}</span>
                  <ChevronRight size={17} strokeWidth={2.6} aria-hidden />
                </button>
              )}
            </div>
            <NumberPad
              value={lineOf(selected.id)[field]}
              onChange={setLine}
              currency={currency}
              label={t(field === "sales" ? "close.salesOf" : "close.refundsOf", { method: selected.name })}
              hint={
                kassa.settings.mode === "receipts" && shift.receipts_recorded[String(selected.id)]
                  ? t("close.recorded", { amount: money(shift.receipts_recorded[String(selected.id)][field]) })
                  : t("close.fromZ")
              }
            />
            <div className="kassa-net">
              <span>{t("close.net")}</span>
              <MoneyText amount={net} currency={currency} size="lg" />
            </div>
          </>
        )}

        {draft.step === "z" && (
          <>
            <Field label={t("close.zPhoto")} hint={photos.z ? undefined : kassa.settings.require_z_photo ? t("close.required") : t("close.optionalPhoto")}>
              <PhotoInput value={photos.z} onChange={pick("z")} capture="environment" label={t("close.zPhotoCta")} />
            </Field>
            <div className="kassa-two">
              <Field label={t("close.zNumber")}>
                <Input inputMode="numeric" value={draft.zNumber} onChange={(event) => update({ zNumber: event.target.value.slice(0, 32) })} num />
              </Field>
              <Field label={t("close.receipts")}>
                <Input inputMode="numeric" value={draft.receipts} onChange={(event) => update({ receipts: digits(event.target.value) })} num />
              </Field>
            </div>
            {takesCards && (
              <Field
                label={t("close.terminalPhoto")}
                hint={photos.terminal ? undefined : kassa.settings.require_terminal_photo ? t("close.required") : t("close.optionalPhoto")}
              >
                <PhotoInput value={photos.terminal} onChange={pick("terminal")} capture="environment" label={t("close.terminalPhotoCta")} />
              </Field>
            )}
            {(needZ || needTerminal) && <p className="kassa-help kassa-help--alert">{needZ ? t("close.needZ") : t("close.needTerminal")}</p>}
          </>
        )}

        {draft.step === "cash" && (
          <>
            {kassa.settings.blind_cash_count ? (
              <Banner tone="sage" icon={EyeOff} title={t("close.blindTitle")} body={t("close.blindBody")} />
            ) : (
              <p className="kassa-help">{t("close.cashHint")}</p>
            )}
            <CashCount
              counts={draft.counts}
              onCounts={(counts) => update({ counts })}
              typed={draft.typedCash}
              onTyped={(typedCash) => update({ typedCash })}
              currency={currency}
              label={t("close.counted")}
            />
          </>
        )}

        {draft.step === "review" && (
          <Review
            kassa={kassa}
            draft={draft}
            net={net}
            counted={counted}
            photos={photos}
            takesCards={takesCards}
            onEdit={go}
            onNote={(note) => update({ note })}
            t={t}
          />
        )}
        {draft.step === "review" && submit.state === "waiting" && (
          <div className="kassa-offline" role="status">
            <Banner tone="accent" icon={WifiOff} title={t("close.offlineTitle")} body={t("close.offlineBody")} />
            <Button icon={RotateCw} onClick={() => void submit.send()}>
              {t("close.retry")}
            </Button>
          </div>
        )}
        {draft.step === "review" && submit.state === "failed" && submit.error && <Banner tone="accent" icon={CircleAlert} title={submit.error} />}
      </Screen>
      {draft.step === "review" && (
        <div className="action-bar kassa-slide">
          <SlideToConfirm label={t("close.slide")} doneLabel={t("close.sending")} state={busy ? "loading" : "idle"} onConfirm={() => void submit.send()} />
        </div>
      )}
      {draft.step !== "review" && (
        <BottomBar
          primary={{ text: primary[draft.step].text, disabled: primary[draft.step].disabled, onClick: () => void next() }}
          secondary={index > 0 ? { text: t("close.back"), onClick: () => go(STEPS[index - 1]) } : undefined}
        />
      )}
    </>
  );
}

function Review({
  kassa,
  draft,
  net,
  counted,
  photos,
  takesCards,
  onEdit,
  onNote,
  t,
}: {
  kassa: Kassa;
  draft: CloseDraft;
  net: DecimalString;
  counted: DecimalString;
  photos: Record<PhotoKind, File | null>;
  takesCards: boolean;
  onEdit: (step: Step) => void;
  onNote: (note: string) => void;
  t: KassaT;
}) {
  const currency = kassa.settings.currency;
  const money = useMoney(currency);
  const lines = kassa.methods
    .map((method) => ({ method, line: draft.lines[String(method.id)] ?? { sales: "", refunds: "" } }))
    .filter(({ line }) => line.sales || line.refunds);
  const edit = (step: Step) => (
    <button type="button" className="btn btn-ghost kassa-edit" onClick={() => onEdit(step)}>
      {t("close.edit")}
    </button>
  );
  return (
    <>
      <Card>
        <CardTitle action={edit("sales")}>{t("close.reviewSales")}</CardTitle>
        <Lines>
          {lines.length ? (
            lines.map(({ method, line }) => (
              <Row key={method.id} label={method.name}>
                {money(amountOf(line.sales))}
                {line.refunds ? <span className="kassa-refund"> −{money(amountOf(line.refunds), { bare: true })}</span> : null}
              </Row>
            ))
          ) : (
            <Row label={t("close.noSales")}>{money("0")}</Row>
          )}
          <Row label={t("close.net")} strong>
            {money(net)}
          </Row>
        </Lines>
      </Card>
      <Card>
        <CardTitle action={edit("z")}>{t("close.reviewDetails")}</CardTitle>
        <Lines>
          <Row label={t("close.receipts")}>{draft.receipts || "—"}</Row>
          <Row label={t("close.zNumber")}>{draft.zNumber || "—"}</Row>
        </Lines>
        <div className="kassa-photos">
          <PhotoChip label={t("close.zPhoto")} file={photos.z} t={t} />
          {takesCards && <PhotoChip label={t("close.terminalPhoto")} file={photos.terminal} t={t} />}
        </div>
      </Card>
      <Card tone="sage" className="kassa-counted">
        <CardTitle action={edit("cash")}>{t("close.counted")}</CardTitle>
        <MoneyText amount={counted} currency={currency} size="hero" />
        {kassa.settings.blind_cash_count && <span className="kassa-counted-hint">{t("close.countedHint")}</span>}
      </Card>
      <Field label={t("close.note")} optional>
        <Textarea rows={3} value={draft.note} maxLength={2000} placeholder={t("close.notePlaceholder")} onChange={(event) => onNote(event.target.value)} />
      </Field>
    </>
  );
}

function PhotoChip({ label, file, t }: { label: string; file: File | null; t: KassaT }) {
  // Made and revoked in one effect, so StrictMode's extra mount never leaves a revoked URL behind.
  const [preview, setPreview] = useState<string | null>(null);
  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  return (
    <span className={cx("kassa-photo-chip", !file && "kassa-photo-chip--missing")}>
      {preview ? <img src={preview} alt="" /> : <span className="kassa-photo-none" aria-hidden />}
      <span className="kassa-photo-chip-text">
        <span>{label}</span>
        <span className="muted">{file ? t("close.photoAdded") : t("close.noPhoto")}</span>
      </span>
    </span>
  );
}

/** After the close: what was handed in, and what happens next. */
function CloseResult({ shift, kassa }: { shift: ShiftDetail; kassa: Kassa | null }) {
  const t = useKassaT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const currency = kassa?.settings.currency ?? "UZS";
  const money = useMoney(currency);
  const net = sumMoney(shift.payments.map((line) => subtractMoney(line.sales, line.refunds)));
  const difference = shift.difference;
  const shown = difference !== null;
  return (
    <>
      <Screen variant="detail" className="kassa-result">
        <div className="kassa-result-mark" aria-hidden>
          <span className="kassa-result-ring" />
          <Check size={44} strokeWidth={3} />
        </div>
        <h1 className="heading title-md kassa-result-title">{t("result.title")}</h1>
        <p className="subline num kassa-result-sub">
          {t("result.sub", { code: shift.code, till: shift.register.name, time: shift.closed_at ? clock(shift.closed_at, member.timeZone, locale) : "" })}
        </p>
        <Card>
          <Lines>
            <Row label={t("result.net")}>{money(net)}</Row>
            <Row label={t("result.receipts")}>{shift.receipts}</Row>
            <Row label={t("result.counted")} strong>
              {money(shift.counted_cash)}
            </Row>
            {shown && shift.expected_cash !== null && <Row label={t("result.expected")}>{money(shift.expected_cash)}</Row>}
          </Lines>
        </Card>
        {shown ? (
          isZero(difference) ? (
            <Banner tone="sage" icon={ShieldCheck} title={t("result.exact")} />
          ) : (
            <Banner
              tone={compareMoney(difference, "0") < 0 ? "accent" : "plain"}
              icon={CircleAlert}
              title={compareMoney(difference, "0") < 0 ? t("result.short", { amount: money(difference.replace(/^-/, "")) }) : t("result.over", { amount: money(difference) })}
              body={t("result.differenceBody")}
            />
          )
        ) : (
          <Banner tone="sage" icon={ShieldCheck} title={t("result.blindTitle")} body={t("result.blindBody")} />
        )}
      </Screen>
      <BottomBar primary={{ text: t("result.done"), icon: Check, onClick: () => navigation.reset({ tab: "home" }) }} />
    </>
  );
}
