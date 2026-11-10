// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { defineComponent, ref } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { ACTIVITY_POLL_MS, aiApi, aiKeys, useActivityFeed, useDraft, useTurn } from "../api";
import module from "../index";
import { activity, aiDraft } from "./fixtures";

type Call = { method: string; url: string; body: unknown };

function stubFetch(answer: (call: Call) => Response | Promise<Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const body = init?.body instanceof FormData ? Object.fromEntries([...init.body.entries()].map(([key, value]) => [key, value instanceof Blob ? `blob:${value.type}` : value])) : init?.body ? JSON.parse(String(init.body)) : undefined;
      const call = { method: init?.method ?? "GET", url: input, body };
      calls.push(call);
      return answer(call);
    }),
  );
  return calls;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("endpoints", () => {
  it("speak the contract's paths, methods and bodies", async () => {
    const calls = stubFetch(() => json({ results: [], next_before: null }));
    await aiApi.status(1);
    await aiApi.enable(1);
    await aiApi.patchAgent(1, "deadline_watcher", { config: { escalate_after_hours: 3 } });
    await aiApi.runAgent(1, "morning_plan");
    await aiApi.activity(1, { agent: "voice_tasks", limit: 30, before: 120 });
    await aiApi.drafts(1, { status: "ready", source: "", page_size: 20 });
    await aiApi.fromText(1, "Alisher, kassani sanab qo‘y");
    const form = new FormData();
    form.append("audio", new Blob(["x"], { type: "audio/webm" }), "voice.webm");
    form.append("seconds", "14");
    await aiApi.fromAudio(1, form);
    await aiApi.apply(1, 41, { drafts: [] });
    await aiApi.discard(1, 41);
    await aiApi.sendTurn(1, 7, { text: "Who is late?" });
    await aiApi.turn(1, 9);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/owner/companies/1/ai/status/",
      "POST /api/v1/owner/companies/1/ai/settings/enable/",
      "PATCH /api/v1/owner/companies/1/ai/agents/deadline_watcher/",
      "POST /api/v1/owner/companies/1/ai/agents/morning_plan/run/",
      "GET /api/v1/owner/companies/1/ai/activity/?agent=voice_tasks&limit=30&before=120",
      "GET /api/v1/owner/companies/1/ai/task-drafts/?status=ready&page_size=20",
      "POST /api/v1/owner/companies/1/ai/task-drafts/",
      "POST /api/v1/owner/companies/1/ai/task-drafts/",
      "POST /api/v1/owner/companies/1/ai/task-drafts/41/apply/",
      "POST /api/v1/owner/companies/1/ai/task-drafts/41/discard/",
      "POST /api/v1/owner/companies/1/ai/conversations/7/turns/",
      "GET /api/v1/owner/companies/1/ai/turns/9/",
    ]);
    expect(calls[1]!.body).toEqual({ accept_terms: true });
    expect(calls[2]!.body).toEqual({ config: { escalate_after_hours: 3 } });
    expect(calls[6]!.body).toEqual({ text: "Alisher, kassani sanab qo‘y" });
    expect(calls[7]!.body).toEqual({ audio: "blob:audio/webm", seconds: "14" });
    expect(aiKeys.draft(3, 41)).toEqual([3, "ai", "draft", { id: 41 }]);
  });

  it("reads list endpoints given as pages or arrays", async () => {
    stubFetch(() => json({ count: 1, next: null, previous: null, results: [{ id: 7, title: "Kim kechikdi?", created_at: "2026-11-02T10:00:00+05:00" }] }));
    expect((await aiApi.conversations(1)).map((c) => c.id)).toEqual([7]);
    stubFetch(() => json([{ key: "voice_tasks" }]));
    expect((await aiApi.agents(1)).map((a) => a.key)).toEqual(["voice_tasks"]);
  });
});

describe("polling", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
  });

  async function mount<T>(setup: () => T): Promise<T> {
    const app = await testApp("/c/1/ai");
    let exposed: T | undefined;
    const Probe = defineComponent({
      setup() {
        exposed = setup();
        return () => null;
      },
    });
    mountWithProviders(Probe, { plugins: app.plugins });
    await flushPromises();
    return exposed!;
  }

  it("polls a draft every second while the AI works and stops at the answer", async () => {
    const answers = ["transcribing", "thinking", "ready"];
    const calls = stubFetch(() => json(aiDraft({ status: (answers.shift() ?? "ready") as never })));
    const draft = await mount(() => useDraft(ref(41)));
    expect(draft.data.value?.status).toBe("transcribing");
    await vi.advanceTimersByTimeAsync(1000);
    expect(draft.data.value?.status).toBe("thinking");
    await vi.advanceTimersByTimeAsync(1000);
    expect(draft.data.value?.status).toBe("ready");
    const made = calls.length;
    await vi.advanceTimersByTimeAsync(5000);
    expect(calls.length).toBe(made);
    expect(draft.gaveUp.value).toBe(false);
  });

  it("gives up after 90 s without an answer, and polls again on retry", async () => {
    const calls = stubFetch(() => json(aiDraft({ status: "thinking" })));
    const draft = await mount(() => useDraft(ref(41)));
    await vi.advanceTimersByTimeAsync(91_000);
    expect(draft.gaveUp.value).toBe(true);
    const made = calls.length;
    expect(made).toBeGreaterThan(80);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(calls.length).toBe(made);
    draft.retry();
    await vi.advanceTimersByTimeAsync(2000);
    expect(draft.gaveUp.value).toBe(false);
    expect(calls.length).toBeGreaterThan(made);
  });

  it("polls a chat turn until it's done", async () => {
    const answers = [
      { status: "running", steps: [], text: "" },
      { status: "running", steps: [{ label: "Vazifalarni ko‘rib chiqyapman…", status: "done", ms: 420 }], text: "Bugun " },
      { status: "done", steps: [{ label: "Vazifalarni ko‘rib chiqyapman…", status: "done", ms: 420 }], text: "Bugun 2 ta vazifa kechikdi.", message_id: 5 },
    ];
    const calls = stubFetch(() => json({ id: 9, error_code: "", message_id: null, ...(answers.shift() ?? answers.at(-1)) }));
    const turn = await mount(() => useTurn(ref(9)));
    expect(turn.data.value?.status).toBe("running");
    await vi.advanceTimersByTimeAsync(1000);
    expect(turn.data.value?.steps).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(turn.data.value?.status).toBe("done");
    const made = calls.length;
    await vi.advanceTimersByTimeAsync(4000);
    expect(calls.length).toBe(made);
  });

  it("merges the activity's polled head with the older pages it loaded", async () => {
    let head = [activity(30), activity(29)];
    const calls = stubFetch((call) => {
      if (call.url.includes("before=29")) return json({ results: [activity(28), activity(27)], next_before: null });
      return json({ results: head, next_before: 29 });
    });
    const feed = await mount(() => useActivityFeed(ref<string | null>(null)));
    expect(feed.items.value.map((item) => item.id)).toEqual([30, 29]);
    expect(feed.hasOlder.value).toBe(true);
    await feed.loadOlder();
    expect(feed.items.value.map((item) => item.id)).toEqual([30, 29, 28, 27]);
    expect(feed.hasOlder.value).toBe(false);
    head = [activity(31), activity(30)];
    await vi.advanceTimersByTimeAsync(ACTIVITY_POLL_MS);
    expect(feed.items.value.map((item) => item.id)).toEqual([31, 30, 29, 28, 27]);
    expect(feed.fresh.value).toEqual([31]);
    expect(calls.filter((call) => call.url.includes("/ai/activity/")).length).toBe(3);
    // The polled head never rewinds the cursor of pages already loaded.
    expect(feed.hasOlder.value).toBe(false);
  });
});

describe("registration", () => {
  it("sits right after Tasks, opens voice notes from the bot and fills the New task dialog", () => {
    expect(module).toMatchObject({ id: "ai", group: "work", order: 15 });
    expect(module.feature).toBeUndefined();
    expect(module.nav?.map((item) => item.to)).toEqual(["ai", "ai/advisor", "ai/activity", "ai/voice", "ai/ask"]);
    expect(module.nav?.find((item) => item.key === "advisor")?.perm).toBe("reports.view");
    expect(module.deepLinks?.draft?.("41")).toBe("ai/voice?draft=41");
    expect(module.deepLinks?.draft?.("x")).toBe("ai/voice");
    expect(module.deepLinks?.advisor?.("41")).toBe("ai/advisor?review=41");
    expect(module.deepLinks?.advisor?.("x")).toBe("ai/advisor");
    expect(Object.keys(module.extensions ?? {})).toEqual(["shell.panel", "tasks.create.tools"]);
    expect(module.widgets?.map((widget) => widget.id)).toEqual(["ai.kpi.today"]);
    expect(module.settings?.[0]).toMatchObject({ id: "ai", perm: "ai.configure" });
    expect(module.settings?.[1]).toMatchObject({ id: "ai.briefings", perm: "company.settings" });
    expect(module.invalidates).toEqual(["ai", "briefings"]);
  });
});
