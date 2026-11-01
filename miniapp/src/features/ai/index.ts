/**
 * Tasks from the AI (contract v0.2 §7): say who should do what ("Alisher, check the fridge by ten
 * tomorrow and send a photo"), or write it in one text, and review the tasks it understood before
 * they go out through the normal task flow. Ways in: "Dictate tasks" in the (+) sheet, the mic and
 * the sparkle beside its title, and a Home card for whoever gives work, each shown while
 * `ai/status/` says the company's voice notes or smart text work. The bot's "Edit in the app"
 * opens the review at `?screen=drafts:<id>`.
 */
import { Mic } from "lucide-react";
import { lazy } from "react";

import { defineFeature } from "../registry";
import { DictateCard, PlusTitleTools, useVoiceVisible } from "./Entry";
import { messages } from "./messages";

export default defineFeature({
  id: "ai",
  messages,
  visible: (member) => member.status === "approved",
  sheets: {
    draft: lazy(() => import("./DraftSheet").then((m) => ({ default: m.DraftSheet }))),
  },
  homeCards: [{ id: "dictate", component: DictateCard, order: 20 }],
  plusActions: [{ id: "dictate", label: "plus.dictate", icon: Mic, open: { sheet: "draft", params: { mode: "voice" } }, order: 10, useVisible: useVoiceVisible }],
  plusTitle: [{ id: "tools", component: PlusTitleTools }],
  // ?screen=drafts:41 or startapp=drafts-41: the review of draft 41, over Home.
  routes: { drafts: { sheet: "draft", param: "id", tab: "home" } },
});
