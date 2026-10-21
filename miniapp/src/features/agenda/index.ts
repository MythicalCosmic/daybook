/**
 * The calendar in the mini app (plan §13.5, package Q): my events and the team dates my
 * permissions allow, a week strip and the next two weeks, and "I'll come / Can't come" on an
 * event. Home shows my next event today or tomorrow.
 */
import { CalendarDays } from "lucide-react";
import { lazy } from "react";

import { defineFeature } from "../registry";
import { messages } from "./messages";
import { NextEventCard } from "./NextEventCard";

export default defineFeature({
  id: "agenda",
  messages,
  visible: (member) => member.status === "approved",
  pages: {
    home: lazy(() => import("./CalendarHome").then((m) => ({ default: m.CalendarHome }))),
    event: lazy(() => import("./EventPage").then((m) => ({ default: m.EventPage }))),
  },
  homeCards: [{ id: "next", component: NextEventCard, order: 30 }],
  meItems: [{ id: "calendar", group: "work", label: "me.calendar", icon: CalendarDays, open: { page: "home" } }],
  // ?screen=calendar or agenda.event:12 (inbox notifications), startapp=event-12.
  routes: { calendar: { page: "home", tab: "profile" }, event: { page: "event", tab: "profile" } },
});
