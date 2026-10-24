/**
 * Sending finished work back asks the same way everywhere (the reviews queue, the task drawer, a
 * board drag, routine checks): ready reasons as chips, a note optional, "Other…" to write it out.
 * The chosen words are the reason the worker reads in Telegram and the app.
 */
import type { ConfirmRequest } from "./useConfirm";

type Translate = (key: string) => string;

export const RETURN_REASONS = ["photo", "unfinished", "wrongItem"] as const;

export function returnReasonFields(t: Translate): Pick<ConfirmRequest, "reason" | "reasonChips" | "reasonOther" | "reasonNotePlaceholder"> {
  return {
    reason: "required",
    reasonChips: RETURN_REASONS.map((key) => t(`common.returnReason.${key}`)),
    reasonOther: t("common.returnReason.other"),
    reasonNotePlaceholder: t("common.returnReason.note"),
  };
}
