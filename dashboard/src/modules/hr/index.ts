/**
 * HR (plan §3.11, §4.10, §6.2; package G's dashboard): the overview of what needs attention
 * (expiring documents, contracts ending, probation ending, birthdays), documents with the
 * compliance matrix, contracts and their templates, celebrations; policies and hiring come later.
 * Adds the "HR" tab to Person 360 and the HR panel to Settings. Kept tiny: pages and the API load
 * on first use.
 */
import { FilePlus2, FileSignature, IdCard } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";
import { counter } from "@/core/pulse";

import { routes } from "./routes";

export default defineModule({
  id: "hr",
  group: "people",
  order: 40,
  icon: IdCard,
  title: "hr.title",
  perm: ["hr.view", "hr.hiring"],
  feature: "hr",
  hotkey: "h",
  badge: counter("hr.expiring"),
  routes,
  nav: [
    { key: "overview", title: "hr.nav.overview", to: "hr", perm: "hr.view", exact: true },
    { key: "documents", title: "hr.nav.documents", to: "hr/documents", perm: "hr.view", badge: counter("hr.expiring") },
    { key: "contracts", title: "hr.nav.contracts", to: "hr/contracts", perm: "hr.view" },
    { key: "templates", title: "hr.nav.templates", to: "hr/contract-templates", perm: "hr.manage" },
    { key: "celebrations", title: "hr.nav.celebrations", to: "hr/celebrations", perm: "hr.view" },
    { key: "policies", title: "hr.nav.policies", to: "hr/policies", perm: "hr.view" },
    { key: "hiring", title: "hr.nav.hiring", to: "hr/hiring", perm: "hr.hiring" },
  ],
  invalidates: ["hr"],
  commands: (ctx) => [
    {
      id: "hr.upload",
      title: ctx.t("hr.cmd.upload"),
      icon: FilePlus2,
      perm: "hr.manage",
      keywords: ["document", "medical book", "tibbiy daftarcha", "hujjat", "медкнижка", "документ", "sertifikat"],
      run: () => ctx.go("hr/documents?upload=1"),
    },
    {
      id: "hr.contract",
      title: ctx.t("hr.cmd.contract"),
      icon: FileSignature,
      perm: "hr.manage",
      keywords: ["contract", "shartnoma", "договор", "mehnat"],
      run: () => ctx.go("hr/contracts?new=1"),
    },
  ],
  personTabs: [
    {
      id: "hr",
      title: "hr.tab",
      perm: "hr.view",
      order: 20,
      component: defineAsyncComponent(() => import("./components/PersonHrTab.vue")),
    },
  ],
  settings: [
    {
      id: "hr",
      title: "hr.settings.title",
      perm: "hr.manage",
      feature: "hr",
      order: 45,
      icon: IdCard,
      component: defineAsyncComponent(() => import("./components/HrSettingsPanel.vue")),
    },
  ],
  deepLinks: {
    contract: (id) => (/^\d+$/.test(id) ? `hr/contracts?contract=${id}` : "hr/contracts"),
    document: (id) => (/^\d+$/.test(id) ? `hr/documents?document=${id}` : "hr/documents"),
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
