<script setup lang="ts">
/**
 * Ko‘z › Cameras and boxes (docs/KOZ.md §6.4, §6.8): the boxes (online, version, cameras; a new
 * code or removing one), pairing a new box (`?pair=1`), and every camera by branch with its
 * picture, role, switch, till and zones. `vision.manage` only.
 */
import { Cctv, Plus } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { deleteAgent, newPairing, useAgents, useCameras, useRefresh, useRegisters } from "../api";
import BoxCard from "../components/BoxCard.vue";
import CameraCard from "../components/CameraCard.vue";
import PairDialog from "../components/PairDialog.vue";
import { ROLE_ORDER } from "../lib/rules";
import type { Agent, Camera, Pairing } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const companyId = useCompanyId();
const confirm = useConfirm();
const refresh = useRefresh();

const pairing = useAgents(false);
const agents = computed(() => pairing.data.value ?? []);
const cameras = useCameras(null);
const registers = useRegisters(computed(() => company.enabled("sales")));
const pair = useRouteState("pair", rs.boolean(), { push: true });

const repairing = ref<{ agent: Agent; pairing: Pairing } | null>(null);
const repairOpen = computed({ get: () => repairing.value !== null, set: (value: boolean) => (repairing.value = value ? repairing.value : null) });

async function repair(agent: Agent): Promise<void> {
  const answer = await confirm({ title: t("vision.boxes.repairTitle", { name: agent.name }), message: t("vision.boxes.repairBody"), confirmLabel: t("vision.boxes.newCode") });
  if (!answer) return;
  try {
    repairing.value = { agent, pairing: await newPairing(companyId.value, agent.id) };
    refresh();
  } catch {
    // Shown by the HTTP layer.
  }
}

async function remove(agent: Agent): Promise<void> {
  const answer = await confirm({ title: t("vision.boxes.removeTitle", { name: agent.name }), message: t("vision.boxes.removeBody"), confirmLabel: t("vision.boxes.remove"), tone: "danger" });
  if (!answer) return;
  try {
    await deleteAgent(companyId.value, agent.id);
    toast.success(t("vision.boxes.removed", { name: agent.name }));
    refresh();
  } catch {
    // Shown by the HTTP layer.
  }
}

const groups = computed(() => {
  const list = cameras.data.value ?? [];
  const branches = company.current?.branches ?? [];
  return branches
    .map((branch) => ({
      branch,
      cameras: list
        .filter((camera: Camera) => camera.branch.id === branch.id)
        .sort((a, b) => Number(b.enabled) - Number(a.enabled) || ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role) || a.name.localeCompare(b.name)),
    }))
    .filter((group) => group.cameras.length);
});

function done(): void {
  document.getElementById("koz-cameras")?.scrollIntoView({ behavior: "smooth", block: "start" });
}
</script>

<template>
  <div class="flex flex-col gap-6">
    <PageHeader :title="t('vision.cameras.title')" :description="t('vision.cameras.description')" class="!mb-0">
      <template #actions>
        <UiButton variant="primary" :icon="Plus" @click="pair = true">{{ t("vision.boxes.add") }}</UiButton>
      </template>
    </PageHeader>

    <section :aria-label="t('vision.boxes.section')" class="flex flex-col gap-3">
      <h2 class="px-1 text-base font-semibold text-fg">{{ t("vision.boxes.section") }}</h2>
      <div v-if="pairing.isPending.value" class="grid gap-3 md:grid-cols-2 xl:grid-cols-3"><SkeletonBlock v-for="n in 2" :key="n" height="112px" radius="12px" /></div>
      <ErrorState v-else-if="pairing.isError.value" class="ui-card" :error="pairing.error.value" :retry="() => pairing.refetch()" />
      <EmptyState v-else-if="!agents.length" class="ui-card py-10" :icon="Cctv" :title="t('vision.boxes.emptyTitle')" :description="t('vision.boxes.emptyBody')">
        <UiButton variant="primary" :icon="Plus" @click="pair = true">{{ t("vision.pitch.cta") }}</UiButton>
      </EmptyState>
      <div v-else class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <BoxCard v-for="agent in agents" :key="agent.id" :agent="agent" @repair="repair" @remove="remove" />
      </div>
    </section>

    <section id="koz-cameras" :aria-label="t('vision.cameras.section')" class="flex scroll-mt-20 flex-col gap-3">
      <h2 class="px-1 text-base font-semibold text-fg">{{ t("vision.cameras.section") }}</h2>
      <div v-if="cameras.isPending.value" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3"><SkeletonBlock v-for="n in 3" :key="n" height="330px" radius="12px" /></div>
      <ErrorState v-else-if="cameras.isError.value" class="ui-card" :error="cameras.error.value" :retry="() => cameras.refetch()" />
      <EmptyState v-else-if="!groups.length" class="ui-card py-10" :icon="Cctv" :title="t('vision.cameras.emptyTitle')" :description="t('vision.cameras.emptyBody')" tone="neutral" />
      <template v-else>
        <div v-for="group in groups" :key="group.branch.id" class="flex flex-col gap-3">
          <h3 v-if="groups.length > 1" class="px-1 text-sm font-semibold text-muted">{{ group.branch.name }}</h3>
          <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <CameraCard v-for="camera in group.cameras" :key="camera.id" :camera="camera" :registers="registers.data.value ?? null" />
          </div>
        </div>
      </template>
    </section>

    <PairDialog v-model:open="pair" @done="done" />
    <PairDialog v-model:open="repairOpen" :agent="repairing?.agent ?? null" :pairing="repairing?.pairing ?? null" />
  </div>
</template>
