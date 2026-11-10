/**
 * The people lifecycle in the mini app (PLAN-OWNER §13.4 `features/lifecycle/`):
 * - "Intizom" (My record): my warnings and reprimands, read (opening one marks it read),
 *   acknowledged ("Tanishdim", which isn't agreeing) and explained once in my own words. Home
 *   shows a calm card while a record waits to be read; Me → My record.
 * - "Ishdan ketish" (Leaving): the resignation letter (my last working day and my reason), its
 *   answer, the day agreed with what I hand over, and three questions before I go. Home shows the
 *   agreed day; Me → Leaving (with the day, or "Waiting").
 * - "Mening tarixim" (My career): my job now, the changes to come and those that took effect.
 *
 * Shown while the company has HR on, to approved people and to suspended ones (they keep reading
 * their records, §13.4; the server refuses their changes). Asking to leave is for approved people.
 *
 * Deep links (the bot's notices): `lifecycle.record:<id>` (also `record:<id>`, `lifecycle`),
 * `lifecycle.leaving` (also `leaving`), `lifecycle.career` (also `career`).
 */
import { BriefcaseBusiness, DoorOpen, ShieldCheck } from "lucide-react";
import { lazy } from "react";

import { hasModule, isSuspended } from "../../api/membership";
import { defineFeature } from "../registry";
import { messages } from "./messages";
import { LeavingCard, RecordCard, useLeavingStatus, useMeStatus } from "./slots";

const approved = (member: { status: string }) => member.status === "approved";

export default defineFeature({
  id: "lifecycle",
  messages,
  visible: (member) => hasModule(member, "hr") && (member.status === "approved" || isSuspended(member)),
  pages: {
    home: lazy(() => import("./RecordsPage")),
    record: lazy(() => import("./RecordPage")),
    leaving: lazy(() => import("./LeavingPage")),
    career: lazy(() => import("./CareerPage")),
  },
  sheets: {
    explain: lazy(() => import("./ExplainSheet")),
  },
  homeCards: [
    { id: "record", component: RecordCard, order: 50 },
    { id: "leaving", component: LeavingCard, order: 55, visible: approved },
  ],
  meItems: [
    { id: "record", group: "documents", label: "me.record", icon: ShieldCheck, open: { page: "home" }, order: 20, useStatus: useMeStatus },
    { id: "leaving", group: "documents", label: "me.leaving", icon: DoorOpen, open: { page: "leaving" }, order: 90, visible: approved, useStatus: useLeavingStatus },
    { id: "career", group: "work", label: "me.career", icon: BriefcaseBusiness, open: { page: "career" }, order: 60 },
  ],
  routes: {
    lifecycle: { page: "home", tab: "profile" },
    "lifecycle.record": { page: "record", tab: "profile" },
    record: { page: "record", tab: "profile" },
    "lifecycle.leaving": { page: "leaving", tab: "profile" },
    leaving: { page: "leaving", tab: "profile" },
    "lifecycle.career": { page: "career", tab: "profile" },
    career: { page: "career", tab: "profile" },
  },
});
