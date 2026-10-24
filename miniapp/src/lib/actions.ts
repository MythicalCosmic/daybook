import { useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import { isMissingEndpoint, keys, refreshAfterTaskChange, reopenTask, useTaskAction } from "../api/hooks";
import type { ConfirmMany, Task } from "../api/types";
import { useI18n, type Translate } from "../i18n";
import { useNavigation } from "../state/navigation";
import { useMember } from "../state/session";
import { useToast } from "../state/toast";
import { haptic, popup } from "../telegram";
import { sendLater, UNDO_MS } from "./delayedSend";

export function errorText(error: unknown, t: Translate): string {
  if (error instanceof ApiError) return error.detail ?? t("error.generic");
  return t("error.network");
}

/**
 * "Done" or "Sent for checking" with Undo for a few seconds: the server reopens it for the person
 * who finished it, within a minute, before anyone confirmed it (R2 T38).
 */
export function useDoneToast(): (done: Task) => void {
  const client = useQueryClient();
  const toast = useToast();
  const { t } = useI18n();
  const { companyId } = useMember();
  return (done) => {
    toast(done.status === "review" ? t("toast.sentForCheck") : t("toast.doneShort"), {
      tone: "success",
      action: {
        label: t("ui.toast.undo"),
        onPress: () => {
          haptic.select();
          reopenTask(client, companyId, done.id).then(
            () => toast(t("toast.reopened")),
            (error: unknown) => toast(undoError(error, t), { tone: "error" }),
          );
        },
      },
    });
  };
}

/** Why Undo didn't work: the server's reason (the minute is over, it's confirmed), or a plain line. */
function undoError(error: unknown, t: Translate): string {
  if (!(error instanceof ApiError)) return t("error.network");
  return !isMissingEndpoint(error) && error.detail ? error.detail : t("toast.undoFailed");
}

/**
 * Before finishing with steps left: "3 steps aren't ticked" → tick them all and finish, or go
 * back (audit X-5). Resolves to whether to go on; ticking happens here.
 */
export function useTickLeftFirst(): (task: Task) => Promise<boolean> {
  const { t } = useI18n();
  const { companyId } = useMember();
  const client = useQueryClient();
  const toast = useToast();
  return async (task) => {
    const left = task.checklist.filter((item) => !item.is_done);
    if (left.length === 0) return true;
    haptic.notify("warning");
    const choice = await popup(t("checklist.left", { count: left.length }), [
      { id: "tick", type: "default", text: t("checklist.tickAll") },
      { id: "back", type: "cancel" },
    ]);
    if (choice !== "tick") return false;
    try {
      let latest: Task | undefined;
      // One by one: each tick is its own change on the server (and its own audit line).
      for (const item of left) {
        latest = await api<Task>(`/companies/${companyId}/tasks/${task.id}/checklist/${item.id}/`, { json: { is_done: true } });
      }
      if (latest) client.setQueryData(keys.task(companyId, task.id), latest);
      return true;
    } catch (error) {
      toast(errorText(error, t), { tone: "error" });
      refreshAfterTaskChange(client, companyId);
      return false;
    }
  };
}

/**
 * Ticking a task: steps left are asked about first; then done right away when nothing else is
 * needed (with Undo), else the finish sheet for the photo or the note.
 */
export function useCompleteTask(): (task: Task) => void {
  const { companyId } = useMember();
  const action = useTaskAction(companyId);
  const navigation = useNavigation();
  const toast = useToast();
  const doneToast = useDoneToast();
  const tickLeftFirst = useTickLeftFirst();
  const client = useQueryClient();
  const { t } = useI18n();
  return (task) => {
    if (!task.actions.includes("complete")) {
      navigation.openTask(task.id);
      return;
    }
    void tickLeftFirst(task).then((go) => {
      if (!go) return;
      if (task.proof !== "none" || task.needs_confirmation) {
        haptic();
        navigation.openSheet({ kind: "complete", taskId: task.id });
        return;
      }
      // The tick shows at once (R2 T40); a refusal puts the row back as it was.
      const board = keys.board(companyId);
      const before = client.getQueryData<Task[]>(board);
      client.setQueryData<Task[]>(board, (list) =>
        list?.map((row) => (row.id === task.id ? { ...row, status: "done", completed_at: new Date().toISOString(), actions: [] } : row)),
      );
      action.mutate(
        { taskId: task.id, action: "complete", proofText: "", photo: null },
        {
          onSuccess: (done) => {
            haptic("success");
            doneToast(done);
          },
          onError: (error) => {
            if (before) client.setQueryData(board, before);
            haptic("error");
            toast(errorText(error, t), { tone: "error" });
          },
        },
      );
    });
  };
}

/**
 * Confirm finished work with a moment to take it back: the toast offers Undo for five seconds
 * and the request goes out after it (the server has no "unconfirm"). The work leaves the
 * "To check" list at once and comes back on Undo.
 */
export function useConfirmTasks(): (tasks: Task[], options?: { onSent?: () => void }) => void {
  const client = useQueryClient();
  const toast = useToast();
  const { t } = useI18n();
  const { companyId } = useMember();
  return (tasks, options = {}) => {
    const ids = tasks.map((task) => task.id);
    const queueKey = keys.review(companyId);
    const before = client.getQueryData<Task[]>(queueKey);
    client.setQueryData<Task[]>(queueKey, (queue) => queue?.filter((task) => !ids.includes(task.id)));
    const restore = () => {
      if (before) client.setQueryData(queueKey, before);
      void client.invalidateQueries({ queryKey: keys.tasks(companyId) });
    };
    const job = sendLater(() => {
      const request: Promise<unknown> =
        ids.length === 1
          ? api<Task>(`/companies/${companyId}/tasks/${ids[0]}/confirm/`, { method: "POST", keepalive: true }).then((task) =>
              refreshAfterTaskChange(client, companyId, task),
            )
          : api<ConfirmMany>(`/companies/${companyId}/tasks/confirm/`, { json: { ids }, keepalive: true }).then((result) => {
              refreshAfterTaskChange(client, companyId);
              if (result.failed) {
                haptic.notify("warning");
                toast(t("review.notConfirmed", { count: result.failed }), { tone: "error" });
              }
            });
      request.then(
        () => options.onSent?.(),
        (error: unknown) => {
          restore();
          haptic.notify("error");
          toast(errorText(error, t), { tone: "error" });
        },
      );
    });
    haptic.notify("success");
    toast(ids.length === 1 ? t("toast.confirmed") : t("review.confirmed", { count: ids.length }), {
      tone: "success",
      duration: UNDO_MS,
      action: {
        label: t("ui.toast.undo"),
        onPress: () => {
          haptic.select();
          if (job.cancel()) {
            restore();
            toast(t("toast.confirmUndone"));
          } else {
            toast(t("toast.undoFailed"), { tone: "error" });
          }
        },
      },
    });
  };
}
