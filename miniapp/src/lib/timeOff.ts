import type { TimeOff } from "../api/types";
import type { DayKey } from "./time";

/** Requests worth showing: anything not cancelled that hasn't ended yet. */
export function current(items: TimeOff[], today: DayKey): TimeOff[] {
  return items.filter((item) => item.status !== "cancelled" && item.last_day >= today);
}

/** The person can take back a request until approved time off begins. */
export function cancellable(item: TimeOff, today: DayKey): boolean {
  return item.status === "pending" || (item.status === "approved" && item.first_day > today);
}

export const STATUS_TAG: Record<TimeOff["status"], string> = {
  pending: "tag-neutral",
  approved: "tag-sage",
  rejected: "tag-accent",
  cancelled: "tag-neutral",
};
