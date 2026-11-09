/**
 * The guards in the Davomat edition (docs/DAVOMAT.md §1.1–§1.2): before the first run every
 * address opens the setup wizard; after it the wizard is closed; signing in is the password page;
 * the home is Davomat's Overview.
 */
// The registry first, as in the app.
import "@/core/modules";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { configureHttp } from "@/api/http";
import { DAYBOOK_INFO, normalizeEdition, setEditionInfo } from "@/core/edition";
import { applyEdition } from "@/core/modules";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";

import { createAppRouter } from "../router";

function davomat(needsSetup: boolean) {
  setEditionInfo(
    normalizeEdition({
      edition: "davomat",
      product: "Davomat",
      organization: needsSetup ? null : { name: "Namuna MChJ", logo_url: null },
      needs_setup: needsSetup,
    }),
  );
  applyEdition("davomat");
}

function boot(refresh: number) {
  setActivePinia(createPinia());
  const session = useSessionStore();
  configureHttp({ getToken: () => session.accessToken, setToken: (token) => session.setAccess(token), onSessionEnded: () => session.endSession() });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.endsWith("/owner/auth/refresh/")) return refresh === 200 ? json({ access: "token" }) : json({ detail: "Sign in again." }, refresh);
      if (url.endsWith("/owner/me/")) return json(me([company({ features: ["attendance", "face_id"] })]));
      return json({ detail: "Not found." }, 404);
    }),
  );
  return { router: createAppRouter(), session };
}

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    // jsdom has storage.
  }
});

afterEach(() => {
  vi.unstubAllGlobals();
  setEditionInfo(DAYBOOK_INFO);
  applyEdition("daybook");
});

describe("Davomat guards", () => {
  it("opens the setup wizard at any address before the first run", async () => {
    davomat(true);
    const { router } = boot(401);
    await router.push("/c/1/team");
    expect(router.currentRoute.value.name).toBe("setup");
    await router.push("/login");
    expect(router.currentRoute.value.name).toBe("setup");
  });

  it("closes the wizard once the organization exists", async () => {
    davomat(false);
    const signedOut = boot(401);
    await signedOut.router.push("/setup");
    expect(signedOut.router.currentRoute.value.name).toBe("login");

    const signedIn = boot(200);
    await signedIn.router.push("/setup");
    expect(signedIn.router.currentRoute.value.path).toBe("/c/1");
  });

  it("sends a signed-out person to the password sign-in, and home is the Overview", async () => {
    davomat(false);
    const out = boot(401);
    await out.router.push("/c/1/team");
    expect(out.router.currentRoute.value.path).toBe("/login");
    expect(out.router.currentRoute.value.query.next).toBe("/c/1/team");
    // Davomat's own page, not Daybook's Telegram one.
    expect(out.router.currentRoute.value.matched[0]?.meta.module).toBe("davomat");

    const signed = boot(200);
    await signed.router.push("/");
    expect(signed.router.currentRoute.value.name).toBe("davomat.overview");
  });

  it("sends old links to a person (people/17) to their page in Team", async () => {
    davomat(false);
    const { router } = boot(200);
    await router.push("/c/1/people/17");
    expect(router.currentRoute.value.name).toBe("davomat.employee");
    expect(router.currentRoute.value.params.employeeId).toBe("17");
  });

  it("leaves Daybook as it was: no setup wizard, no Davomat pages", async () => {
    const { router } = boot(200);
    await router.push("/setup");
    expect(router.currentRoute.value.name).toBe("not-found");
    await router.push("/c/1/team");
    expect(router.currentRoute.value.name).toBe("company-not-found");
  });
});
