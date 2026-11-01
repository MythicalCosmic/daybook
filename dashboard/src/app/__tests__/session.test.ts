import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSessionStore } from "@/stores/session";
import { me } from "@/test/fixtures";

afterEach(() => vi.unstubAllGlobals());

describe("signing out", () => {
  it("ends the session even when the server can't be reached (the error stopped the way to the login page)", async () => {
    setActivePinia(createPinia());
    const session = useSessionStore();
    session.me = me();
    session.setAccess("token");
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(session.logout()).resolves.toBeUndefined();
    expect(session.signedIn).toBe(false);
  });
});
