/**
 * Announcements (plan §6.2, package C): compose with Telegram formatting, audience by positions
 * and branches with a live count, send now or schedule, pin and expiry, read-rate bars, receipts
 * per person and "Remind unread now". The composer hosts `comms.composer.tools` (the AI writer).
 */
import { Megaphone, SquarePen } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

import { routes } from "./routes";

export default defineModule({
  id: "comms",
  group: "comms",
  order: 10,
  icon: Megaphone,
  title: "comms.title",
  perm: "announcements.send",
  hotkey: "m",
  routes,
  nav: [{ key: "announcements", title: "comms.nav.announcements", to: "announcements" }],
  invalidates: ["announcements"],
  commands: (ctx) => [
    {
      id: "comms.new",
      title: ctx.t("comms.cmd.new"),
      icon: SquarePen,
      perm: "announcements.send",
      keywords: ["announce", "e’lon", "объявление", "message"],
      run: () => ctx.go("announcements/new"),
    },
  ],
  searchResults: {
    "announcements.announcement": defineAsyncComponent(() => import("./components/AnnouncementHit.vue")),
  },
  widgets: [
    {
      id: "comms.latest",
      span: 1,
      order: 70,
      kind: "card",
      perm: "announcements.send",
      component: defineAsyncComponent(() => import("./widgets/LatestWidget.vue")),
    },
  ],
  deepLinks: {
    announcement: (id) => (/^\d+$/.test(id) ? `announcements/${id}` : "announcements"),
  },
  messages: async () => {
    const [uz, ru, en] = await Promise.all([import("./i18n/uz.json"), import("./i18n/ru.json"), import("./i18n/en.json")]);
    return { uz: uz.default, ru: ru.default, en: en.default };
  },
});
