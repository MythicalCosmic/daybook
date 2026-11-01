import { Mic, Sparkles } from "lucide-react";

import { givesWork } from "../../api/permissions";
import { useFeatureT } from "../../i18n/feature";
import { useNavigation } from "../../state/navigation";
import { haptic } from "../../telegram";
import { CardButton } from "../../ui";
import { cx } from "../../ui/cx";
import type { PlusTitleProps, SlotProps } from "../registry";
import { entryOf, useAIStatus } from "./api";
import { messages } from "./messages";
import "./ai.css";

type Open = ReturnType<typeof useOpenDraft>;

/** Open the AI sheet: the microphone, or the smart-add box (with what was typed). */
export function useOpenDraft() {
  const navigation = useNavigation();
  return (mode: "voice" | "text", text = "") => {
    haptic.impact(mode === "voice" ? "medium" : "light");
    // Typed text goes straight to the AI (the sheet sends it as it opens); without, the box opens.
    navigation.openSheet({ kind: "feature", feature: "ai", sheet: "draft", params: text ? { mode, text, send: 1 } : { mode } });
  };
}

/** Whether the (+) sheet's "Dictate tasks" shows: the company's voice notes work right now. */
export function useVoiceVisible({ member }: SlotProps): boolean {
  return entryOf(useAIStatus(member.companyId).data).voice;
}

/**
 * Home, for whoever gives work: "Give tasks by voice" and a big microphone (or, where only typed
 * instructions work, the sparkle). The whole card is the button.
 */
export function DictateCard({ member }: SlotProps) {
  const t = useFeatureT(messages);
  const status = useAIStatus(member.companyId);
  const open = useOpenDraft();
  const entry = entryOf(status.data);
  if (!entry.any || !givesWork(member)) return null;
  return (
    <CardButton tone="outline" layout="row" className="ai-home fade-in" onClick={() => open(entry.voice ? "voice" : "text")}>
      <span className="ai-home-text">
        <span className="ai-kicker">
          <Sparkles size={14} strokeWidth={2.6} aria-hidden />
          {t("home.kicker")}
        </span>
        <span className="ai-home-title">{t(entry.voice ? "home.title" : "home.titleText")}</span>
        <span className="ai-home-body">{t(entry.voice ? "home.body" : "home.bodyText")}</span>
      </span>
      <span className="ai-home-mic" aria-hidden>
        <span className="ai-home-mic-ring" />
        {entry.voice ? <Mic size={30} strokeWidth={2.3} /> : <Sparkles size={28} strokeWidth={2.3} />}
      </span>
    </CardButton>
  );
}

/**
 * Beside the (+) sheet's "New task": the sparkle (smart add: what's typed so far becomes tasks,
 * or a box for a longer instruction) and the microphone.
 */
export function PlusTitleTools({ member, text }: PlusTitleProps) {
  const t = useFeatureT(messages);
  const status = useAIStatus(member.companyId);
  const open: Open = useOpenDraft();
  const entry = entryOf(status.data);
  if (!entry.any) return null;
  const typed = text.trim();
  return (
    <span className="ai-plus-tools fade-in">
      {entry.text && (
        <button
          type="button"
          className={cx("ai-tool", typed && "ai-tool--ready")}
          aria-label={t(typed ? "title.smart" : "title.smartEmpty")}
          title={t(typed ? "title.smart" : "title.smartEmpty")}
          onClick={() => open("text", typed)}
        >
          <Sparkles size={20} strokeWidth={2.4} />
        </button>
      )}
      {entry.voice && (
        <button type="button" className="ai-tool ai-tool--mic" aria-label={t("title.mic")} title={t("title.mic")} onClick={() => open("voice")}>
          <Mic size={21} strokeWidth={2.4} />
        </button>
      )}
    </span>
  );
}
