/**
 * Who sees what of stock (PLAN-OWNER §14.6.4): reading (lookup, batches, analogs) takes
 * `stock.operate`, `stock.manage` or `sales.view`; acting (expiry checks, receiving a transfer,
 * defektura, counts, receipts, prescriptions) takes `stock.operate` or `stock.manage`. Owner
 * roles hold every permission. The server checks each request; this only hides what can't work.
 */
import { hasModule, isSuspended } from "../../api/membership";
import { can } from "../../api/permissions";
import type { Membership } from "../../api/types";

type Person = Pick<Membership, "permissions" | "status" | "company">;

export function readsStock(member: Pick<Membership, "permissions">): boolean {
  return can(member, "stock.operate") || can(member, "stock.manage") || can(member, "sales.view");
}

export function operatesStock(member: Pick<Membership, "permissions">): boolean {
  return can(member, "stock.operate") || can(member, "stock.manage");
}

/** The whole feature: the stock module is on, the person works here and may read stock. */
export function stockVisible(member: Person): boolean {
  return hasModule(member, "stock") && member.status === "approved" && !isSuspended(member) && readsStock(member);
}
