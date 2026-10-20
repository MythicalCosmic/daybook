/**
 * Exports (plan §6.1 "Company › exports", W0; N adds scheduled reports and the full export): the
 * person's own Excel/CSV files of the last 7 days, with status, download and "export again", and a
 * "New export" dialog over everything they may export. Tables start exports themselves with the
 * shared ExportButton; this page is where the files wait.
 */
import { Download } from "@lucide/vue";

import { defineModule } from "@/core/modules";
import { PULSE_EXPORTS } from "@/core/pulse";

export default defineModule({
  id: "exports",
  group: "company",
  order: 20,
  icon: Download,
  title: "exports.title",
  perm: "data.export",
  routes: [
    {
      path: "exports",
      name: "exports.list",
      component: () => import("./pages/ExportsPage.vue"),
      meta: { title: "exports.title" },
    },
  ],
  // apps.exports bumps this when an export is asked for and when it is ready or failed.
  invalidates: [PULSE_EXPORTS],
  commands: (ctx) => [
    {
      id: "exports.open",
      title: ctx.t("exports.cmd.open"),
      icon: Download,
      keywords: ["excel", "csv", "xlsx", "export", "экспорт", "eksport"],
      run: () => ctx.go("exports"),
    },
  ],
  messages: async () => {
    const [uz, ru, en] = await Promise.all([import("./i18n/uz.json"), import("./i18n/ru.json"), import("./i18n/en.json")]);
    return { uz: uz.default, ru: ru.default, en: en.default };
  },
});
