/**
 * The edition at runtime (core/edition.ts, docs/DAVOMAT.md §1.1): what `GET edition/` says decides
 * which modules are registered; a server that can't be reached keeps the edition this browser saw
 * last; items narrow their editions; a module may bring several sidebar rows; "Remember me".
 */
// The registry first, as in the app.
import "@/core/modules";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";

import { allowed, isModuleVisible } from "@/core/access";
import { DAYBOOK_INFO, editionInfo, inEdition, loadEdition, moduleEditions, normalizeEdition, refreshEdition, setEditionInfo } from "@/core/edition";
import { allModules, applyEdition, defineModule, findModule, modules, modulesFor } from "@/core/modules";
import { buildNav, moduleRows } from "@/core/nav";
import { endForgottenSession, forgetsOnClose, rememberSession } from "@/core/remember";
import { company, json } from "@/test/fixtures";

const Icon = defineComponent({ render: () => h("svg") });
const Page = defineComponent({ render: () => h("div") });

const DAVOMAT = {
  edition: "davomat",
  product: "Davomat",
  organization: { name: "Namuna MChJ", logo_url: "/media/logo.png" },
  needs_setup: false,
  default_language: "ru",
  languages: ["uz", "ru", "en"],
  telegram: { configured: true, bot_username: "namuna_bot" },
};

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    // jsdom has storage.
  }
  document.cookie = "dvm_alive=; path=/; max-age=0";
});

afterEach(() => {
  vi.unstubAllGlobals();
  setEditionInfo(DAYBOOK_INFO);
  applyEdition("daybook");
});

describe("what the server says", () => {
  it("is read safely: unknown values fall back, needs_setup only means something in Davomat", () => {
    expect(normalizeEdition(null)).toEqual(DAYBOOK_INFO);
    expect(normalizeEdition({ edition: "mystery" }).edition).toBe("daybook");
    expect(normalizeEdition({ edition: "daybook", needs_setup: true }).needs_setup).toBe(false);
    const info = normalizeEdition({ ...DAVOMAT, languages: ["uz", "xx"], default_language: "de", organization: { name: "N", logo_url: "" } });
    expect(info).toMatchObject({ edition: "davomat", product: "Davomat", default_language: "uz", languages: ["uz"], organization: { name: "N", logo_url: null } });
    expect(normalizeEdition({ edition: "davomat", needs_setup: true }).needs_setup).toBe(true);
    // The setup code matters only while the wizard can still run.
    expect(normalizeEdition({ edition: "davomat", needs_setup: true }).setup_token_required).toBe(false);
    expect(normalizeEdition({ edition: "davomat", needs_setup: true, setup_token_required: true }).setup_token_required).toBe(true);
    expect(normalizeEdition({ edition: "davomat", needs_setup: false, setup_token_required: true }).setup_token_required).toBe(false);
  });

  it("loads once at startup and is remembered in this browser", async () => {
    const fetch = vi.fn(async (_url: string) => json(DAVOMAT));
    vi.stubGlobal("fetch", fetch);
    const info = await loadEdition();
    expect(String(fetch.mock.calls[0]![0])).toBe("/api/v1/owner/edition/");
    expect(info.edition).toBe("davomat");
    expect(editionInfo.value.organization?.name).toBe("Namuna MChJ");
    expect(window.localStorage.getItem("daybook.console.edition")).toBe('"davomat"');
  });

  it("is Daybook when the backend has no such endpoint", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Not found." }, 404)));
    expect((await loadEdition()).edition).toBe("daybook");
  });

  it("keeps a Davomat console Davomat when the server can't be reached at startup", async () => {
    window.localStorage.setItem("daybook.console.edition", '"davomat"');
    const fetch = vi.fn(async () => {
      throw new TypeError("offline");
    });
    vi.stubGlobal("fetch", fetch);
    const info = await loadEdition({ retries: 2, delayMs: 1 });
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(info.edition).toBe("davomat");
    // A fresh browser that never saw this server: Daybook.
    window.localStorage.clear();
    expect((await loadEdition({ retries: 0 })).edition).toBe("daybook");
  });

  it("refreshes after the setup wizard and keeps what it knew on a failure", async () => {
    setEditionInfo(normalizeEdition({ ...DAVOMAT, needs_setup: true, organization: null }));
    vi.stubGlobal("fetch", vi.fn(async () => json(DAVOMAT)));
    expect((await refreshEdition()).needs_setup).toBe(false);
    vi.stubGlobal("fetch", vi.fn(async () => json({}, 500)));
    expect((await refreshEdition()).organization?.name).toBe("Namuna MChJ");
  });
});

describe("the registry per edition", () => {
  it("registers only the edition's modules", () => {
    expect(modules.some((m) => m.id === "davomat")).toBe(false);
    applyEdition("davomat");
    const ids = modules.map((m) => m.id);
    expect(ids).toContain("davomat");
    expect(ids).toContain("faceid");
    expect(ids).not.toContain("tasks");
    expect(ids).not.toContain("auth");
    expect(findModule("finance")).toBeUndefined();
    applyEdition("daybook");
    expect(modules.map((m) => m.id)).toEqual(modulesFor("daybook").map((m) => m.id));
    expect(allModules.length).toBe(new Set([...modulesFor("daybook"), ...modulesFor("davomat")]).size);
  });

  it("names the product in a shared module's texts: Face ID says Davomat in Davomat, Daybook in Daybook", async () => {
    setEditionInfo(normalizeEdition(DAVOMAT));
    applyEdition("davomat");
    const shown = (await findModule("faceid")!.messages("en")) as Record<string, string>;
    expect(shown["faceid.people.notInDaybook"]).toBe("Not in Davomat");
    expect(Object.values(shown).some((text) => text.includes("Daybook"))).toBe(false);
    applyEdition("daybook");
    const own = (await findModule("faceid")!.messages("en")) as { default?: Record<string, string> } & Record<string, string>;
    expect((own.default ?? own)["faceid.people.notInDaybook"]).toBe("Not in Daybook");
  });

  it("modules default to Daybook; items follow their module unless they narrow", () => {
    expect(moduleEditions({})).toEqual(["daybook"]);
    expect(inEdition({}, "davomat")).toBe(true);
    expect(inEdition({ editions: ["daybook"] }, "davomat")).toBe(false);
    setEditionInfo(normalizeEdition(DAVOMAT));
    const owner = company();
    expect(allowed(owner, { editions: ["daybook"] })).toBe(false);
    expect(allowed(owner, {})).toBe(true);
    const daybookOnly = defineModule({ id: "x", group: "work", order: 1, icon: Icon, title: "x.title", routes: [], messages: async () => ({}) });
    expect(isModuleVisible(daybookOnly, owner)).toBe(false);
    expect(isModuleVisible({ ...daybookOnly, editions: ["davomat"] }, owner)).toBe(true);
  });
});

describe("a module with several sidebar rows", () => {
  const multi = defineModule({
    id: "multi",
    editions: ["daybook"],
    group: "overview",
    order: 10,
    icon: Icon,
    title: "multi.home",
    routes: [
      { path: "", name: "multi.home", component: Page },
      { path: "team", name: "multi.team", component: Page },
      { path: "team/units", name: "multi.units", component: Page, meta: { perm: "members.manage" } },
      { path: "settings", name: "multi.settings", component: Page },
    ],
    nav: [
      { key: "home", title: "multi.home", to: "" },
      { key: "team", title: "multi.team", to: "team", row: { key: "multi.team", title: "multi.teamRow", icon: Icon, group: "people", order: 25, hotkey: "e" } },
      { key: "units", title: "multi.units", to: "team/units", perm: "members.manage" },
      { key: "settings", title: "multi.settings", to: "settings", row: { key: "multi.settings", title: "multi.settings", icon: Icon, group: "company", order: 10 } },
    ],
    messages: async () => ({}),
  });
  const other = defineModule({ id: "other", group: "people", order: 20, icon: Icon, title: "other.title", routes: [{ path: "other", name: "other.page", component: Page }], messages: async () => ({}) });

  it("splits its items into rows", () => {
    const rows = moduleRows(multi);
    expect(rows.map((row) => [row.key, row.group, row.items.map((item) => item.key)])).toEqual([
      ["multi", "overview", ["home"]],
      ["multi.team", "people", ["team", "units"]],
      ["multi.settings", "company", ["settings"]],
    ]);
  });

  it("puts each row in its group, in order, with its own pages", () => {
    const nav = buildNav([multi, other], company());
    expect(nav.map((group) => [group.id, group.modules.map((m) => m.key)])).toEqual([
      ["overview", ["multi"]],
      ["people", ["other", "multi.team"]],
      ["company", ["multi.settings"]],
    ]);
    const team = nav[1]!.modules[1]!;
    expect(team).toMatchObject({ title: "multi.teamRow", path: "/c/1/team", hotkey: "e", moduleId: "multi" });
    expect(team.children.map((child) => child.key)).toEqual(["multi:team", "multi:units"]);
  });

  it("drops a row's pages the person can't open, and the row when none is left", () => {
    const nav = buildNav([multi], company({ is_owner: false, permissions: ["dashboard.access"] }));
    const team = nav.find((group) => group.id === "people")!.modules[0]!;
    expect(team.children).toEqual([]);
    expect(team.path).toBe("/c/1/team");
  });
});

describe("Remember me", () => {
  it("signs out at the next start after the browser was closed, only when asked not to remember", async () => {
    const fetch = vi.fn(async (_url: string) => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    rememberSession(false);
    expect(forgetsOnClose()).toBe(true);
    // Same browser session (the cookie is there): nothing happens.
    expect(await endForgottenSession()).toBe(false);
    expect(fetch).not.toHaveBeenCalled();
    // The browser closed: its session cookie is gone.
    document.cookie = "dvm_alive=; path=/; max-age=0";
    expect(await endForgottenSession()).toBe(true);
    expect(String(fetch.mock.calls[0]![0])).toBe("/api/v1/owner/auth/logout/");
    expect(forgetsOnClose()).toBe(false);
  });

  it("keeps the session when the person ticked Remember me", async () => {
    const fetch = vi.fn(async (_url: string) => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    rememberSession(true);
    document.cookie = "dvm_alive=; path=/; max-age=0";
    expect(await endForgottenSession()).toBe(false);
    expect(fetch).not.toHaveBeenCalled();
  });
});
