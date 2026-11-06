/**
 * "Jihozlarim" (My equipment) in the mini app: what the company gave the person (a laptop, the
 * keys, a uniform) with "I have it" to confirm, a Home card while something waits for that, and
 * Me → My equipment. Shown while the company has the assets module on, to approved people.
 *
 * Deep link (the bot's notice): `assets.mine`.
 */
import { Package } from "lucide-react";
import { lazy } from "react";

import { hasModule } from "../../api/membership";
import { defineFeature } from "../registry";
import { messages } from "./messages";
import { MineCard, useMeStatus } from "./slots";

export default defineFeature({
  id: "assets",
  messages,
  visible: (member) => hasModule(member, "assets") && member.status === "approved",
  pages: { home: lazy(() => import("./MinePage")) },
  homeCards: [{ id: "equipment", component: MineCard, order: 55 }],
  meItems: [{ id: "equipment", group: "documents", label: "me.equipment", icon: Package, open: { page: "home" }, order: 30, useStatus: useMeStatus }],
  routes: { "assets.mine": { page: "home", tab: "profile" } },
});
