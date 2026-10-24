import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

import { ToastView, type ToastData, type ToastOptions } from "../ui/Toast";

export type ShowToast = (text: string, options?: ToastOptions) => void;

const ToastContext = createContext<ShowToast | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastData | null>(null);
  const timer = useRef<number | undefined>(undefined);
  // The toast a finger or the focus rests on: whatever it holds (a send waiting for Undo) must let
  // go when it closes or another toast takes its place.
  const held = useRef<ToastData | null>(null);
  const letGo = () => {
    const toastHeld = held.current;
    held.current = null;
    toastHeld?.onRelease?.();
  };
  const show = useCallback<ShowToast>((text, options = {}) => {
    window.clearTimeout(timer.current);
    letGo();
    setToast({ id: Date.now(), text, ...options });
    timer.current = window.setTimeout(() => setToast(null), options.duration ?? (options.action ? 5000 : 2600));
  }, []);
  const act = () => {
    window.clearTimeout(timer.current);
    held.current = null;
    const press = toast?.action?.onPress;
    // Closed first, so a toast the action shows ("Back on your list.") is the one that stays.
    setToast(null);
    press?.();
  };
  // A toast with an action stays while a finger or the focus is on it (a screen reader needs the
  // time to reach Undo), then gives a moment more once it leaves.
  const hold = () => {
    window.clearTimeout(timer.current);
    if (toast && held.current !== toast) {
      held.current = toast;
      toast.onHold?.();
    }
  };
  const release = () => {
    window.clearTimeout(timer.current);
    letGo();
    timer.current = window.setTimeout(() => setToast(null), 2500);
  };
  return (
    <ToastContext.Provider value={show}>
      {children}
      {toast && <ToastView key={toast.id} toast={toast} onAction={act} onHold={hold} onRelease={release} />}
    </ToastContext.Provider>
  );
}

/** Show a short message: `toast(text)`, or with a tone and an action (`{action: {label, onPress}}`). */
export function useToast(): ShowToast {
  const show = useContext(ToastContext);
  if (!show) throw new Error("useToast outside ToastProvider");
  return show;
}
