import { AlertCircle, Mic, PenLine } from "lucide-react";

import { useFeatureT } from "../../i18n/feature";
import { useNavigation } from "../../state/navigation";
import { BottomBar, Button, ListRow } from "../../ui";
import type { AIDraft, ApplyResult } from "./api";
import { messages } from "./messages";

/**
 * Created: a check that draws itself, how many went out, and each task with its person (a tap
 * opens it). Anything the server refused is listed with its reason.
 */
export function Done({
  draft,
  failed,
  onAgain,
  onClose,
}: {
  draft: AIDraft;
  failed: ApplyResult["failed"];
  onAgain: (() => void) | null;
  onClose: () => void;
}) {
  const t = useFeatureT(messages);
  const navigation = useNavigation();
  const created = draft.created_tasks;
  const titles = draft.drafts.map((item) => item.title);
  return (
    <div className="ai-stage ai-done fade-in">
      <div className="ai-state">
        <span className="ai-done-mark" aria-hidden>
          <svg viewBox="0 0 24 24">
            <path d="M5 12.5 10 17.5 19 7.5" />
          </svg>
        </span>
        <div className="heading title-sm">{t("done.title", { count: created.length })}</div>
        <p className="ai-state-body">{t("done.body")}</p>
      </div>

      {created.length > 0 && (
        <div className="card list-card ai-done-list">
          {created.map((task) => (
            <ListRow key={task.id} title={task.title} subtitle={task.assignee_name || undefined} onClick={() => navigation.openTask(task.id)} />
          ))}
        </div>
      )}

      {failed.length > 0 && (
        <div className="ai-problem">
          <span className="ai-problem-text">
            <AlertCircle size={17} strokeWidth={2.5} aria-hidden />
            <span>{t("done.failed", { count: failed.length })}</span>
          </span>
          <ul className="ai-failed">
            {failed.map((item) => (
              <li key={item.index}>
                {titles[item.index] ? <b>{titles[item.index]}</b> : null}
                {titles[item.index] ? ": " : ""}
                {item.detail}
              </li>
            ))}
          </ul>
        </div>
      )}

      {onAgain && (
        <Button variant="secondary" icon={draft.audio ? Mic : PenLine} className="ai-again" onClick={onAgain}>
          {draft.audio ? t("done.again") : t("done.againText")}
        </Button>
      )}

      <BottomBar primary={{ text: t("done.close"), onClick: onClose }} />
    </div>
  );
}
