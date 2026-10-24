import { CircleAlert, CircleCheck } from "lucide-react";

import { cx } from "./cx";

export type ToastTone = "default" | "success" | "error";

export type ToastOptions = {
  tone?: ToastTone;
  /** One button in the toast, like "Undo" after completing a task. */
  action?: { label: string; onPress: () => void };
  /** How long it stays (ms); 2600 by default, 5000 with an action. */
  duration?: number;
  /** A finger or the focus rests on the toast (it stays meanwhile), and leaves it. */
  onHold?: () => void;
  onRelease?: () => void;
};

export type ToastData = { id: number; text: string } & ToastOptions;

/** The dark pill above the tab bar. A plain toast keeps the original look exactly. */
export function ToastView({
  toast,
  onAction,
  onHold,
  onRelease,
}: {
  toast: ToastData;
  onAction: () => void;
  /** A finger or the focus is on a toast with an action: keep it. */
  onHold?: () => void;
  onRelease?: () => void;
}) {
  const { text, tone = "default", action } = toast;
  if (tone === "default" && !action) {
    return (
      <div className="toast" role="status">
        <div>{text}</div>
      </div>
    );
  }
  const holds = action ? { onPointerEnter: onHold, onPointerLeave: onRelease, onFocus: onHold, onBlur: onRelease } : {};
  return (
    <div className="toast" role={tone === "error" ? "alert" : "status"}>
      <div className={cx("ui-toast", tone !== "default" && `ui-toast--${tone}`, action && "ui-toast--action")} {...holds}>
        {tone === "success" && <CircleCheck className="ui-toast-icon" size={19} strokeWidth={2.6} aria-hidden />}
        {tone === "error" && <CircleAlert className="ui-toast-icon" size={19} strokeWidth={2.6} aria-hidden />}
        <span className="ui-toast-text">{text}</span>
        {action && (
          <button type="button" className="ui-toast-action" onClick={onAction}>
            {action.label}
          </button>
        )}
      </div>
    </div>
  );
}
