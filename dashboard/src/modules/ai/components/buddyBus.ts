/** Claude's helper poked an agent's card: that agent's chibi greets it back (AgentChibi.vue). */
import { ref } from "vue";

export const buddyGreeting = ref<{ key: string; n: number } | null>(null);
let count = 0;

export function greet(agentKey: string): void {
  buddyGreeting.value = { key: agentKey, n: (count += 1) };
}
