/**
 * Tasks from the AI in the mini app: what shows when (ai/status), the recorder (with a fake
 * MediaRecorder and microphone), the wait (poll every second, give up at 90 s), the review's
 * edits and one-tap fixes, the apply payload, the deep link from the bot, and the fallbacks.
 */
import { act, cleanup, fireEvent, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import type { Membership } from "../../api/types";
import { resolveScreen } from "../../state/deeplink";
import { membership, navigationState, person, renderApp } from "../../test/harness";
import { features } from "../registry";
import { FeatureSlot } from "../FeatureSlot";
import type { AIDraft, AIStatus, DraftItem } from "./api";

const server = vi.hoisted(() => ({
  calls: [] as { path: string; method: string; json: unknown; form: FormData | undefined }[],
  handler: (() => undefined) as (path: string, method: string, json: unknown) => unknown,
}));

vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  const api = vi.fn(async (path: string, options: { method?: string; json?: unknown; form?: FormData } = {}) => {
    const method = options.method ?? (options.json !== undefined || options.form ? "POST" : "GET");
    server.calls.push({ path, method, json: options.json, form: options.form });
    const result = server.handler(path, method, options.json);
    if (result instanceof Error) throw result;
    return result;
  });
  return {
    ...real,
    api,
    apiForm: (path: string, fields: Parameters<typeof real.toFormData>[0]) => api(path, { method: "POST", form: real.toFormData(fields) }),
  };
});

const telegram = vi.hoisted(() => ({ links: [] as string[] }));
vi.mock("../../telegram", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../telegram")>();
  return {
    ...real,
    openTelegramLink: (url: string) => {
      telegram.links.push(url);
      return true;
    },
  };
});

const api = await import("./api");
const drafts = await import("./drafts");
const rec = await import("./recorder");
const { DictateCard, PlusTitleTools } = await import("./Entry");

const TZ = "Asia/Tashkent";
const NOW = new Date("2026-11-02T09:00:00+05:00");

const STATUS: AIStatus = { voice: true, smart_text: true, engine: "rules", max_seconds: 120, auto_create: false, bot_username: "daily_taskmanagment_bot" };

function item(fields: Partial<DraftItem> = {}): DraftItem {
  return {
    title: "Muzlatgich haroratini tekshirish",
    description: "",
    assignee: { id: 15, name: "Alisher Valiyev", position: "Farmatsevt" },
    assignee_guess: "",
    due_at: "2026-11-03T10:00:00+05:00",
    due_text: "Ertaga, 10:00",
    priority: "normal",
    checklist: [],
    proof: "photo",
    problems: [],
    ...fields,
  };
}

function draft(fields: Partial<AIDraft> = {}): AIDraft {
  return {
    id: 41,
    status: "ready",
    source: "miniapp",
    author: { id: 12, name: "Bekzod Mirzayev" },
    created_at: "2026-11-02T09:00:00+05:00",
    audio: { seconds: 14, url: "/media/x.webm" },
    transcript: "Alisher, ertaga soat o‘ngacha muzlatgich haroratini tekshirib, rasmini yubor.",
    language: "uz",
    engine: "rules",
    drafts: [item()],
    questions: [],
    created_tasks: [],
    error_code: "",
    error: "",
    ...fields,
  };
}

/** A head who gives work (tasks.assign). */
function giver(): Membership {
  return membership({ id: 12, first_name: "Bekzod", last_name: "Mirzayev", permissions: ["tasks.assign"] } as Partial<Membership>);
}

const PEOPLE = [
  { id: 15, name: "Alisher Valiyev", position: "Farmatsevt" },
  { id: 16, name: "Sardor Rahimov", position: "Provizor" },
  { id: 17, name: "Sardor Qodirov", position: "Kassir" },
];

beforeEach(() => {
  server.calls = [];
  telegram.links = [];
  server.handler = (path) => {
    if (path.endsWith("/ai/status/")) return STATUS;
    if (path.endsWith("/members/")) return PEOPLE;
    if (path.endsWith("/summary/")) return undefined;
    return undefined;
  };
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

// — what shows when —

describe("status → ways in", () => {
  it("shows the mic for voice and the sparkle for smart text", () => {
    expect(api.entryOf(undefined)).toEqual({ voice: false, text: false, any: false });
    expect(api.entryOf(STATUS)).toEqual({ voice: true, text: true, any: true });
    expect(api.entryOf({ ...STATUS, voice: false })).toEqual({ voice: false, text: true, any: true });
  });

  it("puts the Home card up for whoever gives work, while voice works", async () => {
    renderApp(<DictateCard member={{ ...giver(), timeZone: TZ, companyId: 1 }} summary={undefined} />, { me: person([giver()]) });
    expect(await screen.findByText("Give tasks by voice")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Give tasks by voice/ }));
    expect(navigationState().sheet).toEqual({ kind: "feature", feature: "ai", sheet: "draft", params: { mode: "voice" } });
  });

  it("fetches the sheet's code while idle once a way in shows, so the first tap shows no placeholder", async () => {
    const { DraftSheetScreen } = await import("./sheet");
    const preload = vi.spyOn(DraftSheetScreen, "preload");
    try {
      const worker = membership();
      const first = renderApp(<DictateCard member={{ ...worker, timeZone: TZ, companyId: 1 }} summary={undefined} />, { me: person([worker]) });
      await waitFor(() => expect(server.calls.some((call) => call.path.endsWith("/ai/status/"))).toBe(true));
      await new Promise((resolve) => setTimeout(resolve, 700));
      // No Home card for someone who doesn't give work: nothing fetched for it.
      expect(preload).not.toHaveBeenCalled();
      first.unmount();
      renderApp(<DictateCard member={{ ...giver(), timeZone: TZ, companyId: 1 }} summary={undefined} />, { me: person([giver()]) });
      expect(await screen.findByText("Give tasks by voice")).toBeTruthy();
      await waitFor(() => expect(preload).toHaveBeenCalled(), { timeout: 2000 });
    } finally {
      preload.mockRestore();
    }
  });

  it("offers typing on Home when only smart text works", async () => {
    server.handler = (path) => (path.endsWith("/ai/status/") ? { ...STATUS, voice: false } : undefined);
    renderApp(<DictateCard member={{ ...giver(), timeZone: TZ, companyId: 1 }} summary={undefined} />, { me: person([giver()]) });
    expect(await screen.findByText("Give tasks in one message")).toBeTruthy();
  });

  it("keeps the Home card away from people who don't give work, and when AI is off", async () => {
    const worker = membership();
    const first = renderApp(<DictateCard member={{ ...worker, timeZone: TZ, companyId: 1 }} summary={undefined} />, { me: person([worker]) });
    await waitFor(() => expect(server.calls.some((call) => call.path.endsWith("/ai/status/"))).toBe(true));
    expect(screen.queryByText("Give tasks by voice")).toBeNull();
    first.unmount();
    server.handler = (path) => (path.endsWith("/ai/status/") ? { ...STATUS, voice: false, smart_text: false } : undefined);
    renderApp(<DictateCard member={{ ...giver(), timeZone: TZ, companyId: 1 }} summary={undefined} />, { me: person([giver()]) });
    await waitFor(() => expect(server.calls.filter((call) => call.path.endsWith("/ai/status/")).length).toBe(2));
    expect(screen.queryByText(/Give tasks/)).toBeNull();
  });

  it("hides everything when the server has no AI endpoint", async () => {
    server.handler = (path) => (path.endsWith("/ai/status/") ? new ApiError(404, null) : undefined);
    renderApp(<PlusTitleTools member={{ ...giver(), timeZone: TZ, companyId: 1 }} summary={undefined} text="" />, { me: person([giver()]) });
    await waitFor(() => expect(server.calls.length).toBeGreaterThan(0));
    expect(screen.queryByRole("button", { name: "Dictate tasks" })).toBeNull();
  });

  it("sends what was typed in the (+) title straight to smart add", async () => {
    renderApp(<PlusTitleTools member={{ ...giver(), timeZone: TZ, companyId: 1 }} summary={undefined} text="  Alisher kassani sanasin  " />, { me: person([giver()]) });
    fireEvent.click(await screen.findByRole("button", { name: /Smart add: turn this text into tasks/ }));
    expect(navigationState().sheet).toEqual({ kind: "feature", feature: "ai", sheet: "draft", params: { mode: "text", text: "Alisher kassani sanasin", send: 1 } });
  });

  it("shows Dictate tasks among the (+) quick actions only while voice works", async () => {
    server.handler = (path) => (path.endsWith("/ai/status/") ? { ...STATUS, voice: false } : undefined);
    const { unmount } = renderApp(<FeatureSlot name="plus.actions" />, { me: person([giver()]) });
    await waitFor(() => expect(server.calls.some((call) => call.path.endsWith("/ai/status/"))).toBe(true));
    expect(screen.queryByText("Dictate tasks")).toBeNull();
    unmount();
    server.handler = (path) => (path.endsWith("/ai/status/") ? STATUS : undefined);
    renderApp(<FeatureSlot name="plus.actions" />, { me: person([giver()]) });
    fireEvent.click(await screen.findByText("Dictate tasks"));
    expect(navigationState().sheet).toEqual({ kind: "feature", feature: "ai", sheet: "draft", params: { mode: "voice" } });
  });

  it("puts the mic beside the (+) sheet's title, and it opens the recorder", async () => {
    renderApp(null, { me: person([giver()]), init: { sheet: { kind: "add" } } });
    const mics = await screen.findAllByRole("button", { name: "Dictate tasks" });
    // The quick action and the title row's mic.
    expect(mics).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Smart add: several tasks in one text" })).toBeTruthy();
    fireEvent.click(mics[1]!);
    expect(navigationState().sheet).toEqual({ kind: "feature", feature: "ai", sheet: "draft", params: { mode: "voice" } });
  });

  it("asks before the (+) sheet's mic or a quick action throws away a task being written", async () => {
    const ask = vi.spyOn(window, "confirm").mockReturnValue(false);
    try {
      renderApp(null, { me: person([giver()]), init: { sheet: { kind: "add" } } });
      const mics = await screen.findAllByRole("button", { name: "Dictate tasks" });
      fireEvent.change(screen.getByRole("textbox", { name: "What needs doing?" }), { target: { value: "Order insulin" } });
      // The title row's mic, answered Cancel: the sheet and the words stay.
      fireEvent.click(mics[1]!);
      await waitFor(() => expect(ask).toHaveBeenCalledWith("Close it? What you entered won't be saved."));
      expect(navigationState().sheet).toEqual({ kind: "add" });
      expect(screen.getByRole("textbox", { name: "What needs doing?" })).toHaveProperty("value", "Order insulin");
      // The quick action, answered OK: the recorder takes the sheet's place.
      ask.mockReturnValue(true);
      fireEvent.click(mics[0]!);
      await waitFor(() => expect(navigationState().sheet).toEqual({ kind: "feature", feature: "ai", sheet: "draft", params: { mode: "voice" } }));
      expect(ask).toHaveBeenCalledTimes(2);
    } finally {
      ask.mockRestore();
    }
  });

  it("answers the bot's Edit in the app link with the review sheet", () => {
    expect(resolveScreen({ name: "drafts", arg: "41" }, features)).toEqual({
      tab: "home",
      sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { id: 41 } },
    });
  });
});

// — the wait —

describe("polling", () => {
  it("asks every second while the draft works and stops when it's done", () => {
    const since = 1_000_000;
    expect(api.pollInterval(undefined, since, since)).toBe(1000);
    expect(api.pollInterval({ status: "transcribing" }, since, since + 10_000)).toBe(1000);
    expect(api.pollInterval({ status: "ready" }, since, since + 1000)).toBe(false);
    expect(api.pollInterval({ status: "failed" }, since, since + 1000)).toBe(false);
  });

  it("gives up after 90 seconds, and only on a draft still at work", () => {
    const since = 1_000_000;
    expect(api.pollInterval({ status: "thinking" }, since, since + 89_999)).toBe(1000);
    expect(api.pollInterval({ status: "thinking" }, since, since + 90_000)).toBe(false);
    expect(api.gaveUp({ status: "thinking" }, since, since + 90_000)).toBe(true);
    expect(api.gaveUp({ status: "ready" }, since, since + 900_000)).toBe(false);
  });

  it("says Listening until the words are written down, then Thinking", () => {
    expect(api.workingPhase({ status: "queued", audio: { seconds: 3, url: "" } })).toBe("listening");
    expect(api.workingPhase({ status: "transcribing", audio: { seconds: 3, url: "" } })).toBe("listening");
    expect(api.workingPhase({ status: "thinking", audio: { seconds: 3, url: "" } })).toBe("thinking");
    expect(api.workingPhase({ status: "queued", audio: null })).toBe("thinking");
    expect(api.workingPhase({ status: "ready", audio: null })).toBeNull();
  });

  it("waits, then shows the review when the draft is ready", async () => {
    let status: AIDraft["status"] = "thinking";
    server.handler = (path) => {
      if (path.endsWith("/ai/status/")) return STATUS;
      if (path.endsWith("/members/")) return PEOPLE;
      if (path.endsWith("/task-drafts/41/")) return draft({ status, drafts: status === "ready" ? [item()] : [] });
      return undefined;
    };
    renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { id: 41 } } } });
    expect(await screen.findByText("Thinking…")).toBeTruthy();
    status = "ready";
    expect(await screen.findByDisplayValue("Muzlatgich haroratini tekshirish", {}, { timeout: 3000 })).toBeTruthy();
    expect(screen.getAllByText("1 task").length).toBeGreaterThan(0);
  });

  it("offers to keep waiting after 90 seconds, and asks again when told to", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    server.handler = (path) => {
      if (path.endsWith("/ai/status/")) return STATUS;
      if (path.endsWith("/task-drafts/41/")) return draft({ status: "thinking", drafts: [] });
      return undefined;
    };
    renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { id: 41 } } } });
    expect(await screen.findByText("Thinking…")).toBeTruthy();
    vi.setSystemTime(new Date(NOW.getTime() + 91_000));
    expect(await screen.findByText("This is taking longer than usual", {}, { timeout: 3000 })).toBeTruthy();
    const before = server.calls.filter((call) => call.path.endsWith("/task-drafts/41/")).length;
    fireEvent.click(screen.getByRole("button", { name: "Keep waiting" }));
    expect(await screen.findByText("Thinking…")).toBeTruthy();
    await waitFor(() => expect(server.calls.filter((call) => call.path.endsWith("/task-drafts/41/")).length).toBeGreaterThan(before));
  });
});

// — the review —

describe("review edits → apply payload", () => {
  const now = NOW;

  it("keeps the cards as heard when nothing changed", () => {
    const cards = drafts.editableFrom(draft(), now, TZ);
    expect(drafts.applyPayload(cards, now, TZ)).toEqual([
      { title: "Muzlatgich haroratini tekshirish", description: "", assignee_id: 15, due_at: "2026-11-03T05:00:00.000Z", priority: "normal", checklist: [], proof: "photo" },
    ]);
  });

  it("sends what the person changed and leaves out removed cards", () => {
    const [first, second] = drafts.editableFrom(draft({ drafts: [item(), item({ title: "Kassani sanash", assignee: null, due_at: null, proof: "none" })] }), now, TZ);
    const edited = [
      drafts.setWhen(drafts.pickAssignee({ ...first!, title: "  Muzlatgichni tekshirish ", priority: "urgent", checklist: ["Harorat", " ", "Rasm"] }, 16), { when: "today", date: "2026-11-04", time: "18:00" }),
      { ...second!, removed: true },
    ];
    expect(drafts.applyPayload(edited, now, TZ)).toEqual([
      { title: "Muzlatgichni tekshirish", description: "", assignee_id: 16, due_at: "2026-11-02T13:00:00.000Z", priority: "urgent", checklist: ["Harorat", "Rasm"], proof: "photo" },
    ]);
  });

  it("keeps a passed time as heard, so the card can say it has passed", () => {
    const [card] = drafts.editableFrom(draft({ drafts: [item({ due_at: "2026-11-02T08:00:00+05:00", problems: ["past_due"] })] }), now, TZ);
    expect(drafts.problemsOf(card!, now, TZ)).toEqual(["past_due"]);
    expect(drafts.cardReady(card!, now, TZ)).toBe(false);
    const fixed = drafts.sameTimeTomorrow(card!, now, TZ);
    expect(drafts.problemsOf(fixed, now, TZ)).toEqual([]);
    expect(drafts.dueOf(fixed, now, TZ)?.toISOString()).toBe("2026-11-03T03:00:00.000Z");
  });
});

describe("problems → fixes", () => {
  const now = NOW;
  const heard = (fields: Partial<DraftItem>) => drafts.editableFrom(draft({ drafts: [item(fields)] }), now, TZ)[0]!;

  it("settles who it's for with Make it mine, or by picking someone", () => {
    const card = heard({ assignee: null, assignee_guess: "Sardor", problems: ["ambiguous_assignee"] });
    expect(drafts.problemsOf(card, now, TZ)).toEqual(["ambiguous_assignee"]);
    expect(drafts.firstUnready([card], now, TZ)).toBe(card.key);
    const mine = drafts.makeMine(card);
    expect(mine.assigneeId).toBeNull();
    expect(drafts.problemsOf(mine, now, TZ)).toEqual([]);
    expect(drafts.problemsOf(drafts.pickAssignee(card, 17), now, TZ)).toEqual([]);
    expect(drafts.applyPayload([drafts.pickAssignee(card, 17)], now, TZ)[0]!.assignee_id).toBe(17);
  });

  it("lets a missing deadline through, and fixes it with one tap when wanted", () => {
    const card = heard({ due_at: null, problems: ["no_due"] });
    expect(drafts.problemsOf(card, now, TZ)).toEqual(["no_due"]);
    expect(drafts.isBlocking("no_due")).toBe(false);
    expect(drafts.cardReady(card, now, TZ)).toBe(true);
    const tomorrow = drafts.quickDue(card, "tomorrow", "09:00");
    expect(drafts.problemsOf(tomorrow, now, TZ)).toEqual([]);
    expect(drafts.dueOf(tomorrow, now, TZ)?.toISOString()).toBe("2026-11-03T04:00:00.000Z");
    expect(drafts.problemsOf(drafts.acceptProblem(card, "no_due"), now, TZ)).toEqual([]);
  });

  it("blocks work for someone the author may not give it to until it changes", () => {
    const card = heard({ problems: ["not_allowed"] });
    expect(drafts.cardReady(card, now, TZ)).toBe(false);
    expect(drafts.cardReady(drafts.makeMine(card), now, TZ)).toBe(true);
  });

  it("needs a title", () => {
    const card = { ...heard({}), title: "   " };
    expect(drafts.cardReady(card, now, TZ)).toBe(false);
  });

  it("fixes a problem in the sheet with one tap and creates the tasks", async () => {
    let applied: unknown = null;
    server.handler = (path, method, json) => {
      if (path.endsWith("/ai/status/")) return STATUS;
      if (path.endsWith("/members/")) return PEOPLE;
      if (path.endsWith("/task-drafts/41/")) {
        return draft({ drafts: [item(), item({ title: "Kassani sanash", assignee: null, assignee_guess: "Sardor", due_at: null, proof: "none", problems: ["ambiguous_assignee", "no_due"] })] });
      }
      if (path.endsWith("/task-drafts/41/apply/") && method === "POST") {
        applied = json;
        return {
          draft: draft({ status: "applied", created_tasks: [{ id: 501, title: "Muzlatgich haroratini tekshirish", assignee_name: "Alisher Valiyev" }, { id: 502, title: "Kassani sanash", assignee_name: "Bekzod Mirzayev" }] }),
          created: [501, 502],
          failed: [],
        };
      }
      return undefined;
    };
    renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { id: 41 } } } });
    expect(await screen.findByText("Several people are called “Sardor”")).toBeTruthy();
    // Create with the problem left: nothing is sent, the card is marked.
    fireEvent.click(screen.getByRole("button", { name: "Create 2 tasks" }));
    expect(applied).toBeNull();
    expect(await screen.findByText("Fix the marked task first")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Make it mine" }));
    expect(screen.queryByText("Several people are called “Sardor”")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Create 2 tasks" }));
    expect(await screen.findByText("2 tasks created")).toBeTruthy();
    expect(applied).toEqual({
      drafts: [
        { title: "Muzlatgich haroratini tekshirish", description: "", assignee_id: 15, due_at: "2026-11-03T05:00:00.000Z", priority: "normal", checklist: [], proof: "photo" },
        { title: "Kassani sanash", description: "", assignee_id: null, due_at: null, priority: "normal", checklist: [], proof: "none" },
      ],
    });
    // A created task opens from the list.
    fireEvent.click(screen.getByRole("button", { name: /Kassani sanash/ }));
    expect(navigationState().stack).toEqual([{ feature: "core", page: "task", params: { id: 502 } }]);
  });

  it("adds checklist steps to a card the AI heard none for", async () => {
    let applied: { drafts: { checklist: string[] }[] } | null = null;
    server.handler = (path, method, json) => {
      if (path.endsWith("/ai/status/")) return STATUS;
      if (path.endsWith("/members/")) return PEOPLE;
      if (path.endsWith("/task-drafts/41/")) return draft();
      if (path.endsWith("/task-drafts/41/apply/") && method === "POST") {
        applied = json as typeof applied;
        return { draft: draft({ status: "applied", created_tasks: [{ id: 501, title: "x", assignee_name: "Alisher Valiyev" }] }), created: [501], failed: [] };
      }
      return undefined;
    };
    renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { id: 41 } } } });
    fireEvent.click(await screen.findByRole("button", { name: "Add a step" }));
    fireEvent.change(screen.getByLabelText("Step 1"), { target: { value: "Haroratni yozib olish" } });
    fireEvent.click(screen.getByRole("button", { name: "Create 1 task" }));
    await screen.findByText("1 task created");
    expect(applied!.drafts[0]!.checklist).toEqual(["Haroratni yozib olish"]);
  });

  it("keeps the review and says why when the server made none of the tasks", async () => {
    server.handler = (path, method) => {
      if (path.endsWith("/ai/status/")) return STATUS;
      if (path.endsWith("/members/")) return PEOPLE;
      if (path.endsWith("/task-drafts/41/")) return draft();
      if (path.endsWith("/task-drafts/41/apply/") && method === "POST") return { draft: draft(), created: [], failed: [{ index: 0, detail: "Alisher is on leave today." }] };
      return undefined;
    };
    renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { id: 41 } } } });
    fireEvent.click(await screen.findByRole("button", { name: "Create 1 task" }));
    expect(await screen.findByText("Alisher is on leave today.")).toBeTruthy();
    expect(screen.getByDisplayValue("Muzlatgich haroratini tekshirish")).toBeTruthy();
    expect(screen.queryByText(/created/)).toBeNull();
  });

  it("says plainly when nothing could be made out", async () => {
    server.handler = (path) => {
      if (path.endsWith("/ai/status/")) return STATUS;
      if (path.endsWith("/task-drafts/41/")) return draft({ status: "failed", drafts: [], error_code: "nothing_heard", error: "No speech was heard." });
      return undefined;
    };
    renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { id: 41 } } } });
    expect(await screen.findByText("Couldn’t make this out")).toBeTruthy();
    expect(screen.getByText("No speech was heard.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Say it again" })).toBeTruthy();
  });
});

// — smart add —

describe("smart add", () => {
  it("sends the typed text and opens the same review", async () => {
    server.handler = (path, method) => {
      if (path.endsWith("/ai/status/")) return STATUS;
      if (path.endsWith("/members/")) return PEOPLE;
      if (path.endsWith("/task-drafts/") && method === "POST") return draft({ status: "queued", audio: null, drafts: [] });
      if (path.endsWith("/task-drafts/41/")) return draft({ audio: null });
      return undefined;
    };
    renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { mode: "text", text: "Alisher muzlatgichni tekshirsin", send: 1 } } } });
    expect(await screen.findByDisplayValue("Muzlatgich haroratini tekshirish", {}, { timeout: 3000 })).toBeTruthy();
    const posts = server.calls.filter((call) => call.path.endsWith("/task-drafts/") && call.method === "POST");
    expect(posts).toHaveLength(1);
    expect(posts[0]!.json).toEqual({ text: "Alisher muzlatgichni tekshirsin" });
    expect(screen.getByText("You wrote")).toBeTruthy();
  });

  it("says so when auto-create made the tasks without a review", async () => {
    server.handler = (path, method) => {
      if (path.endsWith("/ai/status/")) return { ...STATUS, auto_create: true };
      if (path.endsWith("/task-drafts/") && method === "POST") return draft({ status: "queued", audio: null, drafts: [] });
      if (path.endsWith("/task-drafts/41/")) return draft({ status: "applied", audio: null, created_tasks: [{ id: 501, title: "Muzlatgich haroratini tekshirish", assignee_name: "Alisher Valiyev" }] });
      return undefined;
    };
    const refreshed: string[] = [];
    const first = renderApp(null, {
      me: person([giver()]),
      init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { mode: "text", text: "Alisher muzlatgichni tekshirsin", send: 1 } } },
      seed: (client) => {
        const invalidate = client.invalidateQueries.bind(client);
        client.invalidateQueries = ((filters, options) => {
          refreshed.push(JSON.stringify(filters?.queryKey));
          return invalidate(filters, options);
        }) as typeof client.invalidateQueries;
      },
    });
    expect(await screen.findByText("1 task created", {}, { timeout: 3000 })).toBeTruthy();
    expect(screen.getByText(/Everything was clear, so they were created right away\./)).toBeTruthy();
    // The server made the tasks: Home's numbers, the lists and My team show them without a reload.
    expect(refreshed).toEqual(expect.arrayContaining(['["tasks",1]', '["summary",1]', '["myTeam",1]']));
    first.unmount();
    // The same draft opened from the bot (applied there, maybe by a tap): no claim about how.
    renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { id: 41 } } } });
    expect(await screen.findByText("1 task created")).toBeTruthy();
    expect(screen.queryByText(/created right away/)).toBeNull();
  });

  it("starts Write more from an empty box instead of sending the same words again", async () => {
    let status: AIDraft["status"] = "ready";
    server.handler = (path, method, json) => {
      if (path.endsWith("/ai/status/")) return STATUS;
      if (path.endsWith("/members/")) return PEOPLE;
      if (path.endsWith("/task-drafts/") && method === "POST") return draft({ status: "queued", audio: null, drafts: [] });
      if (path.endsWith("/task-drafts/41/")) return draft({ status, audio: null, created_tasks: status === "applied" ? [{ id: 501, title: "x", assignee_name: "Alisher Valiyev" }] : [] });
      if (path.endsWith("/task-drafts/41/apply/") && method === "POST") {
        status = "applied";
        void json;
        return { draft: draft({ status: "applied", audio: null, created_tasks: [{ id: 501, title: "x", assignee_name: "Alisher Valiyev" }] }), created: [501], failed: [] };
      }
      return undefined;
    };
    renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { mode: "text", text: "Alisher muzlatgichni tekshirsin", send: 1 } } } });
    fireEvent.click(await screen.findByRole("button", { name: "Create 1 task" }, { timeout: 3000 }));
    fireEvent.click(await screen.findByRole("button", { name: "Write more" }));
    const box = (await screen.findByLabelText("Who should do what?")) as HTMLTextAreaElement;
    expect(box.value).toBe("");
    expect(server.calls.filter((call) => call.path.endsWith("/task-drafts/") && call.method === "POST")).toHaveLength(1);
  });

  it("explains a refusal in the box, and AI switched off as its own state", async () => {
    let refusal: ApiError = new ApiError(400, { code: "text_too_long", detail: "Too long." });
    server.handler = (path, method) => {
      if (path.endsWith("/ai/status/")) return STATUS;
      if (path.endsWith("/task-drafts/") && method === "POST") return refusal;
      return undefined;
    };
    const first = renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { mode: "text" } } } });
    fireEvent.change(await screen.findByLabelText("Who should do what?"), { target: { value: "Hammasi" } });
    fireEvent.click(screen.getByRole("button", { name: "Make tasks" }));
    expect(await screen.findByText("The text is too long.")).toBeTruthy();
    first.unmount();
    refusal = new ApiError(403, { code: "ai_off", detail: "Off." });
    renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { mode: "text", text: "Hammasi", send: 1 } } } });
    expect(await screen.findByText("AI is off")).toBeTruthy();
    expect(screen.getByText("Ask your manager to turn it on.")).toBeTruthy();
  });
});

// — the recorder —

type Listener = (event: { data?: Blob }) => void;

class FakeRecorder {
  static supported = new Set(["audio/webm;codecs=opus", "audio/webm"]);
  static last: FakeRecorder | null = null;
  static isTypeSupported(type: string) {
    return FakeRecorder.supported.has(type);
  }
  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  ondataavailable: Listener | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  timeslice = 0;
  constructor(public stream: MediaStream, options?: { mimeType?: string }) {
    this.mimeType = options?.mimeType ?? "audio/webm";
    FakeRecorder.last = this;
  }
  start(timeslice: number) {
    this.timeslice = timeslice;
    this.state = "recording";
  }
  stop() {
    if (this.state === "inactive") throw new Error("inactive");
    this.state = "inactive";
    queueMicrotask(() => {
      this.ondataavailable?.({ data: new Blob(["voice"], { type: this.mimeType }) });
      this.onstop?.();
    });
  }
}

function fakeMicrophone(result: "ok" | "denied" = "ok") {
  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track] } as unknown as MediaStream;
  const getUserMedia = vi.fn(() => (result === "ok" ? Promise.resolve(stream) : Promise.reject(Object.assign(new Error("no"), { name: "NotAllowedError" }))));
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia } });
  const close = vi.fn(() => Promise.resolve());
  class FakeContext {
    state = "running";
    close = close;
    createAnalyser() {
      return { fftSize: 512, getByteTimeDomainData: (frame: Uint8Array) => frame.fill(200), connect: () => undefined };
    }
    createMediaStreamSource() {
      return { connect: () => undefined };
    }
  }
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  vi.stubGlobal("AudioContext", FakeContext);
  return { track, getUserMedia, close };
}

describe("recorder", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    FakeRecorder.last = null;
  });

  it("picks the first type this phone records", () => {
    expect(rec.pickMimeType((type) => type === "audio/mp4")).toBe("audio/mp4");
    expect(rec.pickMimeType((type) => type.startsWith("audio/ogg"))).toBe("audio/ogg;codecs=opus");
    expect(rec.pickMimeType(() => false)).toBeNull();
    expect(rec.fileNameFor("audio/mp4")).toBe("voice.m4a");
    expect(rec.fileNameFor("audio/ogg;codecs=opus")).toBe("voice.ogg");
    expect(rec.fileNameFor("audio/webm;codecs=opus")).toBe("voice.webm");
  });

  it("reads loudness from a frame and the timer as m:ss", () => {
    expect(rec.levelOf(new Uint8Array(64).fill(128))).toBe(0);
    expect(rec.levelOf(new Uint8Array(64).fill(255))).toBe(1);
    expect(rec.formatClock(7.9)).toBe("0:07");
    expect(rec.formatClock(120)).toBe("2:00");
    expect(rec.phaseForError({ name: "NotAllowedError" })).toBe("denied");
    expect(rec.phaseForError({ name: "NotFoundError" })).toBe("unsupported");
    expect(rec.phaseForError(new Error("boom"))).toBe("failed");
  });

  it("records, meters and stops with a voice note; the microphone is let go", async () => {
    const mic = fakeMicrophone();
    const { result } = renderHook(() => rec.useRecorder(120));
    await act(() => result.current.start());
    expect(result.current.phase).toBe("recording");
    expect(FakeRecorder.last?.mimeType).toBe("audio/webm;codecs=opus");
    expect(FakeRecorder.last?.timeslice).toBe(1000);
    await waitFor(() => expect(result.current.levels.at(-1)).toBeGreaterThan(0));
    // A real voice note is longer than a slip of the finger.
    vi.spyOn(performance, "now").mockReturnValue(performance.now() + 5000);
    act(() => result.current.stop());
    await waitFor(() => expect(result.current.phase).toBe("done"));
    expect(result.current.recording?.fileName).toBe("voice.webm");
    expect(result.current.recording?.blob.type).toBe("audio/webm;codecs=opus");
    expect(mic.track.stop).toHaveBeenCalled();
    expect(mic.close).toHaveBeenCalled();
  });

  it("drops a recording that's too short", async () => {
    fakeMicrophone();
    const { result } = renderHook(() => rec.useRecorder(120));
    await act(() => result.current.start());
    act(() => result.current.stop());
    await waitFor(() => expect(result.current.phase).toBe("idle"));
    expect(result.current.tooShort).toBe(true);
    expect(result.current.recording).toBeNull();
  });

  it("stops by itself at the company's limit", async () => {
    fakeMicrophone();
    const { result } = renderHook(() => rec.useRecorder(2));
    const start = performance.now();
    await act(() => result.current.start());
    vi.spyOn(performance, "now").mockReturnValue(start + 2500);
    await waitFor(() => expect(result.current.phase).toBe("done"));
    expect(result.current.autoStopped).toBe(true);
    expect(result.current.recording?.seconds).toBe(2);
  });

  it("cancels without a recording, and lets go when the screen goes away", async () => {
    const mic = fakeMicrophone();
    const { result, unmount } = renderHook(() => rec.useRecorder(120));
    await act(() => result.current.start());
    act(() => result.current.cancel());
    await waitFor(() => expect(result.current.phase).toBe("idle"));
    expect(result.current.recording).toBeNull();
    expect(mic.track.stop).toHaveBeenCalledTimes(1);
    await act(() => result.current.start());
    unmount();
    expect(mic.track.stop).toHaveBeenCalledTimes(2);
    expect(mic.close).toHaveBeenCalledTimes(2);
  });

  it("says denied or unsupported instead of failing", async () => {
    fakeMicrophone("denied");
    const denied = renderHook(() => rec.useRecorder(120));
    await act(() => denied.result.current.start());
    expect(denied.result.current.phase).toBe("denied");
    vi.stubGlobal("MediaRecorder", undefined);
    const none = renderHook(() => rec.useRecorder(120));
    await act(() => none.result.current.start());
    expect(none.result.current.phase).toBe("unsupported");
  });

  it("asks in its own words before Escape or Back throws a recording away", async () => {
    fakeMicrophone();
    const ask = vi.spyOn(window, "confirm").mockReturnValue(false);
    try {
      renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { mode: "voice" } } } });
      expect(await screen.findByText("Listening to you")).toBeTruthy();
      await waitFor(() => expect(screen.getByRole("button", { name: "Done" })).toHaveProperty("disabled", false));
      fireEvent.keyDown(document, { key: "Escape" });
      // Not "What you entered won't be saved": nothing was typed, something was said.
      await waitFor(() => expect(ask).toHaveBeenCalledWith("Stop recording? What you said won’t be kept."));
      expect(screen.getByText("Listening to you")).toBeTruthy();
    } finally {
      ask.mockRestore();
    }
  });

  it("sends the person to the bot when recording isn't possible here", async () => {
    vi.stubGlobal("MediaRecorder", undefined);
    renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { mode: "voice" } } } });
    expect(await screen.findByText("Recording isn’t possible here")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open the bot" }));
    expect(telegram.links).toEqual(["https://t.me/daily_taskmanagment_bot"]);
    fireEvent.click(screen.getByRole("button", { name: "Type it instead" }));
    expect(await screen.findByLabelText("Who should do what?")).toBeTruthy();
  });

  it("sends the same note again after the signal drops, without asking to speak again", async () => {
    fakeMicrophone();
    let online = false;
    server.handler = (path, method) => {
      if (path.endsWith("/ai/status/")) return STATUS;
      if (path.endsWith("/task-drafts/") && method === "POST") return online ? draft({ status: "queued", transcript: "", drafts: [] }) : new TypeError("Failed to fetch");
      if (path.endsWith("/task-drafts/41/")) return draft({ status: "transcribing", transcript: "", drafts: [] });
      return undefined;
    };
    renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { mode: "voice" } } } });
    expect(await screen.findByText("Listening to you")).toBeTruthy();
    vi.spyOn(performance, "now").mockReturnValue(performance.now() + 4000);
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(await screen.findByText("Couldn’t send the recording")).toBeTruthy();
    online = true;
    fireEvent.click(screen.getByRole("button", { name: "Send again" }));
    expect(await screen.findByText("Listening…")).toBeTruthy();
    const posts = server.calls.filter((call) => call.path.endsWith("/task-drafts/") && call.method === "POST");
    expect(posts).toHaveLength(2);
    const [first, again] = posts.map((call) => call.form?.get("audio") as File);
    expect([again!.name, again!.size, again!.type]).toEqual([first!.name, first!.size, first!.type]);
  });

  it("uploads the voice note as multipart with its length and language", async () => {
    fakeMicrophone();
    server.handler = (path, method) => {
      if (path.endsWith("/ai/status/")) return STATUS;
      if (path.endsWith("/task-drafts/") && method === "POST") return draft({ status: "queued", transcript: "", drafts: [] });
      if (path.endsWith("/task-drafts/41/")) return draft({ status: "transcribing", transcript: "", drafts: [] });
      return undefined;
    };
    renderApp(null, { me: person([giver()]), init: { sheet: { kind: "feature", feature: "ai", sheet: "draft", params: { mode: "voice" } } } });
    expect(await screen.findByText("Listening to you")).toBeTruthy();
    vi.spyOn(performance, "now").mockReturnValue(performance.now() + 6000);
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(await screen.findByText("Listening…")).toBeTruthy();
    const post = server.calls.find((call) => call.path.endsWith("/task-drafts/") && call.method === "POST");
    const audio = post?.form?.get("audio");
    expect(audio).toBeInstanceOf(File);
    expect((audio as File).name).toBe("voice.webm");
    expect(post?.form?.get("seconds")).toBe("6");
    expect(post?.form?.get("language")).toBe("en");
  });
});
