/**
 * The inbox module (plan §6.1, W0): the reference every module engineer copies. It shows the whole
 * contract in one small module: an entry from core/catalog.ts (group, order, hotkey, badge), lazy
 * routes, pulse keys that refresh its queries, a palette command, an Overview widget, Telegram deep
 * links, and messages loaded on first use. See dashboard/README.md, "How to build a module".
 */
import { CheckCheck, Inbox } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { toast } from "@/components/useToast";
import { defineModule } from "@/core/modules";
import { counter, PULSE_INBOX_UNREAD, PULSE_QUEUE } from "@/core/pulse";

import { routes } from "./routes";

export default defineModule({
  id: "inbox",
  group: "overview",
  order: 20,
  icon: Inbox,
  title: "inbox.title",
  hotkey: "i",
  // "Needs you" waiting for the person (the sidebar badge); unread notifications ring the bell.
  badge: counter(PULSE_QUEUE),
  routes,
  // Pulse keys (apps.inbox's "inbox.unread", apps.console's "console.queue"): when either moves,
  // every inbox query refetches.
  invalidates: [PULSE_INBOX_UNREAD, PULSE_QUEUE],
  commands: (ctx) => [
    {
      id: "inbox.read-all",
      title: ctx.t("inbox.cmd.readAll"),
      icon: CheckCheck,
      keywords: ["read", "прочитать", "o‘qish"],
      run: async () => {
        // The API module loads on use, so the registry entry stays tiny in the first bundle.
        const { markRead } = await import("./api");
        await markRead(ctx.companyId, "all");
        toast.success(ctx.t("inbox.cmd.readAllDone"));
      },
    },
  ],
  widgets: [
    {
      id: "inbox.needs",
      span: 2,
      order: 30,
      kind: "card",
      component: defineAsyncComponent(() => import("./widgets/NeedsYouWidget.vue")),
    },
  ],
  // Telegram `startapp=inbox` opens this page, `inbox_notifications` its second tab (`approvals`
  // is the shell's own: it opens the drawer, plan §6.2).
  deepLinks: {
    inbox: (argument) => (argument === "notifications" ? "inbox?tab=notifications" : "inbox"),
  },
  messages: async () => {
    const [uz, ru, en] = await Promise.all([import("./i18n/uz.json"), import("./i18n/ru.json"), import("./i18n/en.json")]);
    return { uz: uz.default, ru: ru.default, en: en.default };
  },
});
