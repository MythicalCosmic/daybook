/**
 * Development only (VITE_MOCK=1): one placeholder module per catalog entry, so the whole
 * navigation, permission and feature gating, badges, palette and breadcrumbs can be seen before
 * the packages land. A real module with the same id always replaces its placeholder.
 */
import {
  Award,
  Banknote,
  Download,
  Lightbulb,
  MessagesSquare,
  BellRing,
  BookOpen,
  Boxes,
  CalendarDays,
  ChartColumn,
  FolderKanban,
  Handshake,
  IdCard,
  Inbox,
  Landmark,
  LayoutDashboard,
  ListTodo,
  MapPinCheck,
  Megaphone,
  Network,
  Repeat,
  ScrollText,
  Settings,
  Sparkles,
  Store,
  TreePalm,
  Users,
} from "@lucide/vue";
import { defineAsyncComponent, type Component } from "vue";

import { CATALOG } from "@/core/catalog";
import { defineModule, type DashboardModule } from "@/core/modules";
import { counter } from "@/core/pulse";
import { i18n } from "@/i18n";
import { LANGUAGES } from "@/api/types";

import { DEV_MESSAGES, stubMessages } from "./stubMessages";

const ICONS: Record<string, Component> = {
  overview: LayoutDashboard,
  inbox: Inbox,
  tasks: ListTodo,
  projects: FolderKanban,
  routines: Repeat,
  reminders: BellRing,
  people: Users,
  lifecycle: Network,
  attendance: MapPinCheck,
  timeoff: TreePalm,
  hr: IdCard,
  recognition: Award,
  sales: Store,
  stock: Boxes,
  finance: Landmark,
  payroll: Banknote,
  crm: Handshake,
  comms: Megaphone,
  groups: MessagesSquare,
  agenda: CalendarDays,
  knowledge: BookOpen,
  reports: ChartColumn,
  insights: Lightbulb,
  ai: Sparkles,
  settings: Settings,
  exports: Download,
  audit: ScrollText,
};

const StubPage = () => import("./StubPage.vue");
const OverviewPreview = () => import("./OverviewPreview.vue");
const PortfolioStub = () => import("./PortfolioStub.vue");
const NewCompanyStub = defineAsyncComponent(() => import("./NewCompanyStub.vue"));

export function devStubModules(): DashboardModule[] {
  for (const language of LANGUAGES) i18n.global.mergeLocaleMessage(language, DEV_MESSAGES[language]);

  return CATALOG.map((entry) =>
    defineModule({
      id: entry.id,
      group: entry.group,
      order: entry.order,
      icon: ICONS[entry.id] ?? LayoutDashboard,
      title: `${entry.id}.title`,
      perm: entry.perm,
      feature: entry.feature,
      hotkey: entry.hotkey,
      index: entry.pages.some((page) => page.to === "") || undefined,
      badge: entry.badge ? counter(entry.badge) : undefined,
      routes: entry.pages.map((page) => ({
        path: page.to,
        name: `${entry.id}.${page.id}`,
        component: entry.id === "overview" ? OverviewPreview : StubPage,
        meta: { title: `${entry.id}.nav.${page.id}`, perm: page.perm, feature: page.feature },
        props: { pkg: entry.pkg },
      })),
      nav:
        entry.pages.length > 1
          ? entry.pages.map((page) => ({
              key: page.id,
              title: `${entry.id}.nav.${page.id}`,
              to: page.to,
              perm: page.perm,
              feature: page.feature,
              badge: page.badge ? counter(page.badge) : undefined,
            }))
          : undefined,
      rootRoutes: entry.id === "overview" ? [{ path: "portfolio", name: "portfolio", component: PortfolioStub, meta: { title: "dev.portfolio.title" } }] : undefined,
      extensions: entry.id === "settings" ? { "shell.company.create": [NewCompanyStub] } : undefined,
      deepLinks: entry.id === "sales" ? { shift: (id) => `sales/shifts?shift=${id}` } : undefined,
      messages: () => Promise.resolve(stubMessages(entry.id)),
    }),
  );
}
