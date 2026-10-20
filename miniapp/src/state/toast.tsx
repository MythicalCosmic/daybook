import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

import { ToastView, type ToastData, type ToastOptions } from "../ui/Toast";

export type ShowToast = (text: string, options?: ToastOptions) => void;

const ToastContext = createContext<ShowToast | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastData | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const show = useCallback<ShowToast>((text, options = {}) => {
    window.clearTimeout(timer.current);
    setToast({ id: Date.now(), text, ...options });
    timer.current = window.setTimeout(() => setToast(null), options.duration ?? (options.action ? 5000 : 2600));
  }, []);
  const act = () => {
    window.clearTimeout(timer.current);
    toast?.action?.onPress();
    setToast(null);
  };
  return (
    <ToastContext.Provider value={show}>
      {children}
      {toast && <ToastView key={toast.id} toast={toast} onAction={act} />}
    </ToastContext.Provider>
  );
}

/** Show a short message: `toast(text)`, or with a tone and an action (`{action: {label, onPress}}`). */
export function useToast(): ShowToast {
  const show = useContext(ToastContext);
  if (!show) throw new Error("useToast outside ToastProvider");
  return show;
}
