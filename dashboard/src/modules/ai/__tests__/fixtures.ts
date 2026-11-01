/** Contract-shaped AI data for the module's tests (briefs/ai-contract.md §4–§5). */
import type { ActivityItem, Agent, AiDraft, AiStatus } from "../types";

export function status(overrides: Partial<AiStatus> = {}): AiStatus {
  return {
    enabled: true,
    can_configure: true,
    claude: "connected",
    speech: "ready",
    features: { voice: true, smart_text: true, chat: true, photo_checker: true },
    budget: { monthly_usd: "20.00", spent_usd: "0.42", resets_on: "2026-12-01" },
    ...overrides,
  };
}

export function aiDraft(overrides: Partial<AiDraft> = {}): AiDraft {
  return {
    id: 41,
    status: "ready",
    source: "dashboard",
    author: { id: 11, name: "Dilnoza Karimova" },
    created_at: "2026-11-02T09:14:03+05:00",
    audio: { seconds: 14, url: "/media/private/voice.webm" },
    transcript: "Alisher, ertaga soat o‘ngacha muzlatgich haroratini tekshirib, rasmini yubor. Bekzod, bugun kechqurun kassani sanab qo‘y.",
    language: "uz",
    engine: "rules",
    drafts: [
      {
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
      },
      {
        title: "Kassani sanash",
        description: "",
        assignee: null,
        assignee_guess: "Bekzod",
        due_at: null,
        due_text: "",
        priority: "normal",
        checklist: ["Naqd pul", "Terminal cheki"],
        proof: "none",
        problems: ["no_assignee_match", "no_due"],
      },
    ],
    questions: [],
    created_tasks: [],
    error_code: "",
    error: "",
    ...overrides,
  };
}

export function agent(overrides: Partial<Agent> = {}): Agent {
  return {
    key: "deadline_watcher",
    name: "Deadline watcher",
    description: "Late work goes to whoever gave it, once.",
    icon: "alarm-clock",
    enabled: true,
    needs_claude: false,
    available: true,
    unavailable_reason: "",
    schedule: "Every 30 min, 08:00–21:00",
    running: false,
    last_run_at: "2026-11-02T09:00:00+05:00",
    next_run_at: "2026-11-02T09:30:00+05:00",
    stats: { today: 3, week: 12 },
    config: { escalate_after_hours: 2, quiet_from: "21:00", quiet_to: "08:00" },
    fields: [
      { key: "escalate_after_hours", type: "int", label: "Tell after", help: "Hours late", min: 1, max: 48, unit: "h" },
      { key: "quiet_from", type: "time", label: "Quiet from", help: "" },
      { key: "quiet_to", type: "time", label: "Quiet until", help: "" },
    ],
    ...overrides,
  };
}

export const AGENTS: Agent[] = [
  agent({
    key: "voice_tasks",
    name: "Voice tasks",
    icon: "mic",
    description: "Voice and typed instructions become tasks.",
    schedule: "When a voice message arrives",
    last_run_at: null,
    next_run_at: null,
    stats: { today: 5, week: 21 },
    config: { auto_create: false, max_seconds: 120 },
    fields: [
      { key: "auto_create", type: "bool", label: "Create at once", help: "" },
      { key: "max_seconds", type: "int", label: "Longest message", help: "", min: 15, max: 300, unit: "s" },
    ],
  }),
  agent(),
  agent({ key: "morning_plan", name: "Morning plan", icon: "sunrise", stats: { today: 2, week: 10 }, config: { at: "08:30", who: "both" }, fields: [] }),
  agent({
    key: "photo_checker",
    name: "Photo checker",
    icon: "scan-eye",
    needs_claude: true,
    available: false,
    unavailable_reason: "needs_claude",
    enabled: false,
    stats: { today: 0, week: 0 },
    last_run_at: null,
    next_run_at: null,
    config: { only_routines: false },
    fields: [{ key: "only_routines", type: "bool", label: "Only routines", help: "" }],
  }),
];

export function activity(id: number, overrides: Partial<ActivityItem> = {}): ActivityItem {
  return {
    id,
    agent: "deadline_watcher",
    agent_name: "Deadline watcher",
    icon: "alarm-clock",
    kind: "escalated",
    level: "warning",
    text: `Event ${id}`,
    created_at: "2026-11-02T10:00:00+05:00",
    actor: null,
    subject: { type: "task", id: 300 + id, label: "Kassani sanash" },
    ...overrides,
  };
}
