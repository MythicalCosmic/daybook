/**
 * The AI endpoints' shapes (briefs/ai-contract.md §4–§5, `/api/v1/owner/companies/{cid}/ai/…`),
 * typed by hand until the owner schema has them.
 */
import type { SceneState } from "./scene";

export type ClaudeState = "connected" | "not_configured" | "fake" | "blocked" | "budget_reached" | "unavailable";
export type SpeechState = "ready" | "not_configured" | "fake";

export interface AiFeatures {
  voice: boolean;
  smart_text: boolean;
  chat: boolean;
  photo_checker: boolean;
}

export interface AiBudget {
  monthly_usd: string;
  spent_usd: string;
  resets_on: string;
}

/** `GET ai/status/` (dashboard.access). */
export interface AiStatus {
  enabled: boolean;
  can_configure: boolean;
  claude: ClaudeState;
  speech: SpeechState;
  features: AiFeatures;
  /** Only for ai.configure, else null. */
  budget: AiBudget | null;
  /** The owner bot, when the server says (voice messages work there too). Not in the contract. */
  bot_username?: string;
}

/** `GET/PATCH ai/settings/` (ai.configure). */
export interface AiSettings {
  enabled: boolean;
  enabled_by?: number | null;
  enabled_by_name: string;
  enabled_at: string | null;
  platform_blocked: boolean;
  monthly_budget_usd: string;
  share_task_text: boolean;
  share_finance: boolean;
  share_salaries: boolean;
  voice_retention_days: number;
  member_daily_drafts: number;
}

export type AiSettingsPatch = Partial<
  Pick<AiSettings, "monthly_budget_usd" | "share_task_text" | "share_finance" | "share_salaries" | "voice_retention_days" | "member_daily_drafts">
>;

// ─── Task drafts ────────────────────────────────────────────────────────────

export type DraftStatus = "queued" | "transcribing" | "thinking" | "ready" | "failed" | "applied" | "discarded" | "expired";
export type DraftSource = "bot" | "owner_bot" | "miniapp" | "dashboard";
export type DraftProblem = "no_assignee_match" | "ambiguous_assignee" | "no_due" | "past_due" | "not_allowed";
export type DraftErrorCode = "" | "speech_unavailable" | "audio_unreadable" | "nothing_heard" | "ai_unavailable" | "expired";

export interface DraftPerson {
  id: number;
  name: string;
  position?: string | null;
}

/** One task the AI understood. `assignee` null = for the author. */
export interface DraftItem {
  title: string;
  description: string;
  assignee: DraftPerson | null;
  /** Who was heard but not matched ("Alisher"), when `assignee` is null. */
  assignee_guess: string;
  due_at: string | null;
  due_text: string;
  priority: "normal" | "urgent";
  checklist: string[];
  proof: "none" | "photo";
  problems: DraftProblem[];
}

export interface CreatedTask {
  id: number;
  title: string;
  assignee_name: string;
}

export interface AiDraft {
  id: number;
  status: DraftStatus;
  source: DraftSource;
  author: { id: number; name: string } | null;
  created_at: string;
  /** null for typed text; `url` is a signed link, null once the recording was deleted. */
  audio: { seconds: number | null; url: string | null } | null;
  transcript: string;
  language: string;
  engine: "claude" | "rules" | "fake" | string;
  drafts: DraftItem[];
  questions: string[];
  created_tasks: CreatedTask[];
  error_code: DraftErrorCode | string;
  error: string;
}

/** One draft as `apply/` takes it (`assignee_id` null = for me). */
export interface ApplyDraft {
  title: string;
  description: string;
  assignee_id: number | null;
  due_at: string | null;
  priority: "normal" | "urgent";
  checklist: string[];
  proof: "none" | "photo";
}

export interface ApplyResult {
  draft: AiDraft;
  created: number[];
  failed: { index: number; detail: string }[];
}

/** The codes `POST ai/task-drafts/` refuses with. */
export type DraftRefusal = "audio_too_long" | "audio_too_big" | "audio_unreadable" | "text_too_long" | "ai_off" | "limit_reached";

// ─── Agents and activity ────────────────────────────────────────────────────

export type AgentFieldType = "bool" | "int" | "time" | "choice";

export interface AgentField {
  key: string;
  type: AgentFieldType;
  label: string;
  help: string;
  min?: number;
  max?: number;
  unit?: string;
  options?: { value: string; label: string }[];
}

export type AgentConfigValue = boolean | number | string | null;

export interface Agent {
  key: string;
  name: string;
  description: string;
  /** A lucide icon name ("alarm-clock"). */
  icon: string;
  enabled: boolean;
  needs_claude: boolean;
  available: boolean;
  unavailable_reason: "" | "needs_claude" | "needs_speech" | "ai_off";
  /** Already translated ("Har 30 daqiqada, 08:00–21:00"). */
  schedule: string;
  running: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  stats: { today: number; week: number };
  config: Record<string, AgentConfigValue>;
  fields: AgentField[];
  /** An agent an owner made (key `custom_<id>`); null (or absent) for a built-in one. */
  custom?: CustomAgentInfo | null;
}

export interface AgentPatch {
  enabled?: boolean;
  config?: Record<string, AgentConfigValue>;
  /** The owner's own instructions ("" takes them away). */
  instructions?: string;
}

// ─── One agent's page (`GET ai/agents/{key}/`, briefs/v5-agent-page.md) ─────

export type AgentRunStatus = "running" | "ok" | "error";

/** One run of the agent, newest first. `error` and `cost_usd` are null without ai.configure. */
export interface AgentRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  status: AgentRunStatus;
  /** Started with "Run now". */
  forced: boolean;
  /** How many things the run did. */
  done: number;
  error: string | null;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string | null;
}

/** One Claude call the agent made (never a prompt or an answer). */
export interface AgentCall {
  at: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  latency_ms: number;
  stop_reason: string;
  cost_usd: string | null;
}

export interface AgentUsageDay {
  /** A company-local day, "2026-11-03". */
  date: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string | null;
}

export interface AgentUsage {
  month: { calls: number; input_tokens: number; output_tokens: number; cache_read_tokens: number; cost_usd: string | null };
  /** The last 30 days in the company's calendar, oldest first, days without calls included. */
  days: AgentUsageDay[];
  /** The whole company's month, for this agent's share of it (ai.configure only, else null). */
  company: { month_cost_usd: string; monthly_budget_usd: string } | null;
}

/** What comes next: a scheduled run, or something the agent expects (counts only, already translated). */
export interface AgentUpcoming {
  at: string | null;
  kind: "run" | "item";
  label: string;
}

/** What an agent asks Claude: the job, and its system prompt as Claude reads it (English). */
export interface AgentPrompt {
  label: string;
  text: string;
}

export interface AgentDetail extends Agent {
  runs: AgentRun[];
  calls: AgentCall[];
  usage: AgentUsage;
  upcoming: AgentUpcoming[];
  /** What its scene shows (AgentScene.vue): at work, on and waiting, or asleep. */
  scene: SceneState;
  /** What it asks Claude; none when it works by fixed rules. */
  prompts: AgentPrompt[];
  /** The owner's own instructions, added after each prompt. */
  instructions: string;
}

export type ActivityLevel = "info" | "success" | "warning";
export type SubjectType = "task" | "member" | "draft";

export interface ActivityItem {
  id: number;
  agent: string;
  agent_name: string;
  icon: string;
  kind: string;
  level: ActivityLevel;
  text: string;
  created_at: string;
  actor: { id: number; name: string; photo: string | null } | null;
  subject: { type: SubjectType; id: number; label: string } | null;
}

export interface ActivityPage {
  results: ActivityItem[];
  next_before: number | null;
}

// ─── Ask AI ─────────────────────────────────────────────────────────────────

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  /** The last question or answer (the real API sends it; the list is ordered by it). */
  last_activity_at?: string;
}

export interface TurnStep {
  label: string;
  status: "done" | "error" | "running" | string;
  ms: number | null;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  created_at: string;
  steps: TurnStep[];
}

export type TurnStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export interface Turn {
  id: number;
  status: TurnStatus;
  steps: TurnStep[];
  /** Markdown so far, or the final answer. */
  text: string;
  error_code: string;
  message_id: number | null;
}

// ─── The agents an owner makes (`ai/custom-agents/…`, briefs/v6-k.md) ───────

export type CustomFrequency = "daily" | "weekdays" | "weekly" | "monthly";
export type CustomRecipients = "me" | "people" | "group";
/** Its chibi's colour (apps.ai.models.CustomAgent.Color). */
export type CustomColor = "sky" | "rose" | "indigo" | "lime" | "amber" | "plum" | "aqua" | "slate";

export interface CustomPerson {
  id: number;
  name: string;
}

/** An agent's own fields when an owner made it (`Agent.custom`; null for a built-in one). */
export interface CustomAgentInfo {
  id: number;
  /** What it should do, in the owner's words. */
  job: string;
  color: CustomColor;
  /** The template it started from ("" = written from scratch). */
  template: string;
  frequency: CustomFrequency;
  /** "HH:MM" in the company's timezone. */
  at: string;
  /** Weekly: 0 = Monday. */
  weekday: number | null;
  /** Monthly: 1–28. */
  month_day: number | null;
  recipients: CustomRecipients;
  people: CustomPerson[];
  group: { id: number; title: string } | null;
  domains: { key: string; label: string }[];
  /** Whose rights it reads with: who "me" is. */
  run_as: CustomPerson;
  created_by: CustomPerson | null;
  created_at: string;
  /** Why it switched itself off: "", "left" or "no_access". */
  paused_reason: string;
  paused_text: string;
  /** What it last wrote, only for its owner and the people it goes to (else null). */
  last_report: string | null;
  last_report_at: string | null;
}

/** `GET ai/custom-agents/templates/`: a ready job, in the reader's language. */
export interface CustomAgentTemplate {
  key: string;
  name: string;
  job: string;
  frequency: CustomFrequency;
  at: string;
  weekday: number | null;
  month_day: number | null;
  domains: string[];
  color: CustomColor;
  /** A lucide icon name. */
  icon: string;
  /** The module it is about. */
  needs: string | null;
}

/** What it may read, as the form offers it. */
export interface CustomDomainOption {
  key: string;
  label: string;
  /** Whether the person setting it up may read it themselves. */
  available: boolean;
  /** "", "switch_off" (Settings › AI keeps it from the AI) or "no_access". */
  reason: string;
  feature: string | null;
}

/** `GET ai/custom-agents/options/` (ai.configure). */
export interface CustomAgentOptions {
  domains: CustomDomainOption[];
  groups: { id: number; title: string }[];
  people: { id: number; name: string; position: string; photo: string | null }[];
  max_agents: number;
  live: number;
  run_now_left: number;
  me: CustomPerson;
}

/** The New agent form (POST `ai/custom-agents/`, or PATCH with the same fields). */
export interface CustomAgentForm {
  name: string;
  job: string;
  color: CustomColor;
  template: string;
  frequency: CustomFrequency;
  at: string;
  weekday: number | null;
  month_day: number | null;
  recipients: CustomRecipients;
  people: number[];
  group: number | null;
  domains: string[];
}
