/**
 * The AI endpoints of the mini app (`/api/v1/companies/{id}/ai/…`, contract §4), typed by hand
 * until the lead regenerates the schema: what the AI can do here, and task drafts made from a
 * voice note or a typed instruction (poll while it works, edit, apply, discard).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, apiForm, ApiError } from "../../api/client";
import { refreshAfterTaskChange } from "../../api/hooks";

export type AIStatus = {
  /** Voice notes become tasks here: AI on, the voice tasks agent on and speech ready. */
  voice: boolean;
  /** A typed instruction becomes tasks: AI on and the voice tasks agent on. */
  smart_text: boolean;
  engine: "claude" | "rules";
  /** The longest voice note the company takes. */
  max_seconds: number;
  /** Tasks are given at once when every one is clear (the voice tasks agent's switch). */
  auto_create: boolean;
  /** The employee bot, for "send it a voice message instead". */
  bot_username: string;
};

export type DraftStatus = "queued" | "transcribing" | "thinking" | "ready" | "failed" | "applied" | "discarded" | "expired";

export type Problem = "no_assignee_match" | "ambiguous_assignee" | "no_due" | "past_due" | "not_allowed";

export type DraftItem = {
  title: string;
  description: string;
  /** Null: for the author (then `assignee_guess` may name who was heard but not matched). */
  assignee: { id: number; name: string; position: string | null } | null;
  assignee_guess: string;
  due_at: string | null;
  due_text: string;
  priority: "normal" | "urgent";
  checklist: string[];
  proof: "none" | "photo";
  problems: Problem[];
};

export type AIDraft = {
  id: number;
  status: DraftStatus;
  source: "bot" | "owner_bot" | "miniapp" | "dashboard";
  author: { id: number; name: string };
  created_at: string;
  /** Null for typed text. */
  audio: { seconds: number; url: string } | null;
  transcript: string;
  language: string;
  engine: "claude" | "rules" | "fake";
  drafts: DraftItem[];
  questions: string[];
  created_tasks: { id: number; title: string; assignee_name: string }[];
  error_code: "" | "speech_unavailable" | "audio_unreadable" | "nothing_heard" | "ai_unavailable" | "expired";
  error: string;
};

/** One task as the review sends it back (`apply/` replaces the stored drafts with these). */
export type ApplyItem = {
  title: string;
  description: string;
  /** Null: for me. */
  assignee_id: number | null;
  due_at: string | null;
  priority: "normal" | "urgent";
  checklist: string[];
  proof: "none" | "photo";
};

export type ApplyResult = { draft: AIDraft; created: number[]; failed: { index: number; detail: string }[] };

/** Why a new draft was refused (`{"code": …}` on a 400, 403 or 429). */
export type CreateRefusal = "audio_too_long" | "audio_too_big" | "audio_unreadable" | "text_too_long" | "ai_off" | "limit_reached";

export const TEXT_MAX = 2000;

const base = (company: number) => `/companies/${company}/ai`;

export const aiKeys = {
  status: (company: number) => ["ai", company, "status"] as const,
  draft: (company: number, id: number) => ["ai", company, "draft", id] as const,
};

/** What the AI can do for this person now. A server without the endpoint reads as "nothing". */
export function useAIStatus(company: number) {
  return useQuery({
    queryKey: aiKeys.status(company),
    queryFn: () => api<AIStatus>(`${base(company)}/status/`),
    staleTime: 60_000,
    retry: (failures, error) => !(error instanceof ApiError && error.status < 500) && failures < 2,
  });
}

/** Which ways in to show: the mic needs voice, the sparkle a typed instruction. */
export function entryOf(status: AIStatus | undefined): { voice: boolean; text: boolean; any: boolean } {
  const voice = Boolean(status?.voice);
  const text = Boolean(status?.smart_text);
  return { voice, text, any: voice || text };
}

// — a draft at work —

/** How often a draft at work is asked about, and when the app stops asking (contract §4). */
export const POLL_MS = 1000;
export const GIVE_UP_MS = 90_000;

const WORKING: ReadonlySet<DraftStatus> = new Set(["queued", "transcribing", "thinking"]);

export function isWorking(draft: Pick<AIDraft, "status"> | undefined | null): boolean {
  return Boolean(draft && WORKING.has(draft.status));
}

/**
 * What the app says while it waits: "Listening…" until the words are written down (a voice note
 * still queued or being transcribed), then "Thinking…" (a typed text starts there).
 */
export function workingPhase(draft: Pick<AIDraft, "status" | "audio"> | undefined | null): "listening" | "thinking" | null {
  if (!draft || !isWorking(draft)) return null;
  if (draft.status === "thinking") return "thinking";
  if (draft.status === "transcribing") return "listening";
  return draft.audio ? "listening" : "thinking";
}

/**
 * Whether to ask again: every second while the draft works, until `GIVE_UP_MS` after `since`
 * (when this screen started waiting). Past that the screen offers to keep waiting.
 */
export function pollInterval(draft: Pick<AIDraft, "status"> | undefined, since: number, now: number): number | false {
  if (draft && !isWorking(draft)) return false;
  return now - since < GIVE_UP_MS ? POLL_MS : false;
}

/** Whether the wait has run past `GIVE_UP_MS` with the draft still at work. */
export function gaveUp(draft: Pick<AIDraft, "status"> | undefined, since: number, now: number): boolean {
  return (draft === undefined || isWorking(draft)) && now - since >= GIVE_UP_MS;
}

/** One draft, asked about every second while it works (from `since`, see `pollInterval`). */
export function useDraft(company: number, id: number | null, since: number) {
  return useQuery({
    queryKey: aiKeys.draft(company, id ?? 0),
    queryFn: () => api<AIDraft>(`${base(company)}/task-drafts/${id}/`),
    enabled: id !== null,
    refetchInterval: (query) => pollInterval(query.state.data, since, Date.now()),
    // Polled on its own clock: a refocus mid-wait mustn't add a burst of extra requests.
    refetchOnWindowFocus: false,
    retry: (failures, error) => !(error instanceof ApiError && error.status < 500) && failures < 3,
  });
}

export type VoiceNote = { blob: Blob; seconds: number; fileName: string; language: string };

/** Send a voice note or a typed instruction; the answer is the new draft (202), already working. */
export function useCreateDraft(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { voice: VoiceNote } | { text: string }) => {
      if ("text" in input) return api<AIDraft>(`${base(company)}/task-drafts/`, { json: { text: input.text } });
      const { blob, seconds, fileName, language } = input.voice;
      const file = new File([blob], fileName, { type: blob.type || "audio/webm" });
      return apiForm<AIDraft>(`${base(company)}/task-drafts/`, { audio: file, seconds: Math.max(1, Math.round(seconds)), language });
    },
    onSuccess: (draft) => client.setQueryData(aiKeys.draft(company, draft.id), draft),
  });
}

/** Create the reviewed tasks. They go out through the normal task flow, so lists refresh after. */
export function useApplyDraft(company: number, id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (drafts: ApplyItem[]) => api<ApplyResult>(`${base(company)}/task-drafts/${id}/apply/`, { json: { drafts } }),
    onSuccess: (result) => {
      client.setQueryData(aiKeys.draft(company, id), result.draft);
      refreshAfterTaskChange(client, company);
    },
  });
}

export function useDiscardDraft(company: number, id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>(`${base(company)}/task-drafts/${id}/discard/`, { method: "POST" }),
    onSuccess: () => client.removeQueries({ queryKey: aiKeys.draft(company, id) }),
  });
}

/** The stable reason a new draft was refused, when the server gave one. */
export function refusalOf(error: unknown): CreateRefusal | null {
  if (!(error instanceof ApiError) || !error.body || typeof error.body !== "object") return null;
  const code = (error.body as { code?: unknown }).code;
  const known: readonly string[] = ["audio_too_long", "audio_too_big", "audio_unreadable", "text_too_long", "ai_off", "limit_reached"];
  return typeof code === "string" && known.includes(code) ? (code as CreateRefusal) : null;
}
