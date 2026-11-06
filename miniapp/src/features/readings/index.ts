/**
 * Storage readings in the mini app (PLAN-OWNER §14.10, package B2): a routine's run that asks
 * for numbers within an allowed range (fridge and room temperature, humidity) is finished on the
 * task screen by typing them, with the note when one is out of range; a finished run shows what
 * was taken and offers the second measurement while it may come. Until P's pharmacist screens
 * (Wave 3) the screen's own Complete button gets the server's "Enter the readings" answer.
 */
import { lazy } from "react";

import { isSuspended } from "../../api/membership";
import { defineFeature } from "../registry";
import { messages } from "./messages";

export default defineFeature({
  id: "readings",
  messages,
  visible: (member) => member.status === "approved" && !isSuspended(member),
  // Before "How to do this" (knowledge, 10): the readings are the work itself. Lazy: only the
  // task screen needs it, and it renders nothing for a task that takes no readings.
  taskActions: [{ id: "readings", component: lazy(() => import("./ReadingsBlock")), order: 5 }],
});
