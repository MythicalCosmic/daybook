import { Check, Mic, MicOff, PenLine, RotateCw, Send } from "lucide-react";
import { useEffect, useRef } from "react";

import { useFeatureT } from "../../i18n/feature";
import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { useMember } from "../../state/session";
import { haptic, openTelegramLink } from "../../telegram";
import { Button } from "../../ui";
import { cx } from "../../ui/cx";
import { refusalOf, useCreateDraft, type AIDraft, type AIStatus } from "./api";
import { messages } from "./messages";
import { formatClock, useRecorder, type Recorder } from "./recorder";
import { AIOff, StateView, Working } from "./States";

/** Seconds before the limit when the timer starts counting down in words. */
const WARN_SECONDS = 10;

/**
 * Speak, then Done: the microphone starts as the sheet opens (a tap on a mic means "I want to
 * talk"), the level meter and the timer move while it listens, and the note goes up as soon as it
 * stops (at Done, or by itself at the company's limit).
 */
export function VoiceCompose({
  status,
  onSent,
  onType,
  onCancel,
}: {
  status: AIStatus;
  onSent: (draft: AIDraft) => void;
  /** Typing instead, where the company allows smart text. */
  onType: (() => void) | null;
  onCancel: () => void;
}) {
  const t = useFeatureT(messages);
  const { lang } = useI18n();
  const member = useMember();
  const recorder = useRecorder(status.max_seconds);
  const create = useCreateDraft(member.companyId);
  const sentFor = useRef<Blob | null>(null);

  // Start listening at once; leaving the sheet stops the microphone (useRecorder's cleanup).
  useEffect(() => {
    void recorder.start();
    // Only when the sheet opens.
  }, []);

  // Stopped with a recording: send it, once per recording.
  const recording = recorder.recording;
  useEffect(() => {
    if (!recording || sentFor.current === recording.blob) return;
    sentFor.current = recording.blob;
    create.mutate(
      { voice: { blob: recording.blob, seconds: recording.seconds, fileName: recording.fileName, language: lang } },
      { onSuccess: onSent },
    );
  }, [recording]);

  if (recorder.phase === "denied" || recorder.phase === "unsupported" || recorder.phase === "failed") {
    return <Fallback denied={recorder.phase === "denied"} botUsername={status.bot_username} onType={onType} onRetry={recorder.phase === "unsupported" ? null : () => void recorder.start()} />;
  }

  if (recorder.phase === "stopping" || (recorder.phase === "done" && !create.isError)) {
    return <Working phase="sending" />;
  }

  if (create.isError) {
    const refusal = refusalOf(create.error);
    if (refusal === "ai_off") return <AIOff />;
    const limit = refusal === "limit_reached";
    return (
      <StateView icon={MicOff} tone="warn" title={t("failed.title")} body={refusal ? t(`refusal.${refusal}`) : errorText(create.error, t)}>
        {limit ? (
          <Button variant="primary" size="lg" onClick={onCancel}>
            {t("common.close")}
          </Button>
        ) : (
          <>
            <Button
              variant="primary"
              size="lg"
              icon={RotateCw}
              onClick={() => {
                create.reset();
                void recorder.start();
              }}
            >
              {t("failed.sayAgain")}
            </Button>
            {onType && (
              <Button variant="ghost" icon={PenLine} onClick={onType}>
                {t("failed.typeInstead")}
              </Button>
            )}
          </>
        )}
      </StateView>
    );
  }

  return <Listening recorder={recorder} max={status.max_seconds} onCancel={() => {
    recorder.cancel();
    onCancel();
  }} />;
}

/** The microphone at work: pulse, level meter, timer, Cancel and Done. */
function Listening({ recorder, max, onCancel }: { recorder: Recorder; max: number; onCancel: () => void }) {
  const t = useFeatureT(messages);
  const live = recorder.phase === "recording";
  const starting = recorder.phase === "starting";
  const left = Math.max(0, Math.ceil(max - recorder.seconds));
  const level = live ? recorder.levels.at(-1) ?? 0 : 0;
  return (
    <div className="ai-stage ai-rec fade-in">
      <div className="ai-rec-head">
        <div className="heading title-sm">{t("rec.title")}</div>
        <p className="ai-rec-lead">{t("rec.lead")}</p>
      </div>

      <div className={cx("ai-rec-stage", live && "ai-rec-stage--live")} style={{ ["--level" as string]: level.toFixed(3) }}>
        <span className="ai-rec-halo ai-rec-halo--outer" aria-hidden />
        <span className="ai-rec-halo" aria-hidden />
        {recorder.phase === "idle" ? (
          // After a recording that was too short: one tap starts again.
          <button type="button" className="ai-rec-mic" aria-label={t("title.mic")} onClick={() => void recorder.start()}>
            <Mic size={38} strokeWidth={2.2} />
          </button>
        ) : (
          <span className={cx("ai-rec-mic", starting && "ai-rec-mic--starting")} aria-hidden>
            <Mic size={38} strokeWidth={2.2} />
          </span>
        )}
      </div>

      <div className="ai-rec-status" role="status" aria-live="polite">
        {starting ? (
          <span className="ai-rec-hint">{t("rec.starting")}</span>
        ) : recorder.phase === "idle" && recorder.tooShort ? (
          <span className="ai-rec-hint ai-rec-hint--warn">{t("rec.tooShort")}</span>
        ) : (
          <>
            <span className="ai-rec-live">
              <span className="ai-rec-dot" aria-hidden />
              {t("rec.listening")}
            </span>
            <span className="ai-rec-clock num">{formatClock(recorder.seconds)}</span>
          </>
        )}
      </div>

      <Meter levels={recorder.levels} live={live} />

      <div className={cx("ai-rec-limit num", live && left <= WARN_SECONDS && "ai-rec-limit--warn")}>
        {live && left <= WARN_SECONDS ? t("rec.left", { count: left }) : t("rec.limit", { time: formatClock(max) })}
      </div>

      <p className="ai-rec-example">{t("rec.example")}</p>

      <div className="ai-rec-buttons">
        <Button variant="secondary" size="lg" onClick={onCancel}>
          {t("rec.cancel")}
        </Button>
        <Button
          variant="primary"
          size="lg"
          icon={Check}
          disabled={!live}
          onClick={() => {
            haptic.impact("light");
            recorder.stop();
          }}
        >
          {t("rec.done")}
        </Button>
      </div>
    </div>
  );
}

/** The live level: the newest bar on the right, quiet bars resting as dots. */
function Meter({ levels, live }: { levels: number[]; live: boolean }) {
  return (
    <div className={cx("ai-meter", live && "ai-meter--live")} aria-hidden>
      {levels.map((value, index) => (
        <span key={index} className="ai-meter-bar" style={{ transform: `scaleY(${Math.max(0.12, live ? value : 0).toFixed(3)})` }} />
      ))}
    </div>
  );
}

/**
 * Recording isn't possible here (no microphone access, or a client without one): the bot takes a
 * voice message instead, and typing works too.
 */
function Fallback({
  denied,
  botUsername,
  onType,
  onRetry,
}: {
  denied: boolean;
  botUsername: string;
  onType: (() => void) | null;
  onRetry: (() => void) | null;
}) {
  const t = useFeatureT(messages);
  return (
    <StateView icon={MicOff} title={t(denied ? "fallback.deniedTitle" : "fallback.title")} body={t(denied ? "fallback.deniedBody" : "fallback.body")}>
        {botUsername && (
          <Button
            variant="primary"
            size="lg"
            icon={Send}
            onClick={() => {
              haptic();
              openTelegramLink(`https://t.me/${botUsername}`);
            }}
          >
            {t("fallback.openBot")}
          </Button>
        )}
        {onType && (
          <Button variant="secondary" size="lg" icon={PenLine} onClick={onType}>
            {t("fallback.type")}
          </Button>
        )}
        {denied && onRetry && (
          <Button variant="ghost" icon={RotateCw} onClick={onRetry}>
            {t("fallback.retry")}
          </Button>
        )}
    </StateView>
  );
}
