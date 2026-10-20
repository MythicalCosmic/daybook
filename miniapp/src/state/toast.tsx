import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

type Toast = { id: number; text: string } | null;

const ToastContext = createContext<((text: string) => void) | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast>(null);
  const timer = useRef<number | undefined>(undefined);
  const show = useCallback((text: string) => {
    window.clearTimeout(timer.current);
    setToast({ id: Date.now(), text });
    timer.current = window.setTimeout(() => setToast(null), 2600);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      {toast && (
        <div className="toast" key={toast.id} role="status">
          <div>{toast.text}</div>
        </div>
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): (text: string) => void {
  const show = useContext(ToastContext);
  if (!show) throw new Error("useToast outside ToastProvider");
  return show;
}
