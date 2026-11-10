/**
 * Pure helpers of the policy pages: categories and states (icons, tones), who a policy applies to
 * in words, the signing progress, and the comparison of two versions' text (paragraphs first, then
 * the words inside a changed one).
 */
import { BookText, Pill, Scale, ShieldCheck, Thermometer } from "@lucide/vue";
import type { Component } from "vue";

import type { StatusTone } from "@/components/StatusPill.vue";

import type { Policy, PolicyCategory, PolicyStanding, PolicyTally } from "./types";

export const CATEGORY_ICONS: Record<PolicyCategory, Component> = {
  dispensing: Pill,
  storage: Thermometer,
  safety: ShieldCheck,
  conduct: Scale,
  other: BookText,
};

/** The tinted square behind a category's icon. */
export const CATEGORY_TINTS: Record<PolicyCategory, string> = {
  dispensing: "bg-success-soft text-success",
  storage: "bg-info-soft text-info",
  safety: "bg-warning-soft text-warning",
  conduct: "bg-accent-soft text-accent-fg",
  other: "bg-surface-2 text-muted dark:bg-surface-3",
};

export const STANDING_TONES: Record<PolicyStanding, StatusTone> = {
  signed: "success",
  waiting: "info",
  late: "danger",
  to_read: "neutral",
};

/** The list a policy belongs to. */
export function policyView(policy: Pick<Policy, "is_active" | "version">): "active" | "drafts" | "archived" {
  if (!policy.is_active) return "archived";
  return policy.version ? "active" : "drafts";
}

/** "Farmatsevt, Provizor" or the word for everyone; the same for branches. */
export function audienceParts(policy: Pick<Policy, "positions" | "branches">, words: { everyPosition: string; everyBranch: string }): { positions: string; branches: string } {
  return {
    positions: policy.positions.length ? policy.positions.map((row) => row.name).join(", ") : words.everyPosition,
    branches: policy.branches.length ? policy.branches.map((row) => row.name).join(", ") : words.everyBranch,
  };
}

/** Signed share of everyone asked, 0–100 (100 when nobody is asked). */
export function signedPercent(tally: PolicyTally | null | undefined): number {
  if (!tally || tally.total === 0) return 100;
  return Math.round((tally.signed / tally.total) * 100);
}

export function policyPath(cid: number | string, id: number, rest = ""): string {
  return `/c/${cid}/hr/policies/${id}${rest}`;
}

/** Whole days from `today` to `day` (both YYYY-MM-DD); negative once it has passed. */
export function daysUntil(day: string, today: string): number {
  const ms = Date.parse(`${day}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`);
  return Math.round(ms / 86_400_000);
}

// Comparing two versions -------------------------------------------------------------------------

export type DiffKind = "same" | "added" | "removed";
export interface DiffPart {
  kind: DiffKind;
  text: string;
}
export interface DiffBlock {
  kind: DiffKind | "changed";
  /** One part for a whole block; several (words) for a changed one. */
  parts: DiffPart[];
}

// Beyond this many cells a table-driven comparison would stall the page: the blocks are then
// compared one for one.
const MAX_CELLS = 250_000;

/** The longest common subsequence of `a` and `b` as a script of same / removed / added items. */
export function lcsScript<T>(a: readonly T[], b: readonly T[]): Array<{ kind: DiffKind; item: T }> {
  const n = a.length;
  const m = b.length;
  if (n * m > MAX_CELLS) {
    return [...a.map((item) => ({ kind: "removed" as const, item })), ...b.map((item) => ({ kind: "added" as const, item }))];
  }
  // lengths[i][j]: LCS length of a[i..] and b[j..], in one flat array.
  const width = m + 1;
  const lengths = new Uint32Array((n + 1) * width);
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      lengths[i * width + j] = a[i] === b[j] ? lengths[(i + 1) * width + j + 1]! + 1 : Math.max(lengths[(i + 1) * width + j]!, lengths[i * width + j + 1]!);
    }
  }
  const script: Array<{ kind: DiffKind; item: T }> = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      script.push({ kind: "same", item: a[i]! });
      i += 1;
      j += 1;
    } else if (lengths[(i + 1) * width + j]! >= lengths[i * width + j + 1]!) {
      script.push({ kind: "removed", item: a[i]! });
      i += 1;
    } else {
      script.push({ kind: "added", item: b[j]! });
      j += 1;
    }
  }
  while (i < n) script.push({ kind: "removed", item: a[i++]! });
  while (j < m) script.push({ kind: "added", item: b[j++]! });
  return script;
}

/** A text as its paragraphs (one per line, blank lines dropped, spaces tidied). */
export function paragraphs(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

/** The words of one paragraph and the spaces between them, so joining them gives it back. */
function tokens(line: string): string[] {
  return line.split(/(\s+)/).filter((token) => token !== "");
}

/** Adjacent parts of the same kind as one. */
function merged(parts: DiffPart[]): DiffPart[] {
  const out: DiffPart[] = [];
  for (const part of parts) {
    const last = out.at(-1);
    if (last && last.kind === part.kind) last.text += part.text;
    else out.push({ ...part });
  }
  return out;
}

/** Words removed and added inside one changed paragraph. */
export function wordDiff(before: string, after: string): DiffPart[] {
  return merged(lcsScript(tokens(before), tokens(after)).map(({ kind, item }) => ({ kind, text: item })));
}

/**
 * What changed from `before` to `after` (plain texts, one paragraph a line): unchanged, added and
 * removed paragraphs, and a removed paragraph followed by an added one shown as one changed
 * paragraph with its words marked, when the two still share most of their words.
 */
export function diffText(before: string, after: string): DiffBlock[] {
  const script = lcsScript(paragraphs(before), paragraphs(after));
  const blocks: DiffBlock[] = [];
  let index = 0;
  while (index < script.length) {
    const step = script[index]!;
    if (step.kind === "same") {
      blocks.push({ kind: "same", parts: [{ kind: "same", text: step.item }] });
      index += 1;
      continue;
    }
    // A run of removed paragraphs, then a run of added ones: pair them up while they look alike.
    const removed: string[] = [];
    const added: string[] = [];
    while (index < script.length && script[index]!.kind === "removed") removed.push(script[index++]!.item);
    while (index < script.length && script[index]!.kind === "added") added.push(script[index++]!.item);
    const pairs = Math.min(removed.length, added.length);
    for (let k = 0; k < Math.max(removed.length, added.length); k += 1) {
      const old = removed[k];
      const fresh = added[k];
      if (k < pairs && old !== undefined && fresh !== undefined && alike(old, fresh)) {
        blocks.push({ kind: "changed", parts: wordDiff(old, fresh) });
        continue;
      }
      if (old !== undefined) blocks.push({ kind: "removed", parts: [{ kind: "removed", text: old }] });
      if (fresh !== undefined) blocks.push({ kind: "added", parts: [{ kind: "added", text: fresh }] });
    }
  }
  return blocks;
}

/** Two paragraphs share at least half of their words (then a word diff reads well). */
function alike(before: string, after: string): boolean {
  const parts = wordDiff(before, after);
  const same = parts.filter((part) => part.kind === "same").reduce((sum, part) => sum + part.text.trim().split(/\s+/).filter(Boolean).length, 0);
  const total = Math.max(before.split(/\s+/).length, after.split(/\s+/).length);
  return total > 0 && same / total >= 0.5;
}

/** How many paragraphs were added, removed or changed. */
export function diffCounts(blocks: readonly DiffBlock[]): { added: number; removed: number; changed: number } {
  return {
    added: blocks.filter((block) => block.kind === "added").length,
    removed: blocks.filter((block) => block.kind === "removed").length,
    changed: blocks.filter((block) => block.kind === "changed").length,
  };
}
