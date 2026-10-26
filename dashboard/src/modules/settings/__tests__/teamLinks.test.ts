// Team links (Settings › Invite staff): words and numbers, the endpoints, the dialog, the live
// screen's polling and the path from "New team link" to its live screen.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { confirmQueue } from "@/components/useConfirm";
import { mergeModuleMessages, i18n } from "@/i18n";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";
import { useSessionStore } from "@/stores/session";

import { createJoinLink, deleteJoinLink, getJoinLink, listJoinLinks, updateJoinLink } from "../api";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import module from "../index";
import { roomLanguages } from "../roomLanguages";
import {
  ENDED_OPEN_MAX,
  botOf,
  defaultName,
  endText,
  expiresAt,
  expiryProblem,
  groupLinks,
  livePeople,
  localToIso,
  placesLeft,
  placesText,
  ruleParts,
  statusNow,
  telegramShare,
  validForOf,
  whenText,
} from "../teamLinks";
import type { CompanySettings, JoinLink, JoinLinkDetail, JoinLinkPerson } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, (call: Call) => Response | Promise<Response>>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = url.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const t = (key: string, params?: Record<string, unknown>) => i18n.global.t(key, params ?? {});
const TZ = "Asia/Tashkent";
// 26 Oct 2026, 10:00 in Tashkent.
const NOW = Date.parse("2026-10-26T05:00:00Z");

function link(overrides: Partial<JoinLink> = {}): JoinLink {
  return {
    id: 1,
    name: "Xodimlar yig‘ilishi",
    link: "https://t.me/daybook_staff_bot?start=j_abc123",
    start_param: "j_abc123",
    auto_approve: true,
    branch: { id: 1, name: "Chilonzor" },
    role: { id: 4, name: "Farmatsevt" },
    default_role: { id: 3, name: "Xodim" },
    position: null,
    max_uses: 20,
    uses: 12,
    expires_at: "2026-10-27T13:00:00Z",
    is_active: true,
    status: "active",
    created_by: { id: 11, name: "Dilnoza Karimova" },
    created_at: "2026-10-26T04:00:00Z",
    can_edit: true,
    ...overrides,
  };
}

function person(id: number, overrides: Partial<JoinLinkPerson> = {}): JoinLinkPerson {
  return { id, name: `Person ${id}`, photo_url: null, position: { id: 9, name: "Farmatsevt" }, status: "approved", onboarded: true, joined_at: "2026-10-26T04:30:00Z", ...overrides };
}

const SETTINGS = { id: 1, name: "Demo Dorixona", default_language: "uz", timezone: TZ } as CompanySettings;
const ROLES = [
  { id: 1, name: "Egasi", is_owner: true, is_default: false, can_assign: true },
  { id: 3, name: "Xodim", is_owner: false, is_default: true, can_assign: true },
  { id: 4, name: "Farmatsevt", is_owner: false, is_default: false, can_assign: true },
  { id: 5, name: "Filial rahbari", is_owner: false, is_default: false, can_assign: false },
];
const POSITIONS = [{ id: 9, name: "Farmatsevt", is_active: true }];

beforeEach(() => {
  mergeModuleMessages("settings", { en, ru, uz });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  confirmQueue.value = [];
  document.body.innerHTML = "";
});

describe("lists and status", () => {
  it("keeps active and full links live, in the server's order, and puts stopped and expired ones under Ended", () => {
    const rows = [link({ id: 1 }), link({ id: 2, status: "full" }), link({ id: 3, status: "expired" }), link({ id: 4, status: "stopped" }), link({ id: 5 })];
    const { live, ended } = groupLinks(rows);
    expect(live.map((row) => row.id)).toEqual([1, 2, 5]);
    expect(ended.map((row) => row.id)).toEqual([3, 4]);
    expect(ENDED_OPEN_MAX).toBe(3);
  });

  it("works out the status the server would give: stopped, then expired, then full", () => {
    expect(statusNow(link({ is_active: false, uses: 20 }), NOW)).toBe("stopped");
    expect(statusNow(link({ expires_at: "2026-10-25T00:00:00Z", uses: 20 }), NOW)).toBe("expired");
    expect(statusNow(link({ uses: 20 }), NOW)).toBe("full");
    expect(statusNow(link({ max_uses: null, uses: 400 }), NOW)).toBe("active");
  });
});

describe("words", () => {
  it("counts places, and says 'signed up' for a link that asks first", () => {
    expect(placesText(link(), t)).toBe("12 of 20 joined");
    expect(placesText(link({ max_uses: null }), t)).toBe("12 joined");
    expect(placesText(link({ max_uses: null, uses: 0 }), t)).toBe("No one yet");
    expect(placesText(link({ auto_approve: false, max_uses: null, uses: 2 }), t)).toBe("2 signed up");
    expect(placesLeft(link())).toBe(8);
    expect(placesLeft(link({ uses: 25 }))).toBe(0);
    expect(placesLeft(link({ max_uses: null }))).toBeNull();
  });

  it("says the rule: how people get in, the branch, the role (or the default one) and the position", () => {
    expect(ruleParts(link({ position: { id: 9, name: "Farmatsevt" } }), t)).toEqual(["Adds straight away", "Chilonzor", "Farmatsevt role", "Farmatsevt position"]);
    expect(ruleParts(link({ auto_approve: false, branch: null, role: null }), t)).toEqual(["Asks for your approval", "Xodim role (default)"]);
  });

  it("says when it ends: the time today, the day and time otherwise, and when it ended", () => {
    expect(whenText("2026-10-26T13:00:00Z", TZ, "en", NOW)).toBe("18:00");
    expect(whenText("2026-10-27T13:00:00Z", TZ, "en", NOW)).toBe("27 Oct, 18:00");
    expect(whenText("2026-10-27T13:00:00Z", TZ, "uz", NOW)).toBe("27-okt, 18:00");
    expect(endText(link(), t, TZ, "en", NOW)).toBe("Until 27 Oct, 18:00");
    expect(endText(link({ expires_at: null }), t, TZ, "en", NOW)).toBe("No end date");
    expect(endText(link({ expires_at: "2026-10-25T13:00:00Z" }), t, TZ, "en", NOW)).toBe("Ended 25 Oct, 18:00");
  });

  it("names a new link after its branch, finds the bot for the poster and builds Telegram's share link", () => {
    expect(defaultName(t, "26 Oct")).toBe("Team link, 26 Oct");
    expect(defaultName(t, "26 Oct", "Yunusobod")).toBe("Yunusobod, 26 Oct");
    expect(botOf("https://t.me/daybook_staff_bot?start=j_abc123")).toBe("daybook_staff_bot");
    expect(botOf("")).toBe("");
    expect(telegramShare("https://t.me/b?start=j_1", "Join «Demo»")).toBe("https://t.me/share/url?url=https%3A%2F%2Ft.me%2Fb%3Fstart%3Dj_1&text=Join%20%C2%ABDemo%C2%BB");
  });

  it("shows on the live screen only people signing up or in, newest first", () => {
    const people = [person(1), person(2, { status: "pending", onboarded: false }), person(3, { status: "rejected" }), person(4, { status: "left" }), person(5)];
    expect(livePeople(people, 6).map((p) => p.id)).toEqual([1, 2, 5]);
    expect(livePeople(people, 2).map((p) => p.id)).toEqual([1, 2]);
  });

  it("speaks to a room in the company's language, then Russian (or Uzbek for a Russian company)", () => {
    expect(roomLanguages("uz")).toEqual(["uz", "ru"]);
    expect(roomLanguages("ru")).toEqual(["ru", "uz"]);
    expect(roomLanguages("en")).toEqual(["en", "ru"]);
  });
});

describe("Works for → expires_at", () => {
  it("counts 24 hours, 7 and 30 days from the moment of saving, and none for no end date", () => {
    expect(expiresAt("24h", NOW)).toBe("2026-10-27T05:00:00.000Z");
    expect(expiresAt("7d", NOW)).toBe("2026-11-02T05:00:00.000Z");
    expect(expiresAt("30d", NOW)).toBe("2026-11-25T05:00:00.000Z");
    expect(expiresAt("none", NOW)).toBeNull();
  });

  it("reads a date and time in the company's timezone", () => {
    expect(localToIso("2026-10-27", "18:00", TZ)).toBe("2026-10-27T13:00:00.000Z");
    expect(expiresAt("date", NOW, { day: "2026-10-27", time: "18:00", tz: TZ })).toBe("2026-10-27T13:00:00.000Z");
    expect(expiresAt("date", NOW, { day: null, time: "18:00", tz: TZ })).toBeNull();
  });

  it("refuses an end that has passed or is more than a year away", () => {
    expect(expiryProblem("2026-10-26T04:59:00Z", NOW)).toBe("past");
    expect(expiryProblem("2027-10-27T05:00:00Z", NOW)).toBe("tooFar");
    expect(expiryProblem("2027-10-26T05:00:00Z", NOW)).toBeNull();
    expect(expiryProblem(null, NOW)).toBeNull();
  });

  it("shows an existing end as a date and time, no end as 'No end date', and starts a new link at 7 days", () => {
    expect(validForOf(link(), TZ)).toEqual({ choice: "date", day: "2026-10-27", time: "18:00" });
    expect(validForOf(link({ expires_at: null }), TZ)).toEqual({ choice: "none", day: null, time: null });
    expect(validForOf(null, TZ)).toEqual({ choice: "7d", day: null, time: null });
  });
});

describe("api", () => {
  it("calls the team link endpoints", async () => {
    const calls = stub({
      "GET join-links/": () => json([]),
      "POST join-links/": () => json(link(), 201),
      "GET join-links/1/": () => json({ ...link(), people: [] }),
      "PATCH join-links/1/": () => json(link({ is_active: false, status: "stopped" })),
      "DELETE join-links/1/": () => new Response(null, { status: 204 }),
    });
    await listJoinLinks(1);
    await createJoinLink(1, { name: "Xodimlar yig‘ilishi", auto_approve: true, branch_id: 1, role_id: null, max_uses: 20, expires_at: "2026-11-02T05:00:00.000Z" });
    await getJoinLink(1, 1);
    await updateJoinLink(1, 1, { is_active: false });
    await deleteJoinLink(1, 1);
    expect(calls.map((c) => `${c.method} ${c.url.replace("/api/v1/owner/companies/1/", "")}`)).toEqual([
      "GET join-links/",
      "POST join-links/",
      "GET join-links/1/",
      "PATCH join-links/1/",
      "DELETE join-links/1/",
    ]);
    expect(calls[1]!.body).toEqual({ name: "Xodimlar yig‘ilishi", auto_approve: true, branch_id: 1, role_id: null, max_uses: 20, expires_at: "2026-11-02T05:00:00.000Z" });
    expect(calls[3]!.body).toEqual({ is_active: false });
  });

  it("refreshes on the members.links pulse key", () => {
    expect(module.invalidates).toEqual(expect.arrayContaining(["companies", "members.links"]));
  });
});

describe("TeamLinkDialog", () => {
  const routes = () => ({
    "GET roles/": () => json(ROLES),
    "GET positions/": () => json(POSITIONS),
    "POST join-links/": (call: Call) => json(link({ id: 7, ...(call.body as object) }), 201),
    "PATCH join-links/1/": (call: Call) => json(link(call.body as Partial<JoinLink>)),
  });
  const submit = () => document.querySelector<HTMLFormElement>("#team-link-form")!.dispatchEvent(new Event("submit", { cancelable: true }));
  const chip = (text: string) => [...document.querySelectorAll<HTMLButtonElement>("button.team-chip")].find((b) => b.textContent?.trim() === text)!;

  it("makes a link that adds people straight away to the only branch, with the default role, for 7 days", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const calls = stub(routes());
    const app = await testApp("/c/1/settings/invite");
    const { default: TeamLinkDialog } = await import("../components/TeamLinkDialog.vue");
    const { inner } = mountWithProviders(TeamLinkDialog, { plugins: app.plugins, props: { open: true, link: null } });
    await flushPromises();

    expect(document.querySelector<HTMLInputElement>('#team-link-form input[maxlength="100"]')!.value).toBe("Chilonzor, 26 Oct");
    // One branch: nothing to choose.
    expect(document.body.textContent).not.toContain("Pick the branch");
    chip("20").click();
    await flushPromises();
    submit();
    await flushPromises();

    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      name: "Chilonzor, 26 Oct",
      auto_approve: true,
      branch_id: 1,
      role_id: null,
      position_id: null,
      max_uses: 20,
      expires_at: "2026-11-02T05:00:00.000Z",
    });
    expect(inner.emitted("saved")?.[0]?.[1]).toBe(true);
  });

  it("asks for a branch when there are two and people are added straight away, and warns about a link with no limit and no end", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const calls = stub(routes());
    const app = await testApp("/c/1/settings/invite");
    useSessionStore().me = me([company({ branches: [{ id: 1, name: "Chilonzor", code: "CHL" }, { id: 2, name: "Yunusobod", code: "YNS" }] })]);
    const { default: TeamLinkDialog } = await import("../components/TeamLinkDialog.vue");
    mountWithProviders(TeamLinkDialog, { plugins: app.plugins, props: { open: true, link: null } });
    await flushPromises();

    expect(document.querySelector<HTMLInputElement>('#team-link-form input[maxlength="100"]')!.value).toBe("Team link, 26 Oct");
    submit();
    await flushPromises();
    expect(document.body.textContent).toContain("Pick the branch they’ll work at");
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    chip("No end date").click();
    await flushPromises();
    expect(document.body.textContent).toContain("Anyone who gets this link can join until you stop it.");
    expect(document.querySelector("[data-end-preview]")!.textContent).toContain("Works until you stop it");
  });

  it("sends only what changed when editing, and keeps the end unless it is touched", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const calls = stub(routes());
    const app = await testApp("/c/1/settings/invite");
    const { default: TeamLinkDialog } = await import("../components/TeamLinkDialog.vue");
    const { inner } = mountWithProviders(TeamLinkDialog, { plugins: app.plugins, props: { open: true, link: link() } });
    await flushPromises();

    const name = document.querySelector<HTMLInputElement>('#team-link-form input[maxlength="100"]')!;
    expect(name.value).toBe("Xodimlar yig‘ilishi");
    // The end shows as its date and time.
    expect(document.querySelector("[data-end-at]")).not.toBeNull();
    name.value = "Xodimlar yig‘ilishi, 2-qavat";
    name.dispatchEvent(new Event("input"));
    chip("No limit").click();
    await flushPromises();
    submit();
    await flushPromises();

    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ name: "Xodimlar yig‘ilishi, 2-qavat", max_uses: null });
    expect(inner.emitted("saved")?.[0]?.[1]).toBe(false);
  });
});

describe("TeamLinkLive", () => {
  function setVisibility(state: "visible" | "hidden"): void {
    Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
    document.dispatchEvent(new Event("visibilitychange", { bubbles: true }));
  }

  afterEach(() => {
    setVisibility("visible");
    Reflect.deleteProperty(navigator, "wakeLock");
  });

  it("asks every 3 s while open and visible, never while hidden or after closing, and keeps the screen awake", async () => {
    vi.useFakeTimers();
    const release = vi.fn(async () => undefined);
    const request = vi.fn(async () => ({ released: false, release }));
    Object.defineProperty(navigator, "wakeLock", { value: { request }, configurable: true });
    const detail: JoinLinkDetail = { ...link(), people: [person(31), person(32, { onboarded: false, status: "pending" })] };
    const calls = stub({ "GET join-links/1/": () => json(detail), "GET settings/": () => json(SETTINGS) });
    const polls = () => calls.filter((c) => c.url.endsWith("/join-links/1/")).length;
    const app = await testApp("/c/1/settings/invite");
    const { default: TeamLinkLive } = await import("../components/TeamLinkLive.vue");
    const { wrapper } = mountWithProviders(TeamLinkLive, { plugins: app.plugins, props: { link: link() } });
    await vi.advanceTimersByTimeAsync(50);

    expect(polls()).toBe(1);
    expect(request).toHaveBeenCalledWith("screen");
    const screen = document.querySelector("[data-team-live]")!;
    expect(screen.textContent).toContain("Xodimlar yig‘ilishi");
    expect(screen.querySelector("[data-live-count]")!.textContent).toContain("12");
    expect(screen.textContent).toContain("8 places left");
    expect(screen.textContent).toContain("Making an account");

    await vi.advanceTimersByTimeAsync(3_000);
    expect(polls()).toBe(2);
    await vi.advanceTimersByTimeAsync(3_000);
    expect(polls()).toBe(3);

    setVisibility("hidden");
    await vi.advanceTimersByTimeAsync(9_000);
    expect(polls()).toBe(3);

    setVisibility("visible");
    await vi.advanceTimersByTimeAsync(50);
    expect(polls()).toBe(4);

    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(9_000);
    expect(polls()).toBe(4);
    expect(release).toHaveBeenCalled();
  });

  it("dims the code and says why when the link can't take anyone", async () => {
    stub({ "GET join-links/1/": () => json({ ...link({ uses: 20, status: "full" }), people: [] }), "GET settings/": () => json(SETTINGS) });
    const app = await testApp("/c/1/settings/invite");
    const { default: TeamLinkLive } = await import("../components/TeamLinkLive.vue");
    mountWithProviders(TeamLinkLive, { plugins: app.plugins, props: { link: link({ uses: 20, status: "full" }) } });
    await flushPromises();
    await flushPromises();
    const closed = document.querySelector("[data-live-closed]");
    expect(closed?.textContent).toContain("All places are taken");
    expect(document.querySelector("[data-team-live]")!.textContent).not.toContain("places left");
  });

  it("closes on Escape", async () => {
    stub({ "GET join-links/1/": () => json({ ...link(), people: [] }), "GET settings/": () => json(SETTINGS) });
    const app = await testApp("/c/1/settings/invite");
    const { default: TeamLinkLive } = await import("../components/TeamLinkLive.vue");
    const { inner } = mountWithProviders(TeamLinkLive, { plugins: app.plugins, props: { link: link() } });
    await flushPromises();
    document.querySelector<HTMLElement>("[data-team-live]")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await flushPromises();
    expect(inner.emitted("close")).toHaveLength(1);
  });
});

describe("TeamLinksSection", () => {
  it("opens a new link's live screen as soon as it is saved", async () => {
    let created: JoinLink | null = null;
    const calls = stub({
      "GET join-links/": () => json(created ? [created] : []),
      "GET roles/": () => json(ROLES),
      "GET positions/": () => json(POSITIONS),
      "GET settings/": () => json(SETTINGS),
      "POST join-links/": (call) => {
        created = link({ id: 7, ...(call.body as object), uses: 0 });
        return json(created, 201);
      },
      "GET join-links/7/": () => json({ ...created!, people: [] }),
    });
    const app = await testApp("/c/1/settings/invite");
    const { default: TeamLinksSection } = await import("../components/TeamLinksSection.vue");
    const { wrapper } = mountWithProviders(TeamLinksSection, { plugins: app.plugins });
    await flushPromises();

    expect(wrapper.text()).toContain("Add a whole team in one go");
    await wrapper.find("[data-new-link]").trigger("click");
    // The dialog and the live screen load on first use.
    await vi.waitFor(() => expect(document.querySelector("#team-link-form")).not.toBeNull());
    await flushPromises();
    document.querySelector<HTMLFormElement>("#team-link-form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.waitFor(() => expect(document.querySelector("[data-team-live]")).not.toBeNull());

    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/join-links/"))).toBe(true);
    expect(document.querySelector("[data-team-live]")!.textContent).toContain("Chilonzor, ");
  });

  it("folds a long Ended group and shows a read-only link without its changing actions", async () => {
    const ended = [3, 4, 5, 6].map((id) => link({ id, status: id % 2 ? "expired" : "stopped", is_active: id % 2 === 1 }));
    stub({ "GET join-links/": () => json([link({ id: 1, can_edit: false }), ...ended]) });
    const app = await testApp("/c/1/settings/invite");
    const { default: TeamLinksSection } = await import("../components/TeamLinksSection.vue");
    const { wrapper } = mountWithProviders(TeamLinksSection, { plugins: app.plugins });
    await flushPromises();

    expect(wrapper.findAll("[data-link]")).toHaveLength(1);
    expect(wrapper.find("[data-ended] button").text()).toContain("Ended (4)");
    await wrapper.find("[data-ended] button").trigger("click");
    expect(wrapper.findAll("[data-link]")).toHaveLength(5);

    const readOnly = wrapper.find('[data-link="1"]');
    expect(readOnly.find("[data-view-only]").exists()).toBe(true);
    await readOnly.find("[data-more]").trigger("click");
    await flushPromises();
    const items = [...document.querySelectorAll("[role=menuitem]")].map((item) => item.textContent?.trim());
    expect(items).toEqual(["Print poster"]);
  });
});
