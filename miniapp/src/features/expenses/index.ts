/**
 * Expenses (PLAN-OWNER §9.3 `features/expenses/`, package I, the claim flow of §3.7): an
 * employee who paid for something for the pharmacy sends the expense with its receipts, paid
 * from their own money (it comes back with their pay or in cash) or from company cash they hold.
 * Under the company's approval threshold it is recorded at once; otherwise it waits for someone
 * with `finance.approve`. (+) → Expense; Me → My expenses lists my claims with their status.
 *
 * Shown while the company has finance on, to approved people with `finance.claim`.
 *
 * Deep links: `expenses` (my expenses), `expense` (a new one), `claim:<id>` (one of my claims,
 * over the list); `expenses.<page>` for any page.
 */
import { Receipt, ReceiptText } from "lucide-react";
import { lazy } from "react";

import type { NavigationInit } from "../../state/navigation";
import { defineFeature } from "../registry";
import { canClaim } from "./lib";
import { messages } from "./messages";
import { useMeStatus } from "./slots";

const sheets = () => import("./sheets");

/** `claim:<id>`: my expenses with that claim open over them (just the list for a bad id). */
function claimRoute(arg: string | null): NavigationInit {
  const id = arg !== null && /^\d{1,15}$/.test(arg) ? Number(arg) : null;
  return {
    tab: "profile",
    stack: [{ feature: "expenses", page: "list", params: {} }],
    ...(id !== null ? { sheet: { kind: "feature" as const, feature: "expenses", sheet: "claim", params: { id } } } : {}),
  };
}

export default defineFeature({
  id: "expenses",
  messages,
  visible: (member) => canClaim(member),
  pages: {
    list: lazy(() => import("./ListPage")),
  },
  sheets: {
    new: lazy(() => sheets().then((module) => ({ default: module.NewClaimSheet }))),
    claim: lazy(() => sheets().then((module) => ({ default: module.ClaimSheet }))),
  },
  meItems: [{ id: "expenses", group: "money", label: "me.expenses", icon: ReceiptText, open: { page: "list" }, order: 20, useStatus: useMeStatus }],
  plusActions: [{ id: "expense", label: "plus.expense", icon: Receipt, open: { sheet: "new" }, order: 20 }],
  routes: {
    expenses: { page: "list", tab: "profile" },
    expense: { sheet: "new" },
    claim: claimRoute,
  },
});
