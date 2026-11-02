/**
 * "Maoshim" (My pay) in the mini app (PLAN-OWNER §9.3 `features/wallet/`, the employee rows of
 * §4.11): this month so far with its parts and the bonus rules' progress, payslips with every
 * line, the PDF and "I received it", bonuses and fines with disputes, advances with the cap, the
 * request and the repayment months. Home shows the month at its end and a card for a payslip that
 * asks something; Me → My pay; (+) → Ask for an advance.
 *
 * Shown while the company has payroll on, to approved people and to suspended ones (they keep
 * reading their pay, §13.4; the server refuses their changes).
 *
 * Deep links (the bot's buttons): `wallet` ("Open my pay"), `payslip:<id>` (a published or paid
 * payslip); also `pay`, and `wallet.<page>` for any page.
 */
import { HandCoins, Wallet } from "lucide-react";
import { lazy } from "react";

import { hasModule, isSuspended } from "../../api/membership";
import { defineFeature } from "../registry";
import { messages } from "./messages";
import { MonthCard, PayslipCard, useCanAskAdvance, useMeStatus } from "./slots";

const lists = () => import("./ListPages");
const sheets = () => import("./sheets");

export default defineFeature({
  id: "wallet",
  messages,
  visible: (member) => hasModule(member, "payroll") && (member.status === "approved" || isSuspended(member)),
  pages: {
    home: lazy(() => import("./WalletPage")),
    payslip: lazy(() => import("./PayslipPage")),
    payslips: lazy(() => lists().then((module) => ({ default: module.PayslipsPage }))),
    adjustments: lazy(() => lists().then((module) => ({ default: module.AdjustmentsPage }))),
    advances: lazy(() => lists().then((module) => ({ default: module.AdvancesPage }))),
  },
  sheets: {
    adjustment: lazy(() => sheets().then((module) => ({ default: module.AdjustmentSheet }))),
    advance: lazy(() => sheets().then((module) => ({ default: module.AdvanceRequestSheet }))),
    advanceInfo: lazy(() => sheets().then((module) => ({ default: module.AdvanceSheet }))),
  },
  // Pay that arrived and waits for "I received it" is something to act on today.
  homeCards: [{ id: "payslip", component: PayslipCard, order: 30 }],
  // The month so far is an overview: after the day's work, before my projects (60).
  homeEnd: [{ id: "month", component: MonthCard, order: 50 }],
  meItems: [{ id: "pay", group: "money", label: "me.pay", icon: Wallet, open: { page: "home" }, order: 10, useStatus: useMeStatus }],
  plusActions: [
    {
      id: "advance",
      label: "plus.advance",
      icon: HandCoins,
      open: { sheet: "advance" },
      order: 50,
      visible: (member) => member.status === "approved",
      useVisible: useCanAskAdvance,
    },
  ],
  routes: {
    wallet: { page: "home", tab: "profile" },
    pay: { page: "home", tab: "profile" },
    payslip: { page: "payslip", tab: "profile" },
  },
});
