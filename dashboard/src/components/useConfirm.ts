/**
 * Confirmation without markup: `const answer = await useConfirm()({ title, message, tone: "danger",
 * reason: "required" })` resolves `{ reason }` when confirmed and `null` when cancelled. One
 * ConfirmHost (mounted in App.vue) shows the requests one at a time.
 */
import { shallowRef, type Component } from "vue";

export interface ConfirmRequest {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "primary" | "danger";
  reason?: "none" | "optional" | "required";
  reasonLabel?: string;
  reasonPlaceholder?: string;
  /** Ready answers as chips above the text (ConfirmDialog). */
  reasonChips?: string[];
  /** The chip that asks for the person's own words. */
  reasonOther?: string;
  reasonNotePlaceholder?: string;
  icon?: Component;
  /** Runs before the dialog closes; the dialog stays open if it throws. */
  onConfirm?: (reason: string) => unknown;
}

export interface PendingConfirm {
  id: number;
  request: ConfirmRequest;
  resolve: (answer: { reason: string } | null) => void;
}

let counter = 0;

/** The request on screen and those waiting behind it. */
export const confirmQueue = shallowRef<PendingConfirm[]>([]);

export function requestConfirm(request: ConfirmRequest): Promise<{ reason: string } | null> {
  return new Promise((resolve) => {
    confirmQueue.value = [...confirmQueue.value, { id: ++counter, request, resolve }];
  });
}

/**
 * Called by ConfirmHost when the person answers: the promise resolves at once, and the dialog leaves
 * the queue after its exit animation, so the next request (if any) opens cleanly.
 */
export function settleConfirm(id: number, answer: { reason: string } | null, leaveAfter = 220): void {
  const entry = confirmQueue.value.find((item) => item.id === id);
  entry?.resolve(answer);
  setTimeout(() => {
    confirmQueue.value = confirmQueue.value.filter((item) => item.id !== id);
  }, leaveAfter);
}

export function useConfirm(): typeof requestConfirm {
  return requestConfirm;
}
