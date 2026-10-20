// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { reminderKeys, remindersApi } from "../api";
import PolicyList from "../components/PolicyList.vue";
import en from "../i18n/en.json";
import { emptyDraft, summary, toDraft, toInput } from "../draft";
import module from "../index";
import { clock, parseClock, planReminders, quietBands, quietUntil, trackScale, type PolicyShape } from "../schedule";
import type { Policy } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const HOUR = 60;
const DAY = 24 * HOUR;
const at = (h: number, m = 0, day = 0) => day * DAY + h * HOUR + m;

const policy = (overrides: Partial<PolicyShape> = {}): PolicyShape => ({
  heads_up_minutes: 15,
  repeat_every_minutes: 20,
  max_reminders: 12,
  escalate_after: 3,
  quiet_from: "22:00",
  quiet_until: "08:00",
  quiet_days: [],
  ...overrides,
});

describe("planReminders", () => {
  it("gives a heads-up, reminds from the deadline, tells the manager once and stops at the cap", () => {
    const plan = planReminders(policy(), at(18), 0);
    expect(plan.events[0]).toMatchObject({ kind: "heads_up", step: 0, at: at(17, 45), shifted: false });
    const reminders = plan.events.filter((e) => e.kind === "reminder");
    expect(reminders).toHaveLength(12);
    expect(reminders.map((e) => clock(e.at)).slice(0, 4)).toEqual(["18:00", "18:20", "18:40", "19:00"]);
    expect(reminders.filter((e) => e.escalate).map((e) => e.step)).toEqual([3]);
    expect(reminders.at(-1)).toMatchObject({ step: 12, at: at(21, 40), last: true });
    expect(reminders.slice(0, -1).every((e) => !e.last)).toBe(true);
    expect(plan.endless).toBe(false);
  });

  it("pushes a reminder that falls in quiet hours to when they end, the next morning", () => {
    const plan = planReminders(policy({ heads_up_minutes: 0, max_reminders: 3 }), at(21, 30), 0);
    expect(plan.events.map((e) => [e.step, e.at, e.shifted])).toEqual([
      [1, at(21, 30), false],
      [2, at(21, 50), false],
      [3, at(8, 0, 1), true],
    ]);
  });

  it("moves a heads-up out of the night but keeps it before the deadline", () => {
    const plan = planReminders(policy({ heads_up_minutes: 60, max_reminders: 1 }), at(8, 30), 0);
    expect(plan.events[0]).toMatchObject({ kind: "heads_up", at: at(8, 0), shifted: true });
    expect(plan.events[1]).toMatchObject({ kind: "reminder", step: 1, at: at(8, 30), last: true });
  });

  it("skips quiet days entirely", () => {
    // Deadline Saturday 18:00, Sunday is quiet, a reminder every 6 hours.
    const plan = planReminders(policy({ heads_up_minutes: 0, repeat_every_minutes: 360, max_reminders: 3, quiet_from: null, quiet_until: null, quiet_days: [6] }), at(18), 5);
    expect(plan.events.map((e) => [e.at, e.shifted])).toEqual([
      [at(18), false],
      [at(0, 0, 2), true],
      [at(6, 0, 2), false],
    ]);
  });

  it("shows only the first reminders of a policy that never stops", () => {
    const plan = planReminders(policy({ max_reminders: 0, quiet_from: null, quiet_until: null }), at(18), 0, 16);
    expect(plan.endless).toBe(true);
    expect(plan.events.filter((e) => e.kind === "reminder")).toHaveLength(16);
    expect(plan.events.some((e) => e.last)).toBe(false);
  });

  it("never tells the manager when escalation is off", () => {
    const plan = planReminders(policy({ escalate_after: 0 }), at(18), 0);
    expect(plan.events.some((e) => e.escalate)).toBe(false);
  });
});

describe("clock helpers and the track", () => {
  it("reads and writes wall-clock times", () => {
    expect(parseClock("22:00:00")).toBe(at(22));
    expect(parseClock("07:30")).toBe(at(7, 30));
    expect(parseClock(null)).toBeNull();
    expect(clock(at(1, 0, 1))).toBe("01:00");
    expect(clock(-30)).toBe("23:30");
  });

  it("knows when quiet hours end, across midnight", () => {
    const shape = policy();
    expect(quietUntil(at(23), shape, 0)).toBe(at(8, 0, 1));
    expect(quietUntil(at(3), shape, 0)).toBe(at(8));
    expect(quietUntil(at(12), shape, 0)).toBeNull();
  });

  it("bands the night and squeezes it on the track, keeping order", () => {
    const shape = policy();
    const bands = quietBands(shape, at(20), at(10, 0, 1), 0);
    expect(bands).toEqual([{ from: at(22), to: at(8, 0, 1), day: false }]);
    const scale = trackScale(at(20), at(10, 0, 1), bands);
    const points = [at(20), at(21), at(22), at(3, 0, 1), at(8, 0, 1), at(10, 0, 1)].map(scale);
    expect(points[0]).toBe(0);
    expect(points.at(-1)).toBeCloseTo(1);
    for (let i = 1; i < points.length; i += 1) expect(points[i]!).toBeGreaterThanOrEqual(points[i - 1]!);
    // Ten hours of night take a small share of the track.
    expect(points[4]! - points[2]!).toBeLessThan(0.1);
  });
});

describe("drafts", () => {
  const saved: Policy = {
    id: 8,
    name: "Till and opening (strict)",
    is_default: false,
    heads_up_minutes: 15,
    repeat_every_minutes: 10,
    max_reminders: 8,
    escalate_after: 2,
    quiet_from: null,
    quiet_until: null,
    quiet_days: [6],
    snooze_minutes: 15,
    max_snoozes: 0,
    replace_previous: true,
    texts: [{ from_step: 3, text: "{name}, the till is still not counted" }],
    usage: { routines: 2, open_tasks: 1 },
    updated_at: "2026-10-21T08:00:00Z",
  };

  it("turns a policy into a form and back without losing anything", () => {
    const draft = toDraft(saved);
    expect(draft.quiet).toBe(false);
    expect(draft.quiet_from).toBe("22:00");
    const input = toInput({ ...draft, name: "  Till and opening (strict) ", texts: [...draft.texts, { from_step: 5, text: "   " }] });
    expect(input).toEqual({
      name: "Till and opening (strict)",
      heads_up_minutes: 15,
      repeat_every_minutes: 10,
      max_reminders: 8,
      escalate_after: 2,
      quiet_from: null,
      quiet_until: null,
      quiet_days: [6],
      snooze_minutes: 15,
      max_snoozes: 0,
      replace_previous: true,
      texts: [{ from_step: 3, text: "{name}, the till is still not counted" }],
    });
    expect(toDraft({ ...saved, quiet_from: "23:00:00", quiet_until: "07:00:00" })).toMatchObject({ quiet: true, quiet_from: "23:00", quiet_until: "07:00" });
    expect(emptyDraft("New")).toMatchObject({ name: "New", quiet: true, max_reminders: 12 });
  });

  it("sums a policy up in one line", () => {
    const t = (key: string, params?: Record<string, unknown>) => `${key.split(".").pop()}:${params?.n ?? ""}`;
    expect(summary(saved, t)).toBe("headsUp:15 · every:10 · escalate:2 · stops:8");
    expect(summary({ ...saved, heads_up_minutes: 0, escalate_after: 0, max_reminders: 0 }, t)).toBe("every:10 · untilDone:");
  });
});

describe("api", () => {
  it("calls the reminders owner endpoints", async () => {
    const calls = stub({
      "GET reminder-policies/": () => json([]),
      "POST reminder-policies/": () => json({ id: 9 }, 201),
      "PATCH reminder-policies/9/": () => json({ id: 9 }),
      "POST reminder-policies/9/make-default/": () => json({ id: 9 }),
      "DELETE reminder-policies/9/": () => new Response(null, { status: 204 }),
      "GET reminder-log/": () => json({ count: 0, next: null, previous: null, results: [] }),
      "GET blocked-bot/": () => json([]),
    });
    await remindersApi.policies(1);
    await remindersApi.create(1, { name: "Gentle", repeat_every_minutes: 60 });
    await remindersApi.update(1, 9, { max_reminders: 4 });
    await remindersApi.makeDefault(1, 9);
    await remindersApi.remove(1, 9);
    await remindersApi.log(1, { kind: ["escalation"], delivered: "false", page: 1 });
    await remindersApi.blocked(1);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/owner/companies/1/reminder-policies/",
      "POST /api/v1/owner/companies/1/reminder-policies/",
      "PATCH /api/v1/owner/companies/1/reminder-policies/9/",
      "POST /api/v1/owner/companies/1/reminder-policies/9/make-default/",
      "DELETE /api/v1/owner/companies/1/reminder-policies/9/",
      "GET /api/v1/owner/companies/1/reminder-log/?kind=escalation&delivered=false&page=1",
      "GET /api/v1/owner/companies/1/blocked-bot/",
    ]);
    expect(calls[2]!.body).toEqual({ max_reminders: 4 });
  });

  it("registers in Work behind reminders.configure with the defaults panel", () => {
    expect(module).toMatchObject({ id: "reminders", group: "work", order: 40, perm: "reminders.configure" });
    expect(module.settings?.map((panel) => panel.id)).toEqual(["reminders.defaults"]);
    expect(reminderKeys.log(1, { page: 1 })).toEqual([1, "reminders", "log", { page: 1 }]);
  });

  it("offers a New reminder policy command that opens the editor", () => {
    const go = vi.fn();
    const commands = module.commands!({ t: (key: string) => key, go, can: () => true } as never);
    commands.find((command) => command.id === "reminders.new")!.run();
    expect(go).toHaveBeenCalledWith("reminders?tab=policies&new=1");
  });
});

describe("PolicyList", () => {
  it("opens a new policy from ?new=1 and drops the flag from the URL", async () => {
    mergeModuleMessages("reminders", { en, ru: en, uz: en });
    stub({ "GET reminder-policies/": () => json([]) });
    const app = await testApp("/c/1/reminders?new=1");
    const { wrapper } = mountWithProviders(PolicyList, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.body.querySelector("[role=dialog]")?.textContent).toContain(en["reminders.editor.newTitle"]);
    expect(app.router.currentRoute.value.query.new).toBeUndefined();
    wrapper.unmount();
    document.body.innerHTML = "";
  });
});
