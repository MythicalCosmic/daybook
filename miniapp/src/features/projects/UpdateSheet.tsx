import { useState } from "react";

import { useFeatureT } from "../../i18n/feature";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { BottomBar, Field, SheetTitle, Textarea } from "../../ui";
import type { SheetProps } from "../registry";
import { postUpdate, useRefresh, type Health } from "./api";
import { messages } from "./messages";
import "./projects.css";

const HEALTHS: Health[] = ["on_track", "at_risk", "off_track"];

/** Post a project update: how it's going (three big buttons) and a few lines. */
export default function UpdateSheet({ params, close }: SheetProps) {
  const projectId = Number(params.id) || 0;
  const member = useMember();
  const t = useFeatureT(messages);
  const toast = useToast();
  const refresh = useRefresh(member.companyId);
  const [health, setHealth] = useState<Health>("on_track");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  async function send() {
    setSaving(true);
    try {
      await postUpdate(member.companyId, projectId, health, text.trim());
      haptic.notify("success");
      toast(t("updates.posted"), { tone: "success" });
      void refresh();
      close();
    } catch (error) {
      haptic.notify("error");
      toast((error as { detail?: string | null }).detail ?? t("moveFailed"), { tone: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="prj-sheet">
      <SheetTitle>{t("updates.how")}</SheetTitle>
      <div className="prj-health" role="radiogroup" aria-label={t("updates.how")}>
        {HEALTHS.map((option) => (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={health === option}
            className="prj-health-option"
            onClick={() => {
              haptic.select();
              setHealth(option);
            }}
          >
            <span className={`prj-dot prj-dot--${option}`} aria-hidden />
            {t(`health.${option}`)}
          </button>
        ))}
      </div>
      <Field label={t("updates.text")} optional>
        <Textarea value={text} rows={4} maxLength={4000} placeholder={t("updates.placeholder")} onChange={(event) => setText(event.target.value)} />
      </Field>
      <BottomBar primary={{ text: t("updates.send"), onClick: () => void send(), loading: saving }} />
    </div>
  );
}
