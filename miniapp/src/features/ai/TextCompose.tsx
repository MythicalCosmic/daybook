import { Sparkles } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { useFeatureT } from "../../i18n/feature";
import { errorText } from "../../lib/actions";
import { useDraftGuard } from "../../lib/useDraftGuard";
import { useMember } from "../../state/session";
import { haptic } from "../../telegram";
import { BottomBar } from "../../ui";
import { refusalOf, TEXT_MAX, useCreateDraft, type AIDraft } from "./api";
import { messages } from "./messages";
import { AIOff, Working } from "./States";

/**
 * Smart add: several people's work written as one text ("Alisher checks the fridge tomorrow
 * morning, Bekzod counts the till tonight") becomes the same review a voice note gets.
 */
export function TextCompose({
  initial,
  send = false,
  onSent,
  onClose,
}: {
  initial: string;
  /** Send `initial` at once (the (+) sheet's sparkle with a title typed): the box shows only on a refusal. */
  send?: boolean;
  onSent: (draft: AIDraft) => void;
  onClose: () => void;
}) {
  const t = useFeatureT(messages);
  const member = useMember();
  const ids = useId();
  const create = useCreateDraft(member.companyId);
  const [text, setText] = useState(initial);
  const trimmed = text.trim();
  const sentOnce = useRef(false);
  useDraftGuard(Boolean(trimmed) && trimmed !== initial.trim());

  const submit = () => {
    if (!trimmed || create.isPending) return;
    haptic.impact("light");
    create.mutate({ text: trimmed }, { onSuccess: onSent });
  };

  // Once, even when React runs effects twice in development.
  useEffect(() => {
    if (!send || sentOnce.current || !initial.trim()) return;
    sentOnce.current = true;
    submit();
  }, []);

  const refusal = create.isError ? refusalOf(create.error) : null;
  if (refusal === "ai_off") return <AIOff onClose={onClose} />;
  // Sending what was typed: the box only comes back when the server says no.
  if (send && initial.trim() && !create.isError) return <Working phase="sending" voice={false} />;

  return (
    <div className="ai-stage ai-text fade-in">
      <div className="ai-review-head">
        <div className="ui-kicker">
          <Sparkles size={14} strokeWidth={2.6} aria-hidden /> {t("home.kicker")}
        </div>
        <div className="heading title-sm">{t("text.title")}</div>
        <p className="ai-rec-lead">{t("text.lead")}</p>
      </div>
      <div className="field">
        <label htmlFor={`${ids}-text`}>{t("text.label")}</label>
        <textarea
          id={`${ids}-text`}
          className="input plus-grow ai-text-box"
          rows={5}
          maxLength={TEXT_MAX}
          autoFocus
          placeholder={t("text.placeholder")}
          value={text}
          aria-invalid={create.isError || undefined}
          onChange={(event) => {
            if (create.isError) create.reset();
            setText(event.target.value);
            const box = event.target;
            box.style.height = "auto";
            box.style.height = `${Math.min(box.scrollHeight, 320)}px`;
          }}
        />
        {text.length > TEXT_MAX - 200 && <span className="field-count num">{`${text.length}/${TEXT_MAX}`}</span>}
        {create.isError && (
          <span className="ui-field-error" role="alert">
            {refusal ? t(`refusal.${refusal}`) : errorText(create.error, t)}
          </span>
        )}
      </div>
      <BottomBar primary={{ text: t("text.submit"), icon: Sparkles, disabled: !trimmed, loading: create.isPending, shine: true, onClick: submit }} />
    </div>
  );
}
