/**
 * Defektura (PLAN-OWNER §14.17): a medicine a customer asked for that we didn't have, so it gets
 * ordered. A catalogue item or the name as the customer said it, how many packs, and the
 * customer's phone for a call-back when it arrives (optional).
 */
import { FilePlus2, Pill, X } from "lucide-react";
import { useState } from "react";

import { useDraftGuard } from "../../lib/useDraftGuard";
import { useMember } from "../../state/session";
import { Button, Field, Input, ListCard, ListRow, SheetTitle, Stepper } from "../../ui";
import type { SheetProps } from "../registry";
import { useFeedback } from "../states";
import { useAddDefektura, useLookup } from "./api";
import { cleanPhone, decimalText } from "./lib";
import { useSettled } from "./parts";
import { useStockT } from "./text";
import "./stock.css";

export default function DefekturaSheet({ params, close }: SheetProps) {
  const t = useStockT();
  const member = useMember();
  const feedback = useFeedback();
  const add = useAddDefektura(member.companyId);
  const presetId = Number(params.product) || null;
  const [picked, setPicked] = useState<{ id: number; name: string } | null>(presetId ? { id: presetId, name: String(params.name ?? "") } : null);
  const [name, setName] = useState(presetId ? "" : String(params.name ?? ""));
  const [packs, setPacks] = useState(1);
  const [phone, setPhone] = useState("");
  useDraftGuard(Boolean((!presetId && name.trim()) || phone.trim()));
  const typed = useSettled(picked ? "" : name, 300);
  const suggestions = useLookup(member.companyId, typed);
  const valid = Boolean(picked || name.trim());

  const submit = () => {
    if (!valid || add.isPending) return;
    add.mutate(
      {
        product: picked?.id ?? null,
        name: picked ? "" : name.trim(),
        packs: decimalText(packs),
        customer_phone: cleanPhone(phone),
      },
      {
        onSuccess: () => {
          feedback.ok(t("defektura.done"));
          close();
        },
        onError: feedback.fail,
      },
    );
  };

  return (
    <>
      <SheetTitle kicker={t("defektura.kicker")}>{t("defektura.title")}</SheetTitle>
      <Field label={t("defektura.item")}>
        {picked ? (
          <div className="stk-picked">
            <Pill size={18} strokeWidth={2.5} aria-hidden />
            <span className="stk-picked-name">{picked.name || t("defektura.fromCatalogue")}</span>
            <Button variant="ghost" icon={X} onClick={() => setPicked(null)}>
              {t("defektura.change")}
            </Button>
          </div>
        ) : (
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder={t("defektura.itemPlaceholder")} maxLength={200} autoFocus />
        )}
      </Field>
      {!picked && suggestions.data && suggestions.data.length > 0 && name.trim().length >= 2 && (
        <section aria-label={t("defektura.fromCatalogue")}>
          <p className="ft-hint">{t("defektura.fromCatalogue")}</p>
          <ListCard>
            {suggestions.data.slice(0, 4).map((row) => (
              <ListRow key={row.id} icon={Pill} title={row.name} subtitle={row.inn || undefined} onClick={() => setPicked({ id: row.id, name: row.name })} />
            ))}
          </ListCard>
        </section>
      )}
      <Field label={t("defektura.packs")}>
        <Stepper value={packs} min={1} max={999} onChange={setPacks} editable label={t("defektura.packs")} />
      </Field>
      <Field label={t("defektura.phone")} hint={t("defektura.phoneHint")} optional>
        <Input type="tel" inputMode="tel" autoComplete="off" value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="+998 90 123 45 67" maxLength={20} />
      </Field>
      <Button variant="primary" size="lg" block icon={FilePlus2} disabled={!valid} loading={add.isPending} onClick={submit}>
        {t("defektura.submit")}
      </Button>
    </>
  );
}
