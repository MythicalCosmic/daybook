/**
 * "Intizom" (My record) in the mini app (PLAN-OWNER §13.4 `features/lifecycle/`, the "My record"
 * part): my warnings and reprimands, read (opening one marks it read), acknowledged ("Tanishdim",
 * which isn't agreeing) and explained once in my own words. Home shows a calm card while a record
 * waits to be read; Me → My record.
 *
 * Shown while the company has HR on, to approved people and to suspended ones (they keep reading
 * their records, §13.4; the server refuses their changes).
 *
 * Deep links (the bot's notice): `lifecycle.record:<id>`; also `record:<id>` and `lifecycle`.
 */
import { ShieldCheck } from "lucide-react";
import { lazy } from "react";

import { hasModule, isSuspended } from "../../api/membership";
import { defineFeature } from "../registry";
import { messages } from "./messages";
import { RecordCard, useMeStatus } from "./slots";

export default defineFeature({
  id: "lifecycle",
  messages,
  visible: (member) => hasModule(member, "hr") && (member.status === "approved" || isSuspended(member)),
  pages: {
    home: lazy(() => import("./RecordsPage")),
    record: lazy(() => import("./RecordPage")),
  },
  sheets: {
    explain: lazy(() => import("./ExplainSheet")),
  },
  homeCards: [{ id: "record", component: RecordCard, order: 50 }],
  meItems: [{ id: "record", group: "documents", label: "me.record", icon: ShieldCheck, open: { page: "home" }, order: 20, useStatus: useMeStatus }],
  routes: {
    lifecycle: { page: "home", tab: "profile" },
    "lifecycle.record": { page: "record", tab: "profile" },
    record: { page: "record", tab: "profile" },
  },
});
