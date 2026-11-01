import { CircleSlash, Hourglass, Mic, MicOff, PenLine, X } from "lucide-react";
import { useState } from "react";

import { isMissingEndpoint } from "../../api/hooks";
import { useFeatureT } from "../../i18n/feature";
import { useNow } from "../../lib/useNow";
import { useMember } from "../../state/session";
import { Button, LoadError, Skeleton } from "../../ui";
import type { SheetProps } from "../registry";
import { entryOf, gaveUp, isWorking, useAIStatus, useDraft, workingPhase, type AIDraft, type ApplyResult } from "./api";
import { Done } from "./Done";
import { messages } from "./messages";
import { VoiceCompose } from "./Recorder";
import { Review } from "./Review";
import { AIOff, StateView, Working } from "./States";
import { TextCompose } from "./TextCompose";
import "./ai.css";

type Mode = "voice" | "text";

/**
 * The one sheet for tasks from the AI: speak (or type), wait while it listens and thinks, review
 * the cards, create them, see them made. `?screen=drafts:41` (the bot's "Edit in the app") opens
 * it straight at that draft. Params: `mode` "voice" | "text", `text` (typed in the (+) sheet),
 * or `id`.
 */
export function DraftSheet({ params, close }: SheetProps) {
  const member = useMember();
  const status = useAIStatus(member.companyId);
  const entry = entryOf(status.data);
  const [mode, setMode] = useState<Mode>(params.mode === "text" ? "text" : "voice");
  const [draftId, setDraftId] = useState<number | null>(typeof params.id === "number" ? params.id : null);
  // When this sheet started waiting for the draft: the give-up clock (contract: 90 s).
  const [since, setSince] = useState(() => Date.now());
  const [failed, setFailed] = useState<ApplyResult["failed"]>([]);
  // What the (+) sheet handed over (its typed title, sent at once) is for the first draft only:
  // "Write more" starts from an empty box, never sends the same words twice.
  const [prefill, setPrefill] = useState(() => ({ text: typeof params.text === "string" ? params.text : "", send: params.send === 1 }));
  // Who made the draft "applied": this person pressing Create, or the server at once (the voice
  // tasks agent's "auto-create" when every task was clear). Only a draft sent from this sheet can
  // be the second kind; one opened from the bot may have been created there.
  const [made, setMade] = useState<"here" | "sent" | null>(null);

  const sent = (draft: AIDraft) => {
    setSince(Date.now());
    setDraftId(draft.id);
    setMade("sent");
  };
  const again = (next: Mode) => {
    setDraftId(null);
    setFailed([]);
    setPrefill({ text: "", send: false });
    setMade(null);
    setMode(next);
  };

  if (draftId !== null) {
    return (
      <DraftView
        id={draftId}
        since={since}
        failed={failed}
        auto={made === "sent"}
        canVoice={entry.voice}
        canType={entry.text}
        onApplied={(result) => {
          setFailed(result.failed);
          setMade("here");
        }}
        onKeepWaiting={() => setSince(Date.now())}
        onAgain={again}
        close={close}
      />
    );
  }

  if (status.isPending) {
    return (
      <div className="ai-stage" aria-busy="true">
        <Skeleton height={28} width="45%" />
        <Skeleton height={180} />
      </div>
    );
  }
  if (status.isError && !isMissingEndpoint(status.error)) return <LoadError compact error={status.error} onRetry={() => void status.refetch()} />;
  if (!entry.any || !status.data) return <AIOff onClose={close} />;

  if ((mode === "voice" && entry.voice) || !entry.text) {
    return <VoiceCompose status={status.data} onSent={sent} onType={entry.text ? () => setMode("text") : null} onCancel={close} />;
  }
  return <TextCompose initial={prefill.text} send={prefill.send} onSent={sent} onClose={close} />;
}

function DraftView({
  id,
  since,
  failed,
  auto,
  canVoice,
  canType,
  onApplied,
  onKeepWaiting,
  onAgain,
  close,
}: {
  id: number;
  since: number;
  failed: ApplyResult["failed"];
  /** The draft was sent from this sheet and nobody here pressed Create: an "applied" one went out at once. */
  auto: boolean;
  canVoice: boolean;
  canType: boolean;
  onApplied: (result: ApplyResult) => void;
  onKeepWaiting: () => void;
  onAgain: (mode: Mode) => void;
  close: () => void;
}) {
  const t = useFeatureT(messages);
  const member = useMember();
  const query = useDraft(member.companyId, id, since);
  const draft = query.data;

  if (!draft) {
    if (query.isError) return <LoadError compact error={query.error} onRetry={() => void query.refetch()} />;
    return <Working phase="thinking" voice={false} />;
  }

  // Say it again in the way it came (a voice note, a text), or the other way when that one is off.
  const againMode: Mode | null = draft.audio ? (canVoice ? "voice" : canType ? "text" : null) : canType ? "text" : canVoice ? "voice" : null;
  const again = againMode ? () => onAgain(againMode) : null;

  if (isWorking(draft)) {
    return (
      <Waiting
        draft={draft}
        since={since}
        onKeepWaiting={() => {
          onKeepWaiting();
          void query.refetch();
        }}
        close={close}
      />
    );
  }

  switch (draft.status) {
    case "ready":
      return <Review key={draft.id} draft={draft} onApplied={onApplied} onDiscarded={close} onAgain={again ?? close} />;
    case "applied":
      return <Done draft={draft} failed={failed} auto={auto} onAgain={again} onClose={close} />;
    case "discarded":
      return (
        <StateView icon={CircleSlash} tone="sage" title={t("discarded.title")} body={t("discarded.body")}>
          <Button variant="secondary" size="lg" icon={X} onClick={close}>
            {t("common.close")}
          </Button>
        </StateView>
      );
    case "expired":
    case "failed": {
      const expired = draft.status === "expired" || draft.error_code === "expired";
      return (
        <StateView
          icon={expired ? Hourglass : MicOff}
          tone="warn"
          title={t(expired ? "expired.title" : "failed.title")}
          body={expired ? t("expired.body") : draft.error || t("failed.body")}
        >
          {again && (
            <Button variant="primary" size="lg" icon={againMode === "voice" ? Mic : PenLine} onClick={again}>
              {againMode === "voice" ? t("failed.sayAgain") : t("done.againText")}
            </Button>
          )}
          {againMode === "voice" && canType && (
            <Button variant="ghost" icon={PenLine} onClick={() => onAgain("text")}>
              {t("failed.typeInstead")}
            </Button>
          )}
          {!again && (
            <Button variant="secondary" size="lg" onClick={close}>
              {t("common.close")}
            </Button>
          )}
        </StateView>
      );
    }
    default:
      return <LoadError compact error={null} onRetry={() => void query.refetch()} />;
  }
}

/** The wait, on its own one-second clock: "Listening…", "Thinking…", then "longer than usual". */
function Waiting({ draft, since, onKeepWaiting, close }: { draft: AIDraft; since: number; onKeepWaiting: () => void; close: () => void }) {
  const t = useFeatureT(messages);
  const now = useNow(1000);
  if (gaveUp(draft, since, now.getTime())) {
    return (
      <StateView icon={Hourglass} title={t("work.slowTitle")} body={t("work.slowBody")}>
        <Button variant="primary" size="lg" onClick={onKeepWaiting}>
          {t("work.wait")}
        </Button>
        <Button variant="ghost" onClick={close}>
          {t("common.close")}
        </Button>
      </StateView>
    );
  }
  return <Working phase={workingPhase(draft) ?? "thinking"} voice={draft.audio !== null} heard={draft.status === "thinking" ? draft.transcript || undefined : undefined} />;
}
