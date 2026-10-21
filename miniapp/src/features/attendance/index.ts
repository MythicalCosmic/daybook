/**
 * Attendance in the mini app (package F, plan §1.8, §4.9 prefix E): check in and out from Home
 * with the location of the tap, my month, my shifts, swaps and open shifts, and fix requests.
 * Shown to approved people while the company has the attendance module on (suspended people
 * see the paused screen instead and nothing here).
 *
 * Deep links: `attendance` (the bot's menu button), `attendance.shifts`, `attendance.swaps`,
 * `attendance.correct:<record id>` (the automatic check-out notice).
 */
import { CalendarClock, Repeat2, Users } from "lucide-react";
import { lazy } from "react";

import { hasModule } from "../../api/membership";
import { can } from "../../api/permissions";
import { defineFeature } from "../registry";
import { messages } from "./messages";
import { HeroSlot, WaitingSlot, useBoardStatus, useMeStatus } from "./slots";

export default defineFeature({
  id: "attendance",
  messages,
  visible: (member) => member.status === "approved" && hasModule(member, "attendance"),
  homeHero: [{ id: "checkIn", component: HeroSlot, order: 10 }],
  homeCards: [{ id: "waiting", component: WaitingSlot, order: 20 }],
  pages: {
    home: lazy(() => import("./AttendancePage")),
    shifts: lazy(() => import("./ShiftsPage")),
    swaps: lazy(() => import("./SwapsPage")),
    // Managers' "Who's in" (attendance.view; the endpoint checks it again).
    board: lazy(() => import("./BoardPage")),
  },
  sheets: {
    correct: lazy(() => import("./CorrectSheet")),
    swap: lazy(() => import("./SwapSheet")),
  },
  meItems: [
    { id: "attendance", group: "work", label: "me.attendance", icon: CalendarClock, open: { page: "home" }, order: 20, useStatus: useMeStatus },
    {
      id: "board",
      group: "team",
      label: "me.board",
      icon: Users,
      open: { page: "board" },
      order: 10,
      visible: (member) => can(member, "attendance.view"),
      useStatus: useBoardStatus,
    },
  ],
  plusActions: [{ id: "swap", label: "plus.swap", icon: Repeat2, open: { page: "shifts" }, order: 40 }],
  routes: {
    attendance: "home",
    "attendance.correct": { sheet: "correct", param: "record" },
  },
});
