/**
 * Switching an agent and "Run now", as the Agents page and an agent's own page both offer them:
 * which agent is saving or starting (for the spinners), and a toast with the agent's name when it
 * worked. A refusal is rolled back (usePatchAgent) and explained by the HTTP layer's toast.
 */
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import { toast } from "@/components/useToast";

import { usePatchAgent, useRunAgent } from "./api";
import type { Agent } from "./types";

export function useAgentActions() {
  const { t } = useI18n();
  const patch = usePatchAgent();
  const run = useRunAgent();
  const switching = ref<string | null>(null);
  const starting = ref<string | null>(null);

  async function toggle(agent: Pick<Agent, "key" | "name">, enabled: boolean): Promise<void> {
    switching.value = agent.key;
    try {
      await patch.mutateAsync({ key: agent.key, patch: { enabled } });
      toast.success(t(enabled ? "ai.agents.turnedOn" : "ai.agents.turnedOff", { name: agent.name }));
    } catch {
      // Rolled back; the reason is a toast.
    } finally {
      switching.value = null;
    }
  }

  async function runNow(agent: Pick<Agent, "key" | "name">): Promise<void> {
    starting.value = agent.key;
    try {
      await run.mutateAsync(agent.key);
      toast.success(t("ai.agents.started", { name: agent.name }));
    } catch {
      // The reason is a toast.
    } finally {
      starting.value = null;
    }
  }

  return { switching, starting, toggle, runNow };
}
