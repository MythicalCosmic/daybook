<script setup lang="ts">
/**
 * Face ID › Terminals: the company's terminals (in the caller's branches) as cards with their
 * status, today's scans and setup; "Add a terminal" opens the three-step wizard (`?add=1` too, from
 * the command palette). A new code makes the old address stop at once, so it asks first.
 */
import { Plus, ScanFace, ShieldCheck } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { regenerate, updateDevice, useDevices, useRefresh } from "../api";
import DeviceCard from "../components/DeviceCard.vue";
import SetupWizard from "../components/SetupWizard.vue";
import type { Device } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const companyId = useCompanyId();
const confirm = useConfirm();
const refresh = useRefresh();

const devices = useDevices();
const skeleton = useDelayedPending(computed(() => devices.isPending.value));
const adding = useRouteState("add", rs.boolean(false));
const wizardOpen = ref(false);
const editing = ref<Device | null>(null);
const busy = ref<number | null>(null);
const canManage = computed(() => company.can("attendance.manage"));

watch(
  adding,
  (value) => {
    if (!value) return;
    editing.value = null;
    wizardOpen.value = true;
    adding.value = false;
  },
  { immediate: true },
);

function setup(device: Device): void {
  editing.value = device;
  wizardOpen.value = true;
}

async function newCode(device: Device): Promise<void> {
  await confirm({
    title: t("faceid.terminals.newCodeTitle", { name: device.name }),
    message: t("faceid.terminals.newCodeBody"),
    confirmLabel: t("faceid.terminals.newCode"),
    onConfirm: async () => {
      await regenerate(companyId.value, device.id);
      toast.success(t("faceid.terminals.newCodeDone"));
      refresh();
      setup(device);
    },
  });
}

async function toggle(device: Device): Promise<void> {
  if (device.enabled) {
    const answer = await confirm({ title: t("faceid.terminals.offTitle", { name: device.name }), message: t("faceid.terminals.offBody"), confirmLabel: t("faceid.terminals.switchOff") });
    if (!answer) return;
  }
  busy.value = device.id;
  try {
    await updateDevice(companyId.value, device.id, { enabled: !device.enabled });
    toast.success(device.enabled ? t("faceid.terminals.offDone") : t("faceid.terminals.onDone"));
    refresh();
  } finally {
    busy.value = null;
  }
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader :title="t('faceid.terminals.title')" :description="t('faceid.terminals.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="(editing = null), (wizardOpen = true)">{{ t("faceid.terminals.add") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="skeleton" class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <SkeletonBlock v-for="n in 3" :key="n" height="236px" radius="14px" />
    </div>
    <ErrorState v-else-if="devices.isError.value" :error="devices.error.value" :retry="() => devices.refetch()" />
    <div v-else-if="devices.data.value && !devices.data.value.length" class="ui-card">
      <EmptyState :icon="ScanFace" :title="t('faceid.terminals.emptyTitle')" :description="t('faceid.terminals.emptyBody')">
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="(editing = null), (wizardOpen = true)">{{ t("faceid.terminals.add") }}</UiButton>
      </EmptyState>
    </div>
    <div v-else class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <DeviceCard v-for="device in devices.data.value" :key="device.id" :device="device" :can-manage="canManage" :busy="busy === device.id" @setup="setup" @regenerate="newCode" @toggle="toggle" />
    </div>

    <p class="flex items-start gap-2 text-sm text-muted">
      <ShieldCheck :size="16" class="mt-0.5 shrink-0 text-subtle" aria-hidden="true" />
      <span>{{ t("faceid.privacy") }}</span>
    </p>

    <SetupWizard v-model:open="wizardOpen" :device="editing" />
  </div>
</template>
