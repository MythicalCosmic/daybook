/**
 * Face ID (v8 F): face recognition terminals at the staff door. The live feed of every scan with
 * its snapshot, everyone the terminals know (linked to a Daybook person or not), the terminals with
 * their three-step setup, and the settings. Its own module switch (`face_id`), attendance's
 * permissions. Pages and the API load on first use.
 */
import { ScanFace, UserPlus } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";
import { counter } from "@/core/pulse";

import { routes } from "./routes";

export default defineModule({
  id: "faceid",
  group: "people",
  order: 21,
  icon: ScanFace,
  title: "faceid.title",
  perm: "attendance.view",
  feature: "face_id",
  // Numbers the terminals saw that nobody is linked to.
  badge: counter("faceid.unlinked"),
  routes,
  nav: [
    { key: "live", title: "faceid.nav.live", to: "faceid", exact: true },
    { key: "people", title: "faceid.nav.people", to: "faceid/people", badge: counter("faceid.unlinked") },
    { key: "terminals", title: "faceid.nav.terminals", to: "faceid/terminals", perm: "attendance.manage" },
    { key: "settings", title: "faceid.nav.settings", to: "faceid/settings", perm: "attendance.manage" },
  ],
  // Scans, links, terminals and settings (apps/faceid/hooks.py); check-ins move attendance too.
  invalidates: ["faceid"],
  commands: (ctx) => [
    {
      id: "faceid.live",
      title: ctx.t("faceid.cmd.live"),
      icon: ScanFace,
      keywords: ["face", "yuz", "лицо", "terminal", "kim keldi", "кто пришёл"],
      run: () => ctx.go("faceid"),
    },
    {
      id: "faceid.addTerminal",
      title: ctx.t("faceid.cmd.add"),
      icon: UserPlus,
      keywords: ["hikvision", "terminal", "терминал", "qurilma"],
      perm: "attendance.manage",
      run: () => ctx.go("faceid/terminals?add=1"),
    },
  ],
  deepLinks: {
    faceid: () => "faceid",
  },
  extensions: {
    "attendance.today.faces": [defineAsyncComponent(() => import("./components/TodayFacePanel.vue"))],
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
