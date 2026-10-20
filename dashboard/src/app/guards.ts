/**
 * Guards, in order (plan §6.5): signed in (else /login?next=), the company is one of `me.companies`
 * (else the same view in the first allowed company), then the route's perm and feature (else the
 * shell renders ForbiddenPage in place, so the URL stays shareable). Module messages are loaded
 * before a module's page renders.
 */
import type { Router } from "vue-router";

import { findModule } from "@/core/modules";
import { ensureModuleMessages } from "@/i18n";
import { telegram } from "@/shell/TelegramBridge";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

import { pathInCompany } from "./navigation";

/** Only same-app paths are accepted after login (no open redirects). */
export function safeNext(value: unknown): string {
  const next = Array.isArray(value) ? value[0] : value;
  if (typeof next !== "string" || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/";
  return next;
}

export function installGuards(router: Router): void {
  router.beforeEach(async (to) => {
    const session = useSessionStore();
    if (session.status !== "ready") await session.boot(telegram().initData);

    if (to.meta.public) {
      if ((to.name === "login" || to.name === "dev-login") && session.signedIn) return safeNext(to.query.next);
      return true;
    }
    if (!session.signedIn) {
      return { path: "/login", query: to.fullPath === "/" ? {} : { next: to.fullPath } };
    }

    const company = useCompanyStore();
    const param = to.params.companyId;
    if (param !== undefined) {
      const id = Number(Array.isArray(param) ? param[0] : param);
      if (!company.has(id)) {
        const fallback = company.defaultCompanyId();
        if (fallback === null) return { name: "welcome", replace: true };
        return { path: pathInCompany(router, to, fallback), replace: true };
      }
      company.setCurrent(id);
    } else if (to.name === "root") {
      const id = company.defaultCompanyId();
      return id === null ? { name: "welcome", replace: true } : { path: `/c/${id}`, replace: true };
    }

    const module = findModule(to.matched.map((record) => record.meta.module).find(Boolean));
    if (module) {
      try {
        await ensureModuleMessages(module);
      } catch {
        // Missing translations must never block the page; keys show until the retry succeeds.
      }
    }
    return true;
  });
}
