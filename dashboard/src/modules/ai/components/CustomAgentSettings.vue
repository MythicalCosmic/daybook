<script setup lang="ts">
/**
 * The settings of an agent an owner made: what it is set to at a glance (when it runs, who gets
 * it, what it may read, whose rights it reads with, who made it), why it paused itself when it
 * did, and Edit (the form), Pause or Switch on, and Delete (after a confirm: it never runs again,
 * what it did stays in the activity). Read-only without ai.configure, and while AI is off.
 */
import { Lock, Pause, Pencil, Play, Trash2, TriangleAlert } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import InlineAlert from "@/components/InlineAlert.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useAgentActions } from "../agentActions";
import { useDeleteCustomAgent } from "../api";
import type { AgentDetail, CustomAgentInfo } from "../types";

const props = defineProps<{ agent: AgentDetail & { custom: CustomAgentInfo }; canConfigure: boolean; aiOn: boolean }>();
const emit = defineEmits<{ edit: [] }>();

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const remove = useDeleteCustomAgent();
const { switching, toggle } = useAgentActions();

const custom = computed(() => props.agent.custom);
const editable = computed(() => props.canConfigure && props.aiOn);

const who = computed(() => {
  if (custom.value.recipients === "me") return t("ai.custom.to.meName", { name: custom.value.run_as.name });
  if (custom.value.recipients === "group") return custom.value.group?.title ?? t("ai.custom.groupGone");
  return custom.value.people.map((person) => person.name).join(", ");
});
const rows = computed(() => [
  { id: "when", label: t("ai.custom.field.when"), value: props.agent.schedule },
  { id: "who", label: t("ai.custom.field.who"), value: who.value },
  { id: "reads", label: t("ai.custom.field.reads"), value: custom.value.domains.map((domain) => domain.label).join(", ") },
  { id: "runAs", label: t("ai.custom.runAs"), value: custom.value.run_as.name },
  {
    id: "made",
    label: t("ai.custom.made"),
    value: [custom.value.created_by?.name, fmt.instant(custom.value.created_at, "date")].filter(Boolean).join(" · "),
  },
]);

async function destroy(): Promise<void> {
  const answer = await confirm({
    title: t("ai.custom.deleteTitle", { name: props.agent.name }),
    message: t("ai.custom.deleteBody"),
    confirmLabel: t("ai.custom.delete"),
    tone: "danger",
    icon: Trash2,
  });
  if (!answer) return;
  try {
    await remove.mutateAsync(props.agent);
    toast.success(t("ai.custom.deleted", { name: props.agent.name }));
    void router.replace({ name: "ai.agents", params: { companyId: company.currentId ?? 0 } });
  } catch {
    // The reason is a toast from the HTTP layer.
  }
}
</script>

<template>
  <div class="flex flex-col gap-4" data-testid="custom-settings">
    <InlineAlert v-if="custom.paused_reason" tone="warning" :icon="TriangleAlert" :title="t('ai.custom.pausedTitle')" :description="`${custom.paused_text}. ${t('ai.custom.pausedHint')}`" data-testid="custom-paused" />

    <dl class="ui-card flex flex-col divide-y divide-line">
      <div v-for="row in rows" :key="row.id" class="flex flex-col gap-0.5 px-4 py-3 sm:flex-row sm:gap-4 md:px-5" :data-row="row.id">
        <dt class="text-sm text-muted sm:w-44 sm:shrink-0">{{ row.label }}</dt>
        <dd class="min-w-0 flex-1 text-sm font-medium text-fg">{{ row.value }}</dd>
      </div>
    </dl>

    <div v-if="editable" class="flex flex-wrap gap-2">
      <UiButton :icon="Pencil" data-testid="custom-edit" @click="emit('edit')">{{ t("ai.custom.edit") }}</UiButton>
      <UiButton
        variant="ghost"
        :icon="agent.enabled ? Pause : Play"
        :loading="switching === agent.key"
        data-testid="custom-pause"
        @click="toggle(agent, !agent.enabled)"
      >
        {{ agent.enabled ? t("ai.custom.pause") : t("ai.custom.resume") }}
      </UiButton>
      <span class="flex-1" />
      <UiButton variant="ghost" class="text-danger" :icon="Trash2" :loading="remove.isPending.value" data-testid="custom-delete" @click="destroy">{{ t("ai.custom.delete") }}</UiButton>
    </div>
    <p v-else-if="!canConfigure" class="flex items-start gap-2 px-1 text-sm text-muted" data-testid="agent-read-only">
      <Lock :size="14" class="mt-0.5 shrink-0" aria-hidden="true" />{{ t("ai.agents.onlyOwner") }}
    </p>
    <p v-else class="px-1 text-sm text-muted">{{ t("ai.agent.settings.aiOff") }}</p>
  </div>
</template>
