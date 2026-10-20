/** The quick sheets over Kassa: payout, handover, the safe, and a single receipt. */
import { ArchiveRestore, ArrowRightLeft, Check, HandCoins, ReceiptText, Undo2, Vault } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { amountFromTyping, isZero } from "../../lib/money";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Avatar, Button, ChipGroup, cx, Field, Input, MoneyInput, NumberPad, PhotoInput, ScreenSkeleton, Segmented, SheetTitle, SlideToConfirm, type SlideState } from "../../ui";
import type { SheetProps } from "../registry";
import { isDenied, tillMethods, useKassa, useMovement, useSale, useVoidSale, type Kassa, type ShiftDetail } from "./api";
import { downscale } from "./image";
import { useKassaT, useMoney } from "./lib";
import { Denied, ErrorScreen, NoShift } from "./parts";

type Body = (props: { kassa: Kassa; shift: ShiftDetail; close: () => void; params: SheetProps["params"] }) => React.ReactNode;

/** Load Kassa (usually cached already) and hand the open shift to the sheet body. */
function withShift(Content: Body) {
  return function KassaSheet({ close, params }: SheetProps) {
    const member = useMember();
    const kassa = useKassa(member.companyId);
    if (kassa.isPending) return <ScreenSkeleton variant="detail" delay={150} />;
    if (kassa.isError) return isDenied(kassa.error) ? <Denied compact /> : <ErrorScreen compact error={kassa.error} retry={() => kassa.refetch()} />;
    if (!kassa.data.shift) return <NoShift onDone={close} />;
    return <Content kassa={kassa.data} shift={kassa.data.shift} close={close} params={params} />;
  };
}

/** Feedback after a write: a buzz, a toast, and the sheet closes. */
function useDone() {
  const toast = useToast();
  const { t: appT } = useI18n();
  return {
    ok: (text: string, close?: () => void) => {
      haptic.notify("success");
      toast(text, { tone: "success" });
      close?.();
    },
    fail: (error: unknown) => {
      haptic.notify("error");
      toast(errorText(error, appT), { tone: "error" });
    },
  };
}

/** Categories a till usually pays for come first. */
const COMMON = ["goods", "transport", "repairs", "utilities", "other_expense"];

const PayoutBody: Body = ({ kassa, shift, close }) => {
  const t = useKassaT();
  const member = useMember();
  const money = useMoney(kassa.settings.currency);
  const done = useDone();
  const move = useMovement(member.companyId, shift.id);
  const [amount, setAmount] = useState("");
  const categories = [...kassa.categories].sort((a, b) => rank(a.code) - rank(b.code));
  const [category, setCategory] = useState<string | null>(categories[0] ? String(categories[0].id) : null);
  const [reason, setReason] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const value = amountFromTyping(amount);
  const valid = Boolean(value && !isZero(value) && reason.trim());

  const submit = async () => {
    if (!value) return;
    move.mutate(
      { kind: "payout", amount: value, category_id: category ? Number(category) : null, reason: reason.trim(), photo: photo ? await downscale(photo) : null },
      { onSuccess: () => done.ok(t("payout.done"), close), onError: done.fail },
    );
  };

  return (
    <>
      <SheetTitle kicker={`${shift.register.name} · ${shift.code}`}>{t("payout.title")}</SheetTitle>
      <Field label={t("payout.amount")}>
        <MoneyInput value={amount} onChange={setAmount} currency={kassa.settings.currency} size="lg" autoFocus />
      </Field>
      {categories.length > 0 && (
        <Field label={t("payout.category")}>
          <ChipGroup scroll value={category} onChange={setCategory} options={categories.map((row) => ({ value: String(row.id), label: row.name }))} label={t("payout.category")} />
        </Field>
      )}
      <Field label={t("payout.reason")}>
        <Input value={reason} onChange={(event) => setReason(event.target.value)} placeholder={t("payout.reasonPlaceholder")} maxLength={200} />
      </Field>
      <Field label={t("payout.photo")} hint={t("payout.photoHint")} optional>
        <PhotoInput value={photo} onChange={setPhoto} capture="environment" label={t("payout.photoCta")} />
      </Field>
      <Button variant="primary" size="lg" block icon={HandCoins} disabled={!valid} loading={move.isPending} onClick={() => void submit()}>
        {value && !isZero(value) ? t("payout.submit", { amount: money(value) }) : t("payout.title")}
      </Button>
    </>
  );
};

const rank = (code: string) => {
  const index = COMMON.indexOf(code);
  return index < 0 ? COMMON.length : index;
};

const HandoverBody: Body = ({ kassa, shift, close }) => {
  const t = useKassaT();
  const member = useMember();
  const money = useMoney(kassa.settings.currency);
  const done = useDone();
  const move = useMovement(member.companyId, shift.id);
  const [amount, setAmount] = useState("");
  const [receiverId, setReceiverId] = useState<number | null>(kassa.receivers.length === 1 ? kassa.receivers[0].id : null);
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [slide, setSlide] = useState<SlideState>("idle");
  const value = amountFromTyping(amount);
  const receiver = kassa.receivers.find((row) => row.id === receiverId) ?? null;
  const valid = Boolean(value && !isZero(value) && receiver);

  if (!kassa.receivers.length) {
    return (
      <>
        <SheetTitle kicker={shift.register.name}>{t("handover.title")}</SheetTitle>
        <p className="kassa-help">{t("handover.nobody")}</p>
      </>
    );
  }

  if (confirming && receiver && value) {
    return (
      <div className="kassa-confirm">
        <Avatar name={receiver.name} size="xl" />
        <div className="heading title-sm kassa-confirm-title num">{t("handover.confirmTitle", { amount: money(value), name: receiver.name })}</div>
        <p className="kassa-confirm-body">{t("handover.confirmBody", { name: receiver.name.split(" ")[0] })}</p>
        <SlideToConfirm
          label={t("handover.slide")}
          doneLabel={t("handover.slideDone")}
          state={slide}
          onConfirm={() => {
            setSlide("loading");
            move.mutate(
              { kind: "handover", amount: value, receiver_id: receiver.id, reason: reason.trim() },
              {
                onSuccess: () => {
                  setSlide("done");
                  done.ok(t("handover.done", { name: receiver.name }), close);
                },
                onError: (error) => {
                  setSlide("idle");
                  done.fail(error);
                },
              },
            );
          }}
        />
        <Button variant="ghost" onClick={() => setConfirming(false)} disabled={slide !== "idle"}>
          {t("handover.edit")}
        </Button>
      </div>
    );
  }

  return (
    <>
      <SheetTitle kicker={`${shift.register.name} · ${shift.code}`}>{t("handover.title")}</SheetTitle>
      <Field label={t("handover.amount")}>
        <MoneyInput value={amount} onChange={setAmount} currency={kassa.settings.currency} size="lg" autoFocus />
      </Field>
      <div className="field">
        <span className="field-label">{t("handover.to")}</span>
        <div className="kassa-people" role="radiogroup" aria-label={t("handover.to")}>
          {kassa.receivers.map((person) => (
            <button
              key={person.id}
              type="button"
              role="radio"
              aria-checked={person.id === receiverId}
              className={cx("kassa-person", person.id === receiverId && "is-selected")}
              onClick={() => {
                haptic.select();
                setReceiverId(person.id);
              }}
            >
              <Avatar name={person.name} size="sm" />
              <span className="row-main">
                <span className="row-title">{person.name}</span>
                {person.role && <span className="row-meta">{person.role}</span>}
              </span>
              <span className="kassa-radio" aria-hidden>
                {person.id === receiverId && <Check size={15} strokeWidth={3.2} />}
              </span>
            </button>
          ))}
        </div>
      </div>
      <Field label={t("handover.reason")} optional>
        <Input value={reason} onChange={(event) => setReason(event.target.value)} placeholder={t("handover.reasonPlaceholder")} maxLength={200} />
      </Field>
      <Button variant="primary" size="lg" block icon={ArrowRightLeft} disabled={!valid} onClick={() => setConfirming(true)}>
        {t("handover.next")}
      </Button>
    </>
  );
};

const SafeBody: Body = ({ kassa, shift, close, params }) => {
  const t = useKassaT();
  const member = useMember();
  const money = useMoney(kassa.settings.currency);
  const done = useDone();
  const move = useMovement(member.companyId, shift.id);
  const [direction, setDirection] = useState<"to_safe" | "from_safe">(params.direction === "from_safe" ? "from_safe" : "to_safe");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const value = amountFromTyping(amount);
  const valid = Boolean(value && !isZero(value));

  return (
    <>
      <SheetTitle kicker={`${shift.branch.name} · ${shift.register.name}`}>{t("safe.title")}</SheetTitle>
      <Segmented
        fit
        value={direction}
        onChange={setDirection}
        label={t("safe.title")}
        options={[
          { value: "to_safe", label: t("safe.to"), icon: Vault },
          { value: "from_safe", label: t("safe.from"), icon: ArchiveRestore },
        ]}
      />
      <Field label={t("safe.amount")}>
        <MoneyInput value={amount} onChange={setAmount} currency={kassa.settings.currency} size="lg" autoFocus />
      </Field>
      <Field label={t("safe.reason")} optional>
        <Input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={200} />
      </Field>
      <Button
        variant="primary"
        size="lg"
        block
        icon={direction === "to_safe" ? Vault : ArchiveRestore}
        disabled={!valid}
        loading={move.isPending}
        onClick={() =>
          value &&
          move.mutate({ kind: direction, amount: value, reason: reason.trim() }, { onSuccess: () => done.ok(t("safe.done"), close), onError: done.fail })
        }
      >
        {valid && value ? t(direction === "to_safe" ? "safe.submitTo" : "safe.submitFrom", { amount: money(value) }) : t("safe.title")}
      </Button>
    </>
  );
};

/**
 * One receipt in receipts mode: the amount on the keypad, the payment method as chips. The sheet
 * stays open for the next customer, with the last receipt and an Undo on top.
 */
const SaleBody: Body = ({ kassa, shift }) => {
  const t = useKassaT();
  const member = useMember();
  const money = useMoney(kassa.settings.currency);
  const done = useDone();
  const sale = useSale(member.companyId);
  const voidSale = useVoidSale(member.companyId);
  const methods = tillMethods(kassa.methods);
  const [kind, setKind] = useState<"sale" | "refund">("sale");
  const [method, setMethod] = useState<string | null>(methods[0] ? String(methods[0].id) : null);
  const [amount, setAmount] = useState("");
  const [last, setLast] = useState<{ id: number; text: string } | null>(null);
  const value = amountFromTyping(amount);
  const valid = Boolean(value && !isZero(value) && method);
  const methodName = methods.find((row) => String(row.id) === method)?.name ?? "";

  if (kassa.settings.mode !== "receipts") return <p className="kassa-help">{t("sale.off")}</p>;

  const submit = () => {
    if (!value || !method) return;
    sale.mutate(
      { kind, payments: [{ method_id: Number(method), amount: value }] },
      {
        onSuccess: (saved) => {
          haptic.notify("success");
          setLast({ id: saved.id, text: t("sale.saved", { amount: `${kind === "refund" ? "−" : ""}${money(value)}`, method: methodName }) });
          setAmount("");
          setKind("sale");
          // The confirmation and its Undo sit at the top of the sheet.
          document.querySelector(".sheet")?.scrollTo?.({ top: 0, behavior: "smooth" });
        },
        onError: done.fail,
      },
    );
  };

  return (
    <>
      <SheetTitle kicker={`${shift.register.name} · ${shift.code}`}>{t("sale.title")}</SheetTitle>
      {last && (
        <div className="kassa-last" role="status">
          <Check size={17} strokeWidth={3} aria-hidden />
          <span className="num">{last.text}</span>
          <button
            type="button"
            className="btn btn-ghost kassa-last-undo"
            disabled={voidSale.isPending}
            onClick={() =>
              voidSale.mutate(
                { id: last.id, reason: t("now.voidReason") },
                {
                  onSuccess: () => {
                    setLast(null);
                    done.ok(t("now.voided"));
                  },
                  onError: done.fail,
                },
              )
            }
          >
            <Undo2 size={15} strokeWidth={2.6} aria-hidden />
            <span>{t("sale.undo")}</span>
          </button>
        </div>
      )}
      <Segmented
        size="small"
        fit
        value={kind}
        onChange={setKind}
        label={t("sale.title")}
        options={[
          { value: "sale", label: t("sale.sale") },
          { value: "refund", label: t("sale.refund") },
        ]}
      />
      <div className="kassa-keep">
        <ChipGroup scroll value={method} onChange={setMethod} options={methods.map((row) => ({ value: String(row.id), label: row.name }))} label={t("sale.method")} />
      </div>
      <NumberPad value={amount} onChange={setAmount} currency={kassa.settings.currency} label={t(kind === "sale" ? "sale.amount" : "sale.refundAmount")} />
      <Button variant="primary" size="lg" block icon={ReceiptText} disabled={!valid} loading={sale.isPending} onClick={submit}>
        {valid && value ? t(kind === "sale" ? "sale.submit" : "sale.submitRefund", { amount: money(value) }) : t("sale.title")}
      </Button>
    </>
  );
};

export const PayoutSheet = withShift(PayoutBody);
export const HandoverSheet = withShift(HandoverBody);
export const SafeSheet = withShift(SafeBody);
export const SaleSheet = withShift(SaleBody);
