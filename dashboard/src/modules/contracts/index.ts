/**
 * The contracts vault (Shartnomalar, v12 C, `apps.contracts`): the business's own leases,
 * supply and service contracts, licences and insurance, with the signed scan and annexes, the
 * dates (a reminder before each one ends and before an auto-renewal's notice deadline), and the
 * rent in the cash forecast through a recurring payment. Employment contracts stay in HR.
 * Reading needs finance.view (rent and payments); changing finance.manage too.
 */
import { FilePlus2, FileSignature } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";
import { counter } from "@/core/pulse";

import { lazy, routes } from "./routes";

export default defineModule({
  id: "contracts",
  group: "money",
  order: 37,
  icon: FileSignature,
  title: "contracts.title",
  perm: "finance.view",
  routes,
  // The badge: contracts ending soon or waiting for a renewal decision.
  nav: [{ key: "list", title: "contracts.title", to: "contracts", perm: "finance.view", badge: counter("contracts") }],
  badge: counter("contracts"),
  // A recurring payment's bills and payments come from the ledger.
  invalidates: ["contracts", "finance"],
  commands: (ctx) => [
    {
      id: "contracts.open",
      title: ctx.t("contracts.cmd.open"),
      icon: FileSignature,
      keywords: ["shartnoma", "договор", "contract", "ijara", "аренда", "lease", "yetkazib berish", "поставка"],
      perm: "finance.view",
      run: () => ctx.go("contracts"),
    },
    {
      id: "contracts.new",
      title: ctx.t("contracts.cmd.new"),
      icon: FilePlus2,
      keywords: ["shartnoma qo‘shish", "новый договор", "new contract", "ijara shartnomasi"],
      perm: "finance.manage",
      run: () => ctx.go("contracts?new=1"),
    },
  ],
  settings: [
    {
      id: "contracts",
      title: "contracts.settings.title",
      perm: "finance.manage",
      order: 48,
      icon: FileSignature,
      component: defineAsyncComponent(() => lazy().then((m) => m.panels.settings())),
    },
  ],
  deepLinks: {
    contracts: () => "contracts",
    contract: (id) => (/^\d+$/.test(id) ? `contracts/${id}` : "contracts"),
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
