import { ApiError } from "../api/client";
import { useTaskAction } from "../api/hooks";
import type { Task } from "../api/types";
import { useI18n, type Translate } from "../i18n";
import { useNavigation } from "../state/navigation";
import { useMember } from "../state/session";
import { useToast } from "../state/toast";
import { haptic } from "../telegram";

export function errorText(error: unknown, t: Translate): string {
  if (error instanceof ApiError) return error.detail ?? t("error.generic");
  return t("error.network");
}

/** Ticking a task: done right away when nothing else is needed, else the finish sheet. */
export function useCompleteTask(): (task: Task) => void {
  const { companyId } = useMember();
  const action = useTaskAction(companyId);
  const navigation = useNavigation();
  const toast = useToast();
  const { t } = useI18n();
  return (task) => {
    if (!task.actions.includes("complete")) {
      navigation.openTask(task.id);
      return;
    }
    if (task.proof !== "none" || task.needs_confirmation) {
      haptic();
      navigation.openSheet({ kind: "complete", taskId: task.id });
      return;
    }
    action.mutate(
      { taskId: task.id, action: "complete", proofText: "", photo: null },
      {
        onSuccess: () => {
          haptic("success");
          toast(t("toast.done"));
        },
        onError: (error) => {
          haptic("error");
          toast(errorText(error, t));
        },
      },
    );
  };
}
