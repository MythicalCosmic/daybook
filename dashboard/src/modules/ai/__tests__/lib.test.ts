import { describe, expect, it } from "vitest";

import { ApiError } from "@/api/http";

import {
  aiVisibility,
  applyBlockers,
  applyFix,
  arrivals,
  blockingProblems,
  budgetShare,
  coerceValue,
  fieldControl,
  formatSeconds,
  isMissingEndpoint,
  isWorking,
  liveProblems,
  mergeActivity,
  pollDecision,
  problemFixes,
  setAssignee,
  subjectPath,
  toApplyPayload,
  toEditable,
  turnIsLive,
  workingPhase,
  zonedIso,
  zonedParts,
} from "../lib";
import type { AgentField } from "../types";
import { activity, aiDraft, status } from "./fixtures";

const TZ = "Asia/Tashkent";
const item = activity;

describe("status → what shows", () => {
  it("offers Turn on to whoever may configure, and a notice to everyone else, while AI is off", () => {
    const off = aiVisibility(status({ enabled: false }));
    expect(off).toMatchObject({ turnOn: true, offNotice: false, dictate: false, smartAdd: false, chat: false, chatTeaser: true });
    const offForStaff = aiVisibility(status({ enabled: false, can_configure: false }));
    expect(offForStaff).toMatchObject({ turnOn: false, offNotice: true, chatTeaser: false });
  });

  it("shows Dictate, Smart add and Ask AI from the features, and the key notice without a key", () => {
    expect(aiVisibility(status())).toMatchObject({ turnOn: false, dictate: true, smartAdd: true, chat: true, chatTeaser: false, keyNotice: false });
    const noKey = aiVisibility(status({ claude: "not_configured", speech: "not_configured", features: { voice: false, smart_text: true, chat: false, photo_checker: false } }));
    expect(noKey).toMatchObject({ dictate: false, smartAdd: true, chat: false, chatTeaser: true, keyNotice: true });
    expect(aiVisibility(status({ claude: "not_configured", can_configure: false })).keyNotice).toBe(false);
    expect(aiVisibility(undefined)).toMatchObject({ turnOn: false, dictate: false, chat: false });
  });
});

describe("draft polling decisions", () => {
  it("polls while the AI works, stops at an answer and gives up after 90 s", () => {
    expect(isWorking("queued")).toBe(true);
    expect(isWorking("thinking")).toBe(true);
    expect(isWorking("ready")).toBe(false);
    expect(pollDecision(undefined, 0)).toBe("poll");
    expect(pollDecision("transcribing", 89_999)).toBe("poll");
    expect(pollDecision("thinking", 90_000)).toBe("give_up");
    expect(pollDecision("ready", 120_000)).toBe("stop");
    expect(pollDecision("failed", 1000)).toBe("stop");
  });

  it("names the phase: listening for a recording, understanding for text", () => {
    expect(workingPhase(undefined, true)).toBe("upload");
    expect(workingPhase("transcribing", true)).toBe("listening");
    expect(workingPhase("queued", true)).toBe("listening");
    expect(workingPhase("queued", false)).toBe("thinking");
    expect(workingPhase("thinking", true)).toBe("thinking");
  });

  it("knows a live chat turn", () => {
    expect(turnIsLive("queued")).toBe(true);
    expect(turnIsLive("running")).toBe(true);
    expect(turnIsLive("done")).toBe(false);
    expect(turnIsLive(undefined)).toBe(false);
  });
});

describe("draft edits → apply payload", () => {
  it("sends the drafts as reviewed: edits kept, removed ones left out, empty steps dropped", () => {
    const edits = toEditable(aiDraft());
    expect(edits).toHaveLength(2);
    expect(edits[0]).toMatchObject({ key: "41:0", assigneeId: 15, dueText: "Ertaga, 10:00", proof: "photo", problems: [] });
    edits[0] = { ...edits[0]!, title: "  Muzlatgich haroratini tekshirish (2–8 °C) ", priority: "urgent", checklist: ["Termometr", " ", ""] };
    edits[1] = setAssignee(edits[1]!, { id: 16, name: "Bekzod Mirzayev", position: "Kassir" });
    edits[1] = applyFix(edits[1]!, { kind: "due", day: "2026-11-02", time: "18:00" }, { timeZone: TZ });
    expect(toApplyPayload(edits)).toEqual({
      drafts: [
        {
          title: "Muzlatgich haroratini tekshirish (2–8 °C)",
          description: "",
          assignee_id: 15,
          due_at: "2026-11-03T10:00:00+05:00",
          priority: "urgent",
          checklist: ["Termometr"],
          proof: "photo",
        },
        {
          title: "Kassani sanash",
          description: "",
          assignee_id: 16,
          due_at: "2026-11-02T18:00:00.000+05:00",
          priority: "normal",
          checklist: ["Naqd pul", "Terminal cheki"],
          proof: "none",
        },
      ],
    });
    edits[0] = { ...edits[0]!, removed: true };
    expect(toApplyPayload(edits).drafts.map((d) => d.title)).toEqual(["Kassani sanash"]);
  });

  it("sends “me” as no assignee", () => {
    const [first] = toEditable(aiDraft());
    expect(toApplyPayload([setAssignee(first!, null)]).drafts[0]!.assignee_id).toBeNull();
  });
});

describe("problems → fixes", () => {
  const morning = Date.parse("2026-11-02T09:30:00+05:00");
  const evening = Date.parse("2026-11-02T19:30:00+05:00");

  it("lists the one-tap fixes for each problem", () => {
    const edit = toEditable(aiDraft())[1]!;
    expect(problemFixes("no_assignee_match", edit, { timeZone: TZ, now: morning })).toEqual([{ kind: "pick" }, { kind: "me" }]);
    expect(problemFixes("no_due", edit, { timeZone: TZ, now: morning })).toEqual([
      { kind: "due", day: "2026-11-02", time: "18:00" },
      { kind: "due", day: "2026-11-03", time: "09:00" },
    ]);
    // In the evening "today, 18:00" is gone.
    expect(problemFixes("no_due", edit, { timeZone: TZ, now: evening })).toEqual([{ kind: "due", day: "2026-11-03", time: "09:00" }]);
    const late = { ...edit, dueAt: "2026-11-02T08:00:00+05:00" };
    expect(problemFixes("past_due", late, { timeZone: TZ, now: morning })).toEqual([
      { kind: "due", day: "2026-11-03", time: "08:00" },
      { kind: "due", day: "2026-11-03", time: "09:00" },
    ]);
  });

  it("clears a problem once its fix or a hand edit answers it", () => {
    const edit = toEditable(aiDraft())[1]!;
    expect(liveProblems(edit, morning)).toEqual(["no_assignee_match", "no_due"]);
    expect(blockingProblems(edit, morning)).toEqual(["no_assignee_match"]);
    const forMe = applyFix(edit, { kind: "me" }, { timeZone: TZ });
    expect(liveProblems(forMe, morning)).toEqual(["no_due"]);
    const timed = applyFix(forMe, { kind: "due", day: "2026-11-03", time: "09:00" }, { timeZone: TZ });
    expect(liveProblems(timed, morning)).toEqual([]);
    expect(applyFix(timed, { kind: "keepNoDue" }, { timeZone: TZ })).toMatchObject({ dueAt: null, dueTouched: true });
  });

  it("flags a deadline that passed while the person was reading", () => {
    const [first] = toEditable(aiDraft());
    expect(liveProblems(first!, Date.parse("2026-11-03T10:30:00+05:00"))).toEqual(["past_due"]);
  });

  it("says what stops Create: problems, missing titles, nothing left", () => {
    const edits = toEditable(aiDraft());
    expect(applyBlockers(edits, morning)).toEqual({ count: 2, untitled: 0, problems: 1 });
    edits[1] = setAssignee(edits[1]!, { id: 16, name: "Bekzod Mirzayev" });
    edits[0] = { ...edits[0]!, title: " " };
    expect(applyBlockers(edits, morning)).toEqual({ count: 2, untitled: 1, problems: 0 });
    expect(applyBlockers(edits.map((edit) => ({ ...edit, removed: true })), morning)).toEqual({ count: 0, untitled: 0, problems: 0 });
  });

  it("reads and writes company-local times", () => {
    expect(zonedIso("2026-11-03", "10:00", TZ)).toBe("2026-11-03T10:00:00.000+05:00");
    expect(zonedParts("2026-11-03T05:00:00.000Z", TZ)).toEqual({ day: "2026-11-03", time: "10:00" });
  });
});

describe("agent settings: fields → controls", () => {
  const int: AgentField = { key: "escalate_after_hours", type: "int", label: "After", help: "", min: 1, max: 48, unit: "h" };
  const time: AgentField = { key: "at", type: "time", label: "At", help: "" };
  const who: AgentField = { key: "who", type: "choice", label: "Who", help: "", options: [{ value: "heads", label: "Heads" }, { value: "managers", label: "Managers" }, { value: "both", label: "Both" }] };
  const many: AgentField = { ...who, options: [...who.options!, { value: "owners", label: "Owners" }] };

  it("draws each type with its control", () => {
    expect(fieldControl({ key: "auto_create", type: "bool", label: "Auto", help: "" })).toEqual({ kind: "switch" });
    expect(fieldControl(int)).toEqual({ kind: "stepper", min: 1, max: 48, unit: "h" });
    expect(fieldControl(time)).toEqual({ kind: "time" });
    expect(fieldControl(who).kind).toBe("segmented");
    expect(fieldControl(many).kind).toBe("select");
    expect(fieldControl({ ...who, options: [{ value: "a", label: "A very long choice label" }] }).kind).toBe("select");
  });

  it("only lets valid values through", () => {
    expect(coerceValue(int, 72)).toBe(48);
    expect(coerceValue(int, 0)).toBe(1);
    expect(coerceValue(int, "3.6")).toBe(4);
    expect(coerceValue(int, "x")).toBe(1);
    expect(coerceValue(time, "8:5")).toBeNull();
    expect(coerceValue(time, "8:30")).toBe("08:30");
    expect(coerceValue(time, "25:99")).toBe("23:59");
    expect(coerceValue(who, "managers")).toBe("managers");
    expect(coerceValue(who, "nobody")).toBe("heads");
    expect(coerceValue({ key: "b", type: "bool", label: "", help: "" }, "true")).toBe(true);
  });
});

describe("activity paging and merging", () => {
  it("keeps one copy of each item, newest first, and knows what just arrived", () => {
    const first = [item(30), item(29), item(28)];
    const older = [item(27), item(26)];
    const merged = mergeActivity(first, older);
    expect(merged.map((x) => x.id)).toEqual([30, 29, 28, 27, 26]);
    const polled = [item(32), item(31), item(30, { text: "Edited" }), item(29)];
    const next = mergeActivity(merged, polled);
    expect(next.map((x) => x.id)).toEqual([32, 31, 30, 29, 28, 27, 26]);
    expect(next[2]!.text).toBe("Edited");
    expect(arrivals(merged, next)).toEqual([32, 31]);
    // The first page is not an "arrival": nothing slides in on first load.
    expect(arrivals([], first)).toEqual([]);
    // An older page appended below doesn't slide in either.
    expect(arrivals(first, merged)).toEqual([]);
  });

  it("opens a subject where it lives", () => {
    expect(subjectPath({ type: "task", id: 345 }, 1)).toBe("/c/1/tasks?task=345");
    expect(subjectPath({ type: "member", id: 17 }, 1)).toBe("/c/1/people/17");
    expect(subjectPath({ type: "draft", id: 41 }, 1)).toBe("/c/1/ai/voice?draft=41");
  });
});

describe("formats", () => {
  it("writes seconds as a clock and the budget as a share", () => {
    expect(formatSeconds(0)).toBe("0:00");
    expect(formatSeconds(14.7)).toBe("0:14");
    expect(formatSeconds(125)).toBe("2:05");
    expect(budgetShare({ monthly_usd: "20.00", spent_usd: "5.00" })).toBe(0.25);
    expect(budgetShare({ monthly_usd: "0", spent_usd: "5.00" })).toBe(0);
    expect(budgetShare({ monthly_usd: "10", spent_usd: "50" })).toBe(1);
    expect(budgetShare(null)).toBe(0);
  });
});

describe("a server without the endpoint yet", () => {
  it("tells a missing endpoint (an AI step not deployed) from a real refusal", () => {
    expect(isMissingEndpoint(new ApiError(404, "<h1>Not Found</h1>"))).toBe(true);
    expect(isMissingEndpoint(new ApiError(405, null))).toBe(true);
    expect(isMissingEndpoint(new ApiError(404, { code: "not_found", detail: "No such agent" }))).toBe(false);
    expect(isMissingEndpoint(new ApiError(500, null))).toBe(false);
    expect(isMissingEndpoint(new Error("x"))).toBe(false);
  });
});
