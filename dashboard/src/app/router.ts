/**
 * The router, built from the module registry (plan §6.5): `/login` from the auth module's
 * `publicRoutes` (a placeholder until package A lands), `/c/:companyId` = AppShell with every
 * module's `routes` as children, signed-in company-less pages (`rootRoutes`, e.g. the portfolio).
 */
import { defineComponent } from "vue";
import { createRouter, createWebHistory, type RouteRecordRaw, type Router } from "vue-router";

import { modules as registry, type DashboardModule } from "@/core/modules";
import AppShell from "@/shell/AppShell.vue";

import { installGuards } from "./guards";

const NotFoundPage = () => import("@/shell/NotFoundPage.vue");
/** "/" only ever redirects (guards.ts); this renders nothing for the instant it is current. */
const Redirecting = defineComponent({ name: "Redirecting", render: () => null });

/** Copies a route tree, stamping the owning module id into every record's meta. */
export function stampModule(record: RouteRecordRaw, moduleId: string): RouteRecordRaw {
  const children = record.children?.map((child) => stampModule(child, moduleId));
  return { ...record, meta: { ...record.meta, module: moduleId }, ...(children ? { children } : {}) } as RouteRecordRaw;
}

export function buildRoutes(list: readonly DashboardModule[] = registry): RouteRecordRaw[] {
  const publicRoutes = list.flatMap((m) => (m.publicRoutes ?? []).map((r) => stampModule({ ...r, meta: { ...r.meta, public: true } }, m.id)));
  const rootRoutes = list.flatMap((m) => (m.rootRoutes ?? []).map((r) => stampModule({ ...r, meta: { ...r.meta, companyless: true } }, m.id)));
  const companyRoutes = list.flatMap((m) => m.routes.map((r) => stampModule(r, m.id)));
  if (!companyRoutes.some((r) => r.path === "")) {
    companyRoutes.unshift({ path: "", name: "company-home", component: Redirecting });
  }

  const hasLogin = publicRoutes.some((r) => r.path === "/login");
  const routes: RouteRecordRaw[] = [...publicRoutes];
  if (!hasLogin) {
    routes.push({ path: "/login", name: "login", component: () => import("@/shell/LoginPlaceholder.vue"), meta: { public: true } });
  }
  if (import.meta.env.DEV && !publicRoutes.some((r) => r.path === "/dev/login")) {
    routes.push({ path: "/dev/login", name: "dev-login", component: () => import("@/shell/DevLoginPage.vue"), meta: { public: true } });
  }
  routes.push({ path: "/session-ended", name: "session-ended", component: () => import("@/shell/SessionEndedPage.vue"), meta: { public: true } });
  routes.push(
    {
      path: "/",
      component: AppShell,
      meta: { companyless: true },
      children: [
        { path: "", name: "root", component: Redirecting, meta: { companyless: true } },
        { path: "welcome", name: "welcome", component: () => import("@/shell/WelcomePage.vue"), meta: { companyless: true } },
        ...rootRoutes,
      ],
    },
    {
      path: "/c/:companyId(\\d+)",
      component: AppShell,
      children: [...companyRoutes, { path: ":pathMatch(.*)*", name: "company-not-found", component: NotFoundPage }],
    },
    { path: "/:pathMatch(.*)*", name: "not-found", component: NotFoundPage, meta: { public: true } },
  );
  return routes;
}

export function createAppRouter(list: readonly DashboardModule[] = registry): Router {
  const router = createRouter({
    history: createWebHistory("/dashboard/"),
    routes: buildRoutes(list),
    scrollBehavior: (to, from, saved) => {
      if (saved) return saved;
      // Opening a drawer or changing a filter keeps the scroll position.
      if (to.path === from.path) return false;
      return { top: 0 };
    },
  });
  installGuards(router);
  return router;
}
