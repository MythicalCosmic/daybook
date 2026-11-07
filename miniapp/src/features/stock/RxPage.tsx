/**
 * Prescription entry (PLAN-OWNER §14.17): a dispensed prescription medicine into the prescription
 * log, or an invalid prescription with what was wrong. The prescription's number and date, the
 * doctor and the clinic, the e-prescription number where there is one, its kind (which sets how
 * long it is kept), and a photo of the paper prescription the pharmacy keeps. Never the patient's
 * name, ID or PINFL. Shown while the company keeps the prescription log.
 */
import { NotebookPen, Pill, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { dayKey } from "../../lib/time";
import { useDraftGuard } from "../../lib/useDraftGuard";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { BottomBar, Button, Card, DateInput, EmptyState, Field, Input, ListCard, ListRow, LoadError, PageHeader, PhotoInput, Screen, Select, Textarea } from "../../ui";
import type { PageProps } from "../registry";
import { useFeedback } from "../states";
import { RX_KINDS, useLookup, useProduct, useRecordRx, useStockSettings, type RxKind } from "./api";
import { decimalText } from "./lib";
import { QtyInput, RowsSkeleton, useSettled } from "./parts";
import { useStockT } from "./text";
import "./stock.css";

type Picked = { id: number; name: string; units_per_pack: number; part_label: string };

/** What the log flags on a record for the head (`shapes.rx_out`). */
const FLAGS = ["no_e_prescription", "past_validity"] as const;
type Flag = (typeof FLAGS)[number];

export default function RxPage({ params }: PageProps) {
  const t = useStockT();
  const member = useMember();
  const navigation = useNavigation();
  const settings = useStockSettings(member.companyId);
  const preset = Number(params.product) || 0;
  const product = useProduct(member.companyId, preset);
  const header = <PageHeader kicker={member.home_branch?.name ?? member.company.name} title={t("rx.title")} subtitle={t("rx.subtitle")} onBack={navigation.pop} />;
  if (!settings.data || (preset && !product.data && !product.isError)) {
    return (
      <Screen variant="detail">
        {header}
        {settings.isError ? <LoadError error={settings.error} onRetry={() => void settings.refetch()} onBack={navigation.pop} /> : <RowsSkeleton rows={3} />}
      </Screen>
    );
  }
  if (!settings.data.rx_log) {
    return (
      <Screen variant="detail">
        {header}
        <EmptyState icon={NotebookPen} tone="sage" title={t("rx.offTitle")} body={t("rx.offBody")} />
      </Screen>
    );
  }
  const start = product.data?.product.rx_required ? product.data.product : null;
  return <Form header={header} start={start ? { id: start.id, name: start.name, units_per_pack: start.units_per_pack, part_label: start.part_label } : null} />;
}

function Form({ header, start }: { header: ReactNode; start: Picked | null }) {
  const t = useStockT();
  const member = useMember();
  const navigation = useNavigation();
  const feedback = useFeedback();
  const toast = useToast();
  const record = useRecordRx(member.companyId);
  const today = dayKey(new Date(), member.timeZone);
  const [product, setProduct] = useState<Picked | null>(start);
  const [query, setQuery] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [number, setNumber] = useState("");
  const [prescribedOn, setPrescribedOn] = useState(today);
  const [prescriber, setPrescriber] = useState("");
  const [facility, setFacility] = useState("");
  const [eRx, setERx] = useState("");
  const [kind, setKind] = useState<RxKind>("regular");
  const [invalid, setInvalid] = useState(false);
  const [reason, setReason] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  useDraftGuard(Boolean(number.trim() || prescriber.trim() || facility.trim() || eRx.trim() || photo));
  const typed = useSettled(product ? "" : query, 250);
  const found = useLookup(member.companyId, typed);
  const rx = (found.data ?? []).filter((row) => row.rx_required);
  const valid = Boolean(product && quantity > 0 && (!invalid || reason.trim()));

  const save = () => {
    if (!product || !valid || record.isPending) return;
    record.mutate(
      {
        product: product.id,
        quantity: decimalText(quantity),
        prescription_number: number.trim(),
        prescribed_on: prescribedOn,
        prescriber: prescriber.trim(),
        facility: facility.trim(),
        e_prescription_id: eRx.trim(),
        rx_kind: kind,
        status: invalid ? "invalid" : "dispensed",
        invalid_reason: invalid ? reason.trim() : "",
        photo,
      },
      {
        onSuccess: (saved) => {
          // One toast shows at a time: what the head will see flagged goes with the "recorded".
          const flags = (saved.flags ?? []).filter((flag): flag is Flag => FLAGS.includes(flag as Flag)).map((flag) => t(`rx.flag.${flag}`));
          if (flags.length) {
            haptic.notify("warning");
            toast([t("rx.done"), ...flags].join(". "), { duration: 5000 });
          } else {
            feedback.ok(t("rx.done"));
          }
          navigation.pop();
        },
        onError: feedback.fail,
      },
    );
  };

  return (
    <Screen variant="detail">
      {header}
      <Card className="stk-form">
        <Field label={t("rx.product")}>
          {product ? (
            <div className="stk-picked">
              <Pill size={18} strokeWidth={2.5} aria-hidden />
              <span className="stk-picked-name">{product.name}</span>
              <Button variant="ghost" icon={X} onClick={() => setProduct(null)}>
                {t("defektura.change")}
              </Button>
            </div>
          ) : (
            <Input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("rx.pickProduct")} aria-label={t("rx.product")} autoComplete="off" />
          )}
        </Field>
        {!product && typed.trim().length >= 2 && found.data && (
          rx.length ? (
            <ListCard>
              {rx.slice(0, 5).map((row) => (
                <ListRow key={row.id} icon={Pill} title={row.name} subtitle={row.inn || undefined} onClick={() => setProduct({ id: row.id, name: row.name, units_per_pack: row.units_per_pack, part_label: row.part_label })} />
              ))}
            </ListCard>
          ) : (
            <p className="ft-hint">{t("rx.notRx")}</p>
          )
        )}
        {product && (
          <Field label={t("rx.quantity")}>
            <QtyInput label={t("rx.quantity")} value={quantity} onChange={(parts) => setQuantity(Math.max(1, parts))} unitsPerPack={product.units_per_pack} partLabel={product.part_label} />
          </Field>
        )}
        <Field label={t("rx.number")} optional>
          <Input value={number} onChange={(event) => setNumber(event.target.value)} maxLength={40} autoComplete="off" />
        </Field>
        <Field label={t("rx.date")}>
          <DateInput value={prescribedOn} onChange={setPrescribedOn} label={t("rx.date")} max={today} today={today} />
        </Field>
        <Field label={t("rx.prescriber")} optional>
          <Input value={prescriber} onChange={(event) => setPrescriber(event.target.value)} maxLength={120} autoComplete="off" />
        </Field>
        <Field label={t("rx.facility")} optional>
          <Input value={facility} onChange={(event) => setFacility(event.target.value)} maxLength={120} autoComplete="off" />
        </Field>
        <Field label={t("rx.eRx")} optional>
          <Input value={eRx} onChange={(event) => setERx(event.target.value)} maxLength={64} autoComplete="off" />
        </Field>
        <Field label={t("rx.kind")}>
          <Select value={kind} onChange={(event) => setKind(event.target.value as RxKind)}>
            {RX_KINDS.map((value) => (
              <option key={value} value={value}>
                {t(`rxKind.${value}`)}
              </option>
            ))}
          </Select>
        </Field>
        <label className="stk-check">
          <input type="checkbox" checked={invalid} onChange={(event) => setInvalid(event.target.checked)} />
          <span>{t("rx.invalid")}</span>
        </label>
        {invalid && (
          <Field label={t("rx.invalidReason")}>
            <Textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={200} />
          </Field>
        )}
        <Field label={t("rx.photo")} hint={t("rx.photoHint")} optional={kind === "regular"}>
          <PhotoInput value={photo} onChange={setPhoto} capture="environment" label={t("photo.cta")} />
        </Field>
      </Card>
      <BottomBar primary={{ text: t("rx.save"), icon: NotebookPen, onClick: save, loading: record.isPending, disabled: !valid }} />
    </Screen>
  );
}
