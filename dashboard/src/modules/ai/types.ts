/**
 * The AI endpoints' shapes (briefs/ai-contract.md §4–§5, `/api/v1/owner/companies/{cid}/ai/…`),
 * typed by hand until the owner schema has them.
 */

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
}

export interface AgentPatch {
  enabled?: boolean;
  config?: Record<string, AgentConfigValue>;
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
