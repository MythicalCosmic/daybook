<script setup lang="ts">
/**
 * A camera in Cameras and boxes (docs/KOZ.md §4, §6.4): its latest picture with the zones drawn
 * on it (a new picture on request), its name (renamed in place), what it is for, whether Ko‘z
 * analyses it, the till a counter camera watches, and what its zones still lack before it counts.
 * Every change saves at once and shows at once; a refusal puts it back.
 */
import { Check, ImageOff, PenLine, RefreshCw, Shapes, TriangleAlert, WifiOff, X } from "@lucide/vue";
import { computed, nextTick, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import IconButton from "@/components/IconButton.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiBadge from "@/components/UiBadge.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { requestSnapshot, useRefresh, useUpdateCamera } from "../api";
import { missingZones } from "../lib/look";
import { CAMERA_ROLES, type Camera, type CameraPatch, type CameraRole } from "../types";
import ZoneLayer from "./ZoneLayer.vue";

const props = defineProps<{ camera: Camera; registers: Array<{ id: number; name: string; branch: { id: number } }> | null }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const companyId = useCompanyId();
const update = useUpdateCamera();
const refresh = useRefresh();

const isNew = computed(() => props.camera.role === "other" && !props.camera.enabled && !props.camera.zones.length);
const missing = computed(() => (props.camera.enabled ? missingZones(props.camera.role, props.camera.zones.map((zone) => zone.kind)) : []));
const roles = computed(() => CAMERA_ROLES.map((value) => ({ value, label: t(`vision.role.${value}`), description: t(`vision.roleHint.${value}`) })));
const tills = computed(() => [
  { value: 0, label: t("vision.cameras.noRegister") },
  ...(props.registers ?? []).filter((r) => r.branch.id === props.camera.branch.id).map((r) => ({ value: r.id, label: r.name })),
]);
const source = computed(() => {
  const s = props.camera.source;
  return s === "nvr" && props.camera.channel !== null ? t("vision.cameras.source.nvr", { n: props.camera.channel }) : t(`vision.cameras.source.${s}`);
});
const zonesTo = computed(() => `/c/${company.currentId}/vision/cameras/${props.camera.id}/zones`);

async function save(patch: CameraPatch, message?: string): Promise<void> {
  try {
    await update.mutateAsync({ id: props.camera.id, patch });
    if (message) toast.success(message);
  } catch {
    // Shown by the HTTP layer; the card went back.
  }
}

function setEnabled(on: boolean): void {
  void save({ enabled: on }, on ? t("vision.cameras.analyseOn", { name: props.camera.name }) : t("vision.cameras.analyseOff", { name: props.camera.name }));
}

// Renaming in place: Enter saves, Esc puts the name back.
const renaming = ref(false);
const draft = ref("");
const input = ref<InstanceType<typeof TextInput> | null>(null);
async function startRename(): Promise<void> {
  draft.value = props.camera.name;
  renaming.value = true;
  await nextTick();
  input.value?.select();
}
function finishRename(keep: boolean): void {
  const name = draft.value.trim();
  renaming.value = false;
  if (keep && name && name !== props.camera.name) void save({ name });
}

const refreshing = ref(false);
async function newSnapshot(): Promise<void> {
  refreshing.value = true;
  try {
    await requestSnapshot(companyId.value, props.camera.id);
    toast.info(t("vision.cameras.refreshing"));
    setTimeout(() => {
      refresh();
      refreshing.value = false;
    }, 3200);
  } catch {
    refreshing.value = false;
  }
}
</script>

<template>
  <article class="ui-card flex min-w-0 flex-col overflow-hidden" :data-camera="camera.id">
    <div class="relative aspect-video overflow-hidden bg-[#0f0d0b]">
      <img v-if="camera.snapshot_url" :src="camera.snapshot_url" :alt="camera.name" class="size-full object-cover" loading="lazy" />
      <div v-else class="grid size-full place-items-center text-sm text-white/60"><span class="flex flex-col items-center gap-2"><ImageOff :size="20" />{{ t("vision.cameras.noSnapshot") }}</span></div>
      <ZoneLayer v-if="camera.snapshot_url && camera.zones.length" :zones="camera.zones" :aspect="camera.w && camera.h ? camera.w / camera.h : 16 / 9" />
      <div class="absolute inset-x-0 top-0 flex items-start justify-between gap-2 p-2.5">
        <span class="koz-chip inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold text-white">{{ t(`vision.role.${camera.role}`) }}</span>
        <span class="flex items-center gap-1.5">
          <UiBadge v-if="isNew" tone="primary" variant="solid">{{ t("vision.cameras.new") }}</UiBadge>
          <span v-if="!camera.online" class="koz-chip inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold text-[#ffb3a3]"><WifiOff :size="12" />{{ t("vision.camera.offline") }}</span>
        </span>
      </div>
      <div class="absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 p-2.5">
        <span v-if="camera.snapshot_at" class="koz-chip rounded-full px-2.5 py-1 text-[11px] font-medium text-white/80">{{ t("vision.cameras.snapshot", { time: fmt.relative(camera.snapshot_at) }) }}</span>
        <button type="button" class="koz-chip pressable inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold text-white hover:bg-black/70 disabled:opacity-60" :disabled="refreshing || !camera.online" @click="newSnapshot">
          <RefreshCw :size="12" :class="refreshing && 'koz-turn'" />{{ t("vision.cameras.refresh") }}
        </button>
      </div>
    </div>

    <div class="flex flex-1 flex-col gap-3 p-4">
      <div class="flex items-start gap-2">
        <div class="min-w-0 flex-1">
          <div v-if="renaming" class="flex items-center gap-1">
            <TextInput
              ref="input"
              v-model="draft"
              size="sm"
              class="min-w-0 flex-1"
              :aria-label="t('vision.cameras.name')"
              :maxlength="64"
              @keydown.enter.prevent="finishRename(true)"
              @keydown.esc.prevent="finishRename(false)"
              @blur="finishRename(true)"
            />
            <IconButton :icon="Check" :label="t('common.save')" size="sm" @mousedown.prevent @click="finishRename(true)" />
            <IconButton :icon="X" :label="t('common.cancel')" size="sm" @mousedown.prevent @click="finishRename(false)" />
          </div>
          <h3 v-else class="flex min-w-0 items-center gap-1.5">
            <span class="truncate text-base font-semibold text-fg">{{ camera.name }}</span>
            <IconButton :icon="PenLine" :label="t('vision.cameras.rename')" size="sm" @click="startRename" />
          </h3>
          <p class="truncate text-xs text-muted">{{ source }}<template v-if="camera.w && camera.h"> · {{ camera.w }}×{{ camera.h }}</template><template v-if="!camera.online && camera.last_seen_at"> · {{ t("vision.cameras.offlineSince", { time: fmt.relative(camera.last_seen_at) }) }}</template></p>
        </div>
        <ToggleSwitch :model-value="camera.enabled" :label="t('vision.cameras.analyse')" size="sm" @update:model-value="setEnabled" />
      </div>

      <div class="grid gap-2" :class="camera.role === 'counter' && registers ? 'sm:grid-cols-2' : ''">
        <div class="min-w-0">
          <p class="mb-1 text-xs font-medium text-muted">{{ t("vision.cameras.role") }}</p>
          <SelectBox :model-value="camera.role" size="sm" :options="roles" @update:model-value="(role: CameraRole | null) => role && save({ role })" />
        </div>
        <div v-if="camera.role === 'counter' && registers" class="min-w-0">
          <p class="mb-1 text-xs font-medium text-muted">{{ t("vision.cameras.register") }}</p>
          <SelectBox :model-value="camera.register?.id ?? 0" size="sm" :options="tills" @update:model-value="(id: number | null) => save({ register_id: id || null })" />
          <p class="mt-1 text-xs text-subtle">{{ t("vision.cameras.registerHint") }}</p>
        </div>
      </div>

      <div class="mt-auto flex flex-wrap items-center gap-2 border-t border-line pt-3">
        <span class="inline-flex min-w-0 flex-1 items-center gap-1.5 text-sm">
          <Shapes :size="15" class="shrink-0 text-subtle" />
          <span class="truncate text-fg">{{ camera.zones.length ? t("vision.cameras.zones", { n: camera.zones.length }, camera.zones.length) : t("vision.cameras.noZones") }}</span>
        </span>
        <RouterLink :to="zonesTo" class="pressable inline-flex h-8 items-center gap-1.5 rounded-button bg-accent-soft px-3 text-sm font-semibold text-accent-fg hover:brightness-95">{{ t("vision.cameras.editZones") }}</RouterLink>
        <p v-for="kind in missing" :key="kind" class="flex w-full items-center gap-1.5 text-xs font-medium text-warning"><TriangleAlert :size="13" class="shrink-0" />{{ t(`vision.cameras.needs.${kind}`) }}</p>
      </div>
    </div>
  </article>
</template>

<style scoped>
.koz-chip {
  background: rgb(14 11 9 / 0.6);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
}
.koz-turn {
  animation: koz-turn 1s linear infinite;
}
@keyframes koz-turn {
  to {
    transform: rotate(360deg);
  }
}
:root[data-motion="reduced"] .koz-turn {
  animation: none;
}
</style>
