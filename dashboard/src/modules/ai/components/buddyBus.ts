/**
 * How the AI's helpers hear about things. `greet`: Claude's helper poked an agent's card, so that
 * agent's chibi greets it back (AgentChibi.vue). `cue`: something happened in the company that a
 * helper reacts to — a voice note to listen to, a late task, a finished task (buddyCues.ts); the key
 * is an agent's, or "" for everyone.
 */
import { ref } from "vue";

import type { BuddyAction } from "../lib";

export const buddyGreeting = ref<{ key: string; n: number } | null>(null);
export const buddyCue = ref<{ key: string; action: BuddyAction; visit: boolean; n: number } | null>(null);
let count = 0;

export function greet(agentKey: string): void {
  buddyGreeting.value = { key: agentKey, n: (count += 1) };
}

export function cue(agentKey: string, action: BuddyAction, visit = false): void {
  buddyCue.value = { key: agentKey, action, visit, n: (count += 1) };
}
