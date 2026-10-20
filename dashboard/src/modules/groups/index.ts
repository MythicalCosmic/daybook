/**
 * Telegram groups (plan §6.1 Communication › Groups, package A): connected groups, the events the
 * bot posts in each, positions and branches filters, disconnect.
 */
import { MessagesSquare } from "@lucide/vue";

import { defineModule } from "@/core/modules";

export default defineModule({
  id: "groups",
  group: "comms",
  order: 20,
  icon: MessagesSquare,
  title: "groups.title",
  perm: "groups.manage",
  routes: [
    {
      path: "groups",
      name: "groups.page",
      component: () => import("./pages/GroupsPage.vue"),
      meta: { title: "groups.title" },
    },
  ],
  invalidates: ["groups"],
  commands: (ctx) => [
    {
      id: "groups.add",
      title: ctx.t("groups.cmd.add"),
      keywords: ["guruh", "группа", "telegram"],
      run: async () => {
        const { listGroups } = await import("./api");
        const { connect_link } = await listGroups(ctx.companyId);
        if (connect_link) window.open(connect_link, "_blank", "noopener");
        else ctx.go("groups");
      },
    },
  ],
  deepLinks: { groups: () => "groups" },
  messages: async () => {
    const [uz, ru, en] = await Promise.all([import("./i18n/uz.json"), import("./i18n/ru.json"), import("./i18n/en.json")]);
    return { uz: uz.default, ru: ru.default, en: en.default };
  },
});
