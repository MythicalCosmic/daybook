/**
 * Toasts without a library (plan §6.4). `useToast().success("Saved")`, or with an undo action:
 * `toast.info(t("tasks.done"), { action: { label: t("common.undo"), onClick: undo }, duration: 5000 })`.
 * Plain module state, so non-component code (the HTTP layer) can raise toasts too.
 */
import { shallowReactive } from "vue";

export type ToastTone = "success" | "error" | "info" | "warning";

export interface ToastAction {
  label: string;
  onClick: () => unknown;
}

export interface ToastOptions {
  description?: string;
  action?: ToastAction;
  /** ms; 0 keeps it until dismissed. Default 4 s, errors 6 s, with an action 5 s. */
  duration?: number;
  /** Re-using an id replaces that toast instead of stacking another. */
  id?: string;
}

export interface Toast {
  id: string;
  tone: ToastTone;
  title: string;
  description?: string;
  action?: ToastAction;
  duration: number;
  createdAt: number;
}

const MAX_VISIBLE = 4;
let counter = 0;

export const toasts = shallowReactive<Toast[]>([]);
const timers = new Map<string, ReturnType<typeof setTimeout>>();

export function dismissToast(id: string): void {
  const index = toasts.findIndex((t) => t.id === id);
  if (index >= 0) toasts.splice(index, 1);
  clearTimeout(timers.get(id));
  timers.delete(id);
}

function schedule(toast: Toast): void {
  clearTimeout(timers.get(toast.id));
  if (toast.duration > 0) timers.set(toast.id, setTimeout(() => dismissToast(toast.id), toast.duration));
}

/** Hover pauses the countdown; leaving restarts it. */
export function pauseToast(id: string): void {
  clearTimeout(timers.get(id));
  timers.delete(id);
}

export function resumeToast(id: string): void {
  const toast = toasts.find((t) => t.id === id);
  if (toast) schedule(toast);
}

export function showToast(tone: ToastTone, title: string, options: ToastOptions = {}): string {
  const id = options.id ?? `toast-${++counter}`;
  const duration = options.duration ?? (options.action ? 5000 : tone === "error" ? 6000 : 4000);
  const toast: Toast = { id, tone, title, description: options.description, action: options.action, duration, createdAt: Date.now() };
  const existing = toasts.findIndex((t) => t.id === id);
  if (existing >= 0) toasts.splice(existing, 1, toast);
  else toasts.push(toast);
  while (toasts.length > MAX_VISIBLE) dismissToast(toasts[0]!.id);
  schedule(toast);
  return id;
}

export const toast = {
  success: (title: string, options?: ToastOptions) => showToast("success", title, options),
  error: (title: string, options?: ToastOptions) => showToast("error", title, options),
  info: (title: string, options?: ToastOptions) => showToast("info", title, options),
  warning: (title: string, options?: ToastOptions) => showToast("warning", title, options),
  dismiss: dismissToast,
};

export function useToast() {
  return toast;
}
