// The registry first, as in the app.
import "@/core/modules";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { configureHttp } from "@/api/http";
import type { Me } from "@/api/types";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { company, json, manager, me } from "@/test/fixtures";

import { createAppRouter } from "../router";

/** A fresh app state whose backend answers refresh and me/ as given. */
function boot(answer: { refresh: number; me?: Me }) {
  setActivePinia(createPinia());
  const session = useSessionStore();
  configureHttp({ getToken: () => session.accessToken, setToken: (token) => session.setAccess(token), onSessionEnded: () => session.endSession() });
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      if (url.endsWith("/owner/auth/refresh/")) return answer.refresh === 200 ? json({ access: "token" }) : json({ detail: "Sign in again.", code: "session_ended" }, answer.refresh);
      if (url.endsWith("/owner/me/")) return json(answer.me ?? me());
      return json({ detail: "Not found." }, 404);
    }),
  );
  return { router: createAppRouter(), calls, session };
}

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    // jsdom always has storage; the app copes without it.
  }
});

afterEach(() => vi.unstubAllGlobals());

describe("guards", () => {
  it("sends a signed-out person to /login and remembers where they were going", async () => {
    const { router, calls } = boot({ refresh: 401 });
    await router.push("/c/1/inbox?tab=notifications");
    expect(router.currentRoute.value.path).toBe("/login");
    expect(router.currentRoute.value.query.next).toBe("/c/1/inbox?tab=notifications");
    // One refresh attempt on boot, no me/ without a token.
    expect(calls.filter((c) => c.endsWith("/refresh/"))).toHaveLength(1);
    expect(calls.some((c) => c.endsWith("/owner/me/"))).toBe(false);
  });

  it("restores the session from the refresh cookie and opens the requested company", async () => {
    const { router, session } = boot({ refresh: 200, me: me([company(), manager(["dashboard.access"])]) });
    await router.push("/c/2/inbox");
    expect(router.currentRoute.value.fullPath).toBe("/c/2/inbox");
    expect(session.signedIn).toBe(true);
    expect(useCompanyStore().currentId).toBe(2);
  });

  it("moves a company the person can't open to the same page in one they can", async () => {
    const { router } = boot({ refresh: 200 });
    await router.push("/c/99/inbox");
    expect(router.currentRoute.value.fullPath).toBe("/c/1/inbox");
  });

  it("opens the company overview from / and the welcome page without any company", async () => {
    const first = boot({ refresh: 200 });
    await first.router.push("/");
    expect(first.router.currentRoute.value.path).toBe("/c/1");
    expect(first.router.currentRoute.value.name).toBe("overview.today");

    const none = boot({ refresh: 200, me: me([]) });
    await none.router.push("/");
    expect(none.router.currentRoute.value.name).toBe("welcome");
  });

  it("skips the login page for someone already signed in", async () => {
    const { router } = boot({ refresh: 200 });
    await router.push("/login?next=/c/1/exports");
    expect(router.currentRoute.value.fullPath).toBe("/c/1/exports");
    // Another site is never a destination: "/" instead, which opens the default company.
    await router.push("/login?next=https://evil.example");
    expect(router.currentRoute.value.fullPath).toBe("/c/1");
  });
});

describe("the first company", () => {
  it("opens the main company on a first visit, the last one used after that", () => {
    setActivePinia(createPinia());
    const distributor = manager([], { id: 41, name: "Demo Distribyutor", is_owner: true, branches: [{ id: 9, name: "Ombor", code: "OMB" }] });
    const pharmacy = company({ id: 40, name: "Demo Dorixona", branches: [{ id: 1, name: "Chilonzor", code: "CHL" }, { id: 2, name: "Yunusobod", code: "YUN" }] });
    useSessionStore().me = me([distributor, pharmacy]);
    localStorage.removeItem("daybook.console.lastCompany");
    const store = useCompanyStore();
    expect(store.defaultCompanyId()).toBe(40);
    store.setCurrent(41);
    expect(store.defaultCompanyId()).toBe(41);
  });

  it("follows the company picked last in the bot or the mini app", () => {
    setActivePinia(createPinia());
    const distributor = manager([], { id: 41, name: "Demo Distribyutor", is_owner: true });
    const pharmacy = company({ id: 40, name: "Demo Dorixona" });
    useSessionStore().me = { ...me([distributor, pharmacy]), bot_company: 41 };
    const store = useCompanyStore();
    store.setCurrent(40);
    expect(store.defaultCompanyId()).toBe(41);
  });
});
