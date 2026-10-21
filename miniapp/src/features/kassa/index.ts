/**
 * Kassa (PLAN-OWNER §9.3, package E): the cashier's till in the mini app. Home shows the till
 * (closed: "Open shift"; open: payout, handover, close) and the "Received?" card for cash
 * handed to me; the Kassa page opens a shift with the float counted note by note, runs it, and
 * closes it with totals per method, photos and the blind count, kept as a draft on the phone.
 *
 * Deep links: `kassa` (the Kassa page), `kassa.shift:<id>` (one of my shifts), `kassa.close:<id>`.
 */
import { HandCoins, Store } from "lucide-react";
import { lazy, type ComponentType } from "react";

import { hasModule } from "../../api/membership";
import { useMember } from "../../state/session";
import { defineFeature, type SheetProps, type SlotProps } from "../registry";
import { useKassa } from "./api";
import { runsTill, tillPage, tillSheet } from "./gate";
import { KassaHero } from "./KassaHero";
import { messages } from "./messages";
import { ReceivedCards } from "./Received";

/** Me → My shifts shows the open shift's code. */
function useShiftStatus(_: SlotProps) {
  const member = useMember();
  const kassa = useKassa(member.companyId);
  return { value: kassa.data?.shift?.code };
}

const sheet = <T extends "PayoutSheet" | "HandoverSheet" | "SafeSheet" | "SaleSheet">(name: T) =>
  tillSheet(lazy(() => import("./sheets").then((module) => ({ default: module[name] as ComponentType<SheetProps> }))));

export default defineFeature({
  id: "kassa",
  messages,
  // Anyone may receive handed-over cash; the till itself needs sales.operate (checked per slot).
  visible: (member) => hasModule(member, "sales"),
  // Till pages check `sales.operate` before they load or ask the server (gate.tsx); the Kassa
  // page still shows cash handed to the person.
  pages: {
    home: tillPage(lazy(() => import("./KassaPage")), { withReceived: true }),
    close: tillPage(lazy(() => import("./ClosePage"))),
    shift: tillPage(lazy(() => import("./ShiftPage"))),
    history: tillPage(lazy(() => import("./HistoryPage"))),
  },
  sheets: {
    payout: sheet("PayoutSheet"),
    handover: sheet("HandoverSheet"),
    safe: sheet("SafeSheet"),
    sale: sheet("SaleSheet"),
  },
  homeHero: [{ id: "till", component: KassaHero, order: 20, visible: runsTill }],
  homeCards: [{ id: "received", component: ReceivedCards, order: 10 }],
  meItems: [{ id: "shifts", group: "work", label: "me.shifts", icon: Store, open: { page: "history" }, visible: runsTill, useStatus: useShiftStatus }],
  plusActions: [{ id: "payout", label: "plus.payout", icon: HandCoins, open: { sheet: "payout" }, order: 30, visible: runsTill }],
  // `kassa.shift:<id>` and `kassa.close:<id>` resolve through the generic <feature>.<page> form.
  routes: { kassa: "home" },
});
