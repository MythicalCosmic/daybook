// Recognition screens against a stubbed API: the leaderboard's podium and table with its filters,
// the settings panel sending only the changed rows of the points table, hiding a thank-you, the
// person panel, "Say thanks" in Person 360's header and the module's registrations.
// The registry first, as in the app (core/modules loads every module's index.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import { extensionsFor } from "@/core/extensions";
import type { CompanyFeature } from "@/core/features";
import { modules } from "@/core/modules";
import type { Perm } from "@/core/perms";
import { mergeModuleMessages } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders as mountRaw, testApp } from "@/test/plugins";

import PersonPanel from "../components/PersonPanel.vue";
import SayThanksAction from "../components/SayThanksAction.vue";
import SettingsPanel from "../components/SettingsPanel.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import { shiftDay } from "../lib";
import KudosPage from "../pages/KudosPage.vue";
import LeaderboardPage from "../pages/LeaderboardPage.vue";
import type { BoardRow, Kudos, Profile, RecognitionSettings } from "../types";

vi.setConfig({ testTimeout: 20_000 });

const mounted: Array<{ unmount: () => void }> = [];
const mountWithProviders: typeof mountRaw = (component, options) => {
  const result = mountRaw(component, options);
  mounted.push(result.wrapper);
  return result;
};

interface Call {
  method: string;
  path: string;
  query: string;
  body: unknown;
}

class NoResize {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

function stub(routesByCall: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("ResizeObserver", NoResize);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const [path, query = ""] = url.replace(/^.*\/api\/v1\/owner\/companies\/1\//, "").split("?") as [string, string?];
      const body = init?.body && typeof init.body === "string" ? JSON.parse(init.body) : undefined;
      const call = { method: init?.method ?? "GET", path, query, body };
      calls.push(call);
      return routesByCall[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) await flushPromises();
}

/** The test app at `path`, signed in to a company with recognition on (after testApp, which signs in). */
async function appAt(path: string, permissions: Perm[] | "owner" = "owner") {
  const app = await testApp(path);
  const features: CompanyFeature[] = ["recognition", "learning"];
  useSessionStore().me = me([permissions === "owner" ? company({ features }) : company({ is_owner: false, permissions, features })]);
  return app;
}

beforeEach(() => {
  mergeModuleMessages("recognition", { en, ru: en, uz: en });
  localStorage.clear();
  confirmQueue.value = [];
});

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

const person = (id: number, name: string) => ({ id, name, avatar_url: null, position: "Farmatsevt" });
const row = (place: number, id: number, name: string, points: number): BoardRow => ({
  place,
  member: person(id, name),
  points,
  level: { number: 2, name: "Learner" },
  badges: 1,
  streak: 3,
});

describe("dictionaries", () => {
  it("have the same keys and placeholders in the three languages", () => {
    const keys = Object.keys(en).sort();
    expect(Object.keys(ru).sort()).toEqual(keys);
    expect(Object.keys(uz).sort()).toEqual(keys);
    const holes = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
    for (const key of keys) {
      const source = en[key as keyof typeof en];
      for (const other of [ru, uz]) {
        const text = other[key as keyof typeof other];
        expect(text, key).toBeTruthy();
        expect(holes(text), key).toEqual(holes(source));
        expect(text.split(" | ").length, key).toBe(source.split(" | ").length);
      }
    }
    for (const text of Object.values(uz)) expect(text).not.toMatch(/'|`/);
  });

  it("moves a week or a month", () => {
    expect(shiftDay("2026-11-07", "week", -1)).toBe("2026-10-31");
    expect(shiftDay("2026-11-07", "month", 1)).toBe("2026-12-01");
    expect(shiftDay("2026-01-15", "month", -1)).toBe("2025-12-01");
  });
});

describe("the leaderboard", () => {
  it("puts the top three on the podium and everyone in the table, and follows the filters", async () => {
    const calls = stub({
      "GET recognition/leaderboard/": () =>
        json({
          period: "week",
          kind: "all",
          start: "2026-11-01T19:00:00Z",
          end: "2026-11-08T19:00:00Z",
          rows: [row(1, 3, "Madina Saidova", 120), row(2, 6, "Nigora Azimova", 90), row(3, 5, "Jasur Tursunov", 40), row(4, 4, "Alisher Valiyev", 25)],
        }),
    });
    const app = await appAt("/c/1/recognition");
    const { wrapper } = mountWithProviders(LeaderboardPage, { plugins: app.plugins });
    await settle();
    const podium = wrapper.find("[data-testid=podium]");
    expect(podium.exists()).toBe(true);
    const names = podium.findAll(".rcg-podium-place").map((place) => place.text());
    expect(names[0]).toContain("Nigora Azimova");
    expect(names[1]).toContain("Madina Saidova");
    expect(names[2]).toContain("Jasur Tursunov");
    expect(wrapper.text()).toContain("Alisher Valiyev");
    expect(wrapper.find("[data-testid=board-span]").text()).toMatch(/2.*8/);
    expect(calls[0]!.query).toContain("period=week");
    await app.router.push("/c/1/recognition?period=month&kind=learning");
    await settle();
    const last = calls.at(-1)!;
    expect(last.query).toContain("period=month");
    expect(last.query).toContain("kind=learning");
  });
});

describe("settings", () => {
  const settings = (): RecognitionSettings => ({
    points_enabled: true,
    leaderboard_for_staff: true,
    leaderboard_scope: "company",
    task_points: true,
    kudos_enabled: true,
    kudos_per_day: 3,
    post_kudos_to_groups: false,
    points_table: {},
    points: [
      { key: "lesson", label: "Lesson watched", default: 10, points: 10 },
      { key: "quiz", label: "Quiz passed (first time)", default: 20, points: 20 },
    ],
    levels: [{ number: 1, name: "Newcomer", starts_at: 0, next_at: 100 }],
  });

  it("sends only the rows that differ from the defaults", async () => {
    const calls = stub({ "GET recognition/settings/": () => json(settings()), "PATCH recognition/settings/": () => json(settings()) });
    const app = await appAt("/c/1/settings");
    const { wrapper } = mountWithProviders(SettingsPanel, { plugins: app.plugins });
    await settle();
    const inputs = wrapper.find("[data-testid=points-table]").findAll("input");
    await inputs[1]!.setValue("25");
    await inputs[1]!.trigger("blur");
    await wrapper.findAll("button").find((button) => button.text() === "Save")!.trigger("click");
    await settle();
    const patch = calls.find((call) => call.method === "PATCH")!;
    expect(patch.body).toMatchObject({ points_table: { quiz: 25 }, kudos_per_day: 3, leaderboard_scope: "company" });
  });

  it("is read only without recognition.manage", async () => {
    stub({ "GET recognition/settings/": () => json(settings()) });
    const app = await appAt("/c/1/settings", ["members.view", "dashboard.access"]);
    const { wrapper } = mountWithProviders(SettingsPanel, { plugins: app.plugins });
    await settle();
    expect(wrapper.findAll("button").some((button) => button.text() === "Save")).toBe(false);
  });
});

describe("thanks", () => {
  const kudos = (): Kudos => ({
    id: 8,
    from: person(3, "Madina Saidova"),
    to: person(4, "Alisher Valiyev"),
    badge: "careful",
    badge_label: "Careful work",
    message: "Muzlatgichni tekshirding",
    task: null,
    at: "2026-11-07T05:00:00Z",
    seen: false,
    mine: false,
  });

  it("lists them and lets an owner hide one", async () => {
    const calls = stub({ "GET recognition/kudos/": () => json([kudos()]), "POST recognition/kudos/8/hide/": () => new Response(null, { status: 204 }) });
    const app = await appAt("/c/1/recognition/kudos");
    const { wrapper } = mountWithProviders(KudosPage, { plugins: app.plugins });
    await settle();
    const feed = wrapper.find("[data-testid=kudos-feed]");
    expect(feed.text()).toContain("Madina Saidova");
    expect(feed.text()).toContain("«Muzlatgichni tekshirding»");
    await feed.find(`button[aria-label="${en["recognition.kudosFeed.hide"]}"]`).trigger("click");
    await settle();
    // What the app's ConfirmHost does when the owner confirms: run onConfirm, then answer.
    expect(confirmQueue.value).toHaveLength(1);
    const entry = confirmQueue.value[0]!;
    expect(entry.request.title).toBe(en["recognition.kudosFeed.hideTitle"]);
    await entry.request.onConfirm?.("");
    settleConfirm(entry.id, { reason: "" }, 0);
    await settle();
    expect(calls.some((call) => call.method === "POST" && call.path === "recognition/kudos/8/hide/")).toBe(true);
  });

  it("offers Say thanks on someone else's profile, not on one's own", async () => {
    const app = await appAt("/c/1/people/4");
    const other = mountWithProviders(SayThanksAction, { plugins: app.plugins, props: { context: { memberId: 4, person: { id: 4, name: "Alisher Valiyev", status: "approved" } } } });
    expect(other.wrapper.find("[data-testid=say-thanks]").exists()).toBe(true);
    const self = mountWithProviders(SayThanksAction, { plugins: app.plugins, props: { context: { memberId: 11, person: { id: 11, name: "Dilnoza Karimova", status: "approved" } } } });
    expect(self.wrapper.find("[data-testid=say-thanks]").exists()).toBe(false);
    const gone = mountWithProviders(SayThanksAction, { plugins: app.plugins, props: { context: { memberId: 9, person: { id: 9, name: "Old", status: "left" } } } });
    expect(gone.wrapper.find("[data-testid=say-thanks]").exists()).toBe(false);
  });
});

describe("learning's person page", () => {
  it("shows their level, points, streak and badges", async () => {
    const profile: Profile = {
      member: person(4, "Alisher Valiyev"),
      points: 310,
      week_points: 45,
      month_points: 120,
      level: { number: 3, name: "Active", starts_at: 250, next_at: 500, next_name: "Knowledgeable" },
      streak: 4,
      best_streak: 9,
      badges: [{ key: "first_lesson", ref: "", name: "First lesson", description: "Watch a video lesson to the end.", icon: "circle-play", tier: "bronze", awarded_at: "2026-11-02T09:00:00Z" }],
      history: [],
      kudos_received: 2,
      kudos_given: 1,
    };
    stub({ "GET recognition/people/4/": () => json(profile) });
    const app = await appAt("/c/1/learning/people/4");
    const { wrapper } = mountWithProviders(PersonPanel, { plugins: app.plugins, props: { context: { companyId: 1, memberId: 4 } } });
    await settle();
    const text = wrapper.find("[data-testid=recognition-person-panel]").text();
    expect(text).toContain("Active");
    expect(text).toContain("310");
    expect(text).toContain("45");
  });
});

describe("the module", () => {
  it("fills learning's and Person 360's extension points while recognition is on", () => {
    const module = modules.find((entry) => entry.id === "recognition")!;
    expect(module.group).toBe("people");
    expect(module.feature).toBe("recognition");
    const owner = company({ features: ["recognition", "learning"] });
    for (const point of ["learning.person.panels", "learning.overview.cards", "people.profile.actions"] as const) {
      expect(extensionsFor(point, owner).some((entry) => entry.moduleId === "recognition"), point).toBe(true);
    }
    expect(extensionsFor("learning.person.panels", company({ features: ["learning"] })).some((entry) => entry.moduleId === "recognition")).toBe(false);
  });
});
