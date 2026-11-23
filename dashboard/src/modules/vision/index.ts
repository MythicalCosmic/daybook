/**
 * Ko‘z (docs/KOZ.md): the pharmacy's cameras become a sensor. A Ko‘z box at the pharmacy counts
 * people, queues and who stands at the counter, and sends only numbers, alerts and, on request,
 * pictures and short clips. Here: the day by hour (visitors against receipts, waits, staff), the
 * live view with its TV mode, alerts with their photo and video, moments worth a look (voids and
 * payouts with nobody at the counter), cameras and boxes with pairing and the zone editor, and the
 * settings. Behind the `vision` switch; `vision.view`, `vision.video` (live pictures and clips) and
 * `vision.manage` (boxes, cameras, zones, rules). Sales' receipts get a "Video" through
 * `sales.entry.actions`. Pages and the API load on first use.
 */
import { Cctv, Plus } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

import { FIXTURES } from "./mode";
import { lazy, routes } from "./routes";

export default defineModule({
  id: "vision",
  group: "insights",
  order: 5,
  icon: Cctv,
  title: "vision.title",
  perm: "vision.view",
  // Fixture mode (dev server only) runs against a backend that doesn't know the switch yet.
  feature: FIXTURES ? undefined : "vision",
  hotkey: "v",
  routes,
  nav: [
    { key: "overview", title: "vision.nav.overview", to: "vision", exact: true },
    { key: "live", title: "vision.nav.live", to: "vision/live" },
    { key: "alerts", title: "vision.nav.alerts", to: "vision/alerts" },
    { key: "review", title: "vision.nav.review", to: "vision/review", perm: "vision.video" },
    { key: "cameras", title: "vision.nav.cameras", to: "vision/cameras", perm: "vision.manage" },
    { key: "settings", title: "vision.nav.settings", to: "vision/settings" },
  ],
  // Alerts, cameras, boxes and settings (apps/vision); the live view polls on its own.
  invalidates: ["vision"],
  commands: (ctx) => [
    {
      id: "vision.live",
      title: ctx.t("vision.cmd.live"),
      icon: Cctv,
      keywords: ["kamera", "камера", "camera", "navbat", "очередь", "queue"],
      run: () => ctx.go("vision/live"),
    },
    {
      id: "vision.tv",
      title: ctx.t("vision.cmd.tv"),
      icon: Cctv,
      keywords: ["tv", "televizor", "телевизор", "ekran", "экран"],
      run: () => ctx.go("vision/live?tv=1"),
    },
    {
      id: "vision.pair",
      title: ctx.t("vision.cmd.pair"),
      icon: Plus,
      keywords: ["ko‘z", "quti", "бокс", "box", "ulash"],
      perm: "vision.manage",
      run: () => ctx.go("vision/cameras?pair=1"),
    },
  ],
  extensions: {
    "sales.entry.actions": [defineAsyncComponent(() => lazy().then((m) => m.parts.saleVideo()))],
  },
  // `startapp=koz` opens the live view, `koz_<alert id>` that alert (the bots' buttons).
  deepLinks: {
    koz: (id) => (/^\d+$/.test(id) ? `vision/alerts?alert=${id}` : "vision/live"),
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
