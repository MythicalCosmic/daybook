/**
 * The global "Record" dialog's open state (plan §6.2: quick add with `N` or the button). The
 * launcher in the top bar (QuickAddLauncher) watches it; palette commands, page buttons and the
 * Get started link open it from anywhere with `openQuickAdd("expense")`. Tiny on purpose: the
 * registry entry imports it, so it is part of the first bundle.
 */
import { shallowRef } from "vue";

export type QuickAddMode = "expense" | "income" | "transfer" | "owner" | "opening";

export interface QuickAddRequest {
  mode: QuickAddMode;
  /** Pre-picked account (from an account card or statement). */
  account?: number;
  /** Pre-picked destination of a transfer. */
  toAccount?: number;
  counterparty?: { id: number; name: string };
  category?: number;
  amount?: string;
  description?: string;
}

export const quickAdd = shallowRef<QuickAddRequest | null>(null);

export function openQuickAdd(request: QuickAddMode | QuickAddRequest = "expense"): void {
  quickAdd.value = typeof request === "string" ? { mode: request } : { ...request };
}

export function closeQuickAdd(): void {
  quickAdd.value = null;
}
