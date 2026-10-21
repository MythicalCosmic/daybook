import { useFeatureT } from "../../i18n/feature";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { useTimerAction } from "./api";
import { hhmm } from "./lib";
import { messages } from "./messages";

/**
 * Start my timer on a card or stop it, with the haptics and toasts every place uses: Home's timer
 * card, the card sheet and the task screen.
 */
export function useCardTimer(company: number) {
  const t = useFeatureT(messages);
  const toast = useToast();
  const action = useTimerAction(company);
  const failed = (error: unknown) => {
    haptic.notify("error");
    toast((error as { detail?: string | null }).detail ?? t("timerFailed"), { tone: "error" });
  };
  return {
    busy: action.isPending,
    start: (task: number) =>
      action.mutate(
        { kind: "start", task },
        {
          onSuccess: () => {
            haptic.impact("light");
            toast(t("timerStarted"), { tone: "success" });
          },
          onError: failed,
        },
      ),
    stop: () =>
      action.mutate(
        { kind: "stop" },
        {
          onSuccess: (entry) => {
            haptic.notify("success");
            if (entry) toast(t("timerLogged", { time: hhmm(entry.minutes) }), { tone: "success" });
          },
          onError: failed,
        },
      ),
  };
}
