<script setup lang="ts">
/**
 * Adding a terminal in three steps. 1: its name, branch and how it counts scans. 2: the exact
 * values for the terminal's own web page (a MinMoe DS-K1T341AMF, firmware V3.2.x: Configuration ›
 * Network › Advanced Settings › HTTP Listening), each with a copy button, drawn the way that page
 * looks. 3: "Scan a face at the terminal now…", which turns into "Connected" the moment its first
 * event arrives (the setup values are polled). "Simulate a face" shows the whole flow before the
 * terminal is set up; it never counts. Opened for an existing terminal, it starts at step 2.
 */
import { Check, CircleCheck, Copy, FlaskConical, ScanFace } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import FormField from "@/components/FormField.vue";
import RadioCards from "@/components/RadioCards.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import WizardSteps from "@/components/WizardSteps.vue";
import { useCompanyId } from "@/stores/company";

import { createDevice, simulate, useRefresh, useSetup } from "../api";
import type { Device, Direction } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ device?: Device | null }>(), { device: null });

const { t } = useI18n();
const companyId = useCompanyId();
const refresh = useRefresh();

type Step = "terminal" | "values" | "first";
const step = ref<Step>("terminal");
const deviceId = ref<number | null>(null);
const form = ref<{ name: string; branch: number | null; direction: Direction }>({ name: "", branch: null, direction: "toggle" });
const saving = ref(false);
const error = ref<string | null>(null);
const tested = ref(false);
const testing = ref(false);
const copied = ref<string | null>(null);

watch(
  open,
  (value) => {
    if (!value) return;
    error.value = null;
    tested.value = false;
    deviceId.value = props.device?.id ?? null;
    step.value = props.device ? "values" : "terminal";
    form.value = { name: props.device?.name ?? "", branch: props.device?.branch.id ?? null, direction: props.device?.direction ?? "toggle" };
  },
  { immediate: true },
);

const waiting = computed(() => open.value && step.value === "first");
const setup = useSetup(deviceId, waiting);
const connected = computed(() => !!setup.data.value?.last_event_at);
watch(connected, (value, before) => {
  if (value && !before && waiting.value) refresh();
});

const steps = computed(() => [
  { id: "terminal", label: t("faceid.wizard.step1") },
  { id: "values", label: t("faceid.wizard.step2") },
  { id: "first", label: t("faceid.wizard.step3") },
]);
const completed = computed(() => [...(deviceId.value ? ["terminal"] : []), ...(step.value === "first" ? ["values"] : []), ...(connected.value ? ["first"] : [])]);

const directions = computed(() =>
  (["toggle", "in", "out"] as const).map((value) => ({ value, label: t(`faceid.direction.${value}`), description: t(`faceid.direction.${value}Hint`) })),
);

async function create(): Promise<void> {
  if (!form.value.name.trim() || !form.value.branch) {
    error.value = t("faceid.wizard.needNameBranch");
    return;
  }
  saving.value = true;
  error.value = null;
  try {
    const made = await createDevice(companyId.value, { name: form.value.name.trim(), branch_id: form.value.branch, direction: form.value.direction });
    deviceId.value = made.id;
    step.value = "values";
    refresh();
  } catch {
    // The HTTP client toasts the reason.
  } finally {
    saving.value = false;
  }
}

async function copy(key: string, value: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value);
    copied.value = key;
    setTimeout(() => copied.value === key && (copied.value = null), 1500);
  } catch {
    toast.error(t("faceid.wizard.copyFailed"));
  }
}

async function test(): Promise<void> {
  if (!deviceId.value) return;
  testing.value = true;
  try {
    await simulate(companyId.value, deviceId.value);
    tested.value = true;
    refresh();
  } finally {
    testing.value = false;
  }
}

const fields = computed(() => {
  const values = setup.data.value;
  if (!values) return [];
  return [
    { key: "protocol", label: t("faceid.wizard.protocol"), value: values.recommended.toUpperCase(), note: t("faceid.wizard.protocolNote") },
    { key: "addressing", label: t("faceid.wizard.addressing"), value: values.addressing === "hostname" ? t("faceid.wizard.hostname") : t("faceid.wizard.ipaddress") },
    { key: "host", label: t("faceid.wizard.host"), value: values.host, copy: true },
    { key: "port", label: t("faceid.wizard.port"), value: String(values[values.recommended].port), copy: true },
    { key: "url", label: t("faceid.wizard.url"), value: values.path, copy: true, mono: true },
    { key: "heartbeat", label: t("faceid.wizard.heartbeat"), value: t("faceid.wizard.heartbeatValue", { n: values.heartbeat_minutes }) },
  ];
});
</script>

<template>
  <UiDialog v-model:open="open" size="lg" :title="device ? t('faceid.wizard.setupTitle', { name: device.name }) : t('faceid.wizard.title')" :description="t('faceid.wizard.description')">
    <div class="flex flex-col gap-5 pt-1">
      <WizardSteps v-model="step" :steps="steps" :completed="completed" :linear="!deviceId" />

      <!-- 1. The terminal -->
      <form v-if="step === 'terminal'" class="flex flex-col gap-4" @submit.prevent="create">
        <FormField :label="t('faceid.wizard.name')" required :hint="t('faceid.wizard.nameHint')">
          <TextInput v-model="form.name" :maxlength="80" :placeholder="t('faceid.wizard.namePlaceholder')" />
        </FormField>
        <FormField :label="t('faceid.wizard.branch')" required>
          <BranchPicker v-model="form.branch" />
        </FormField>
        <FormField :label="t('faceid.wizard.direction')">
          <RadioCards v-model="form.direction" :columns="3" :options="directions" />
        </FormField>
        <p v-if="error" class="text-sm text-danger">{{ error }}</p>
      </form>

      <!-- 2. What to type into the terminal -->
      <div v-else-if="step === 'values'" class="flex flex-col gap-4">
        <ol class="flex flex-col gap-1.5 text-sm text-fg">
          <li class="flex gap-2"><span class="faceid-num">1</span><span>{{ t("faceid.wizard.open") }}</span></li>
          <li class="flex gap-2"><span class="faceid-num">2</span><span>{{ t("faceid.wizard.go") }} <b class="font-semibold">{{ t("faceid.wizard.path") }}</b></span></li>
          <li class="flex gap-2"><span class="faceid-num">3</span><span>{{ t("faceid.wizard.fill") }}</span></li>
        </ol>

        <!-- The terminal's HTTP Listening page, drawn small: these fields, in this order. -->
        <figure class="overflow-hidden rounded-[12px] border border-line bg-surface-2/50" :aria-label="t('faceid.wizard.diagram')">
          <figcaption class="flex items-center gap-2 border-b border-line bg-surface px-3 py-2 text-xs text-muted">
            <span class="flex gap-1" aria-hidden="true"><span class="size-2 rounded-full bg-line" /><span class="size-2 rounded-full bg-line" /><span class="size-2 rounded-full bg-line" /></span>
            <span class="truncate">{{ t("faceid.wizard.pageTitle") }}</span>
          </figcaption>
          <div v-if="!fields.length" class="p-4 text-sm text-muted">{{ t("common.loading") }}</div>
          <dl v-else class="divide-y divide-line">
            <div v-for="field in fields" :key="field.key" class="grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)_auto] items-center gap-3 px-3 py-2.5 max-sm:grid-cols-[minmax(0,1fr)_auto]">
              <dt class="text-xs text-muted max-sm:col-span-2">{{ field.label }}</dt>
              <dd class="min-w-0">
                <span :class="['block truncate rounded-[8px] border border-line bg-surface px-2.5 py-1.5 text-sm text-fg', field.mono && 'font-mono text-[13px]']">{{ field.value }}</span>
                <span v-if="field.note" class="mt-1 block text-xs text-subtle">{{ field.note }}</span>
              </dd>
              <button
                v-if="field.copy"
                type="button"
                class="pressable grid size-8 place-items-center rounded-button text-muted hover:bg-highlight hover:text-fg"
                :aria-label="t('faceid.wizard.copy', { field: field.label })"
                @click="copy(field.key, field.value)"
              >
                <Check v-if="copied === field.key" :size="16" class="text-success" />
                <Copy v-else :size="16" />
              </button>
              <span v-else />
            </div>
          </dl>
        </figure>

        <p v-if="setup.data.value" class="rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm text-muted">
          {{ t("faceid.wizard.fallback", { port: setup.data.value.http.port }) }}
        </p>
        <p class="text-sm text-muted">{{ t("faceid.wizard.people") }}</p>
      </div>

      <!-- 3. The first scan -->
      <div v-else class="flex flex-col items-center gap-4 py-4 text-center">
        <Transition name="faceid-state" mode="out-in">
          <div v-if="connected" key="done" class="flex flex-col items-center gap-3">
            <span class="faceid-done grid size-20 place-items-center rounded-full bg-success-soft text-success"><CircleCheck :size="40" /></span>
            <p class="text-lg font-semibold text-fg">{{ t("faceid.wizard.connected") }}</p>
            <p class="max-w-sm text-sm text-muted">{{ t("faceid.wizard.connectedBody") }}</p>
          </div>
          <div v-else key="wait" class="flex flex-col items-center gap-3">
            <span class="faceid-wait relative grid size-20 place-items-center rounded-full bg-accent-soft text-accent-fg"><ScanFace :size="36" /></span>
            <p class="text-lg font-semibold text-fg">{{ t("faceid.wizard.waiting") }}</p>
            <p class="max-w-sm text-sm text-muted">{{ t("faceid.wizard.waitingBody") }}</p>
          </div>
        </Transition>
        <div v-if="tested && !connected" class="flex items-center gap-2 rounded-[10px] bg-info-soft px-3 py-2 text-sm text-info">
          <FlaskConical :size="15" aria-hidden="true" />
          <span>{{ t("faceid.wizard.tested") }}</span>
        </div>
      </div>
    </div>

    <template #footer>
      <UiButton v-if="step === 'first' && !connected" variant="ghost" :icon="FlaskConical" :loading="testing" @click="test">{{ t("faceid.wizard.simulate") }}</UiButton>
      <span class="flex-1" />
      <UiButton v-if="step === 'values'" variant="ghost" @click="open = false">{{ t("faceid.wizard.later") }}</UiButton>
      <UiButton v-if="step === 'terminal'" variant="primary" :loading="saving" @click="create">{{ t("faceid.wizard.next") }}</UiButton>
      <UiButton v-else-if="step === 'values'" variant="primary" @click="step = 'first'">{{ t("faceid.wizard.typedIn") }}</UiButton>
      <UiButton v-else variant="primary" @click="open = false">{{ connected ? t("faceid.wizard.done") : t("faceid.wizard.close") }}</UiButton>
    </template>
  </UiDialog>
</template>

<style scoped>
.faceid-num {
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  width: 1.375rem;
  height: 1.375rem;
  border-radius: 999px;
  background: var(--c-surface-2);
  color: var(--c-muted);
  font-size: 12px;
  font-weight: 600;
}
.faceid-wait::before,
.faceid-wait::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 999px;
  border: 2px solid color-mix(in srgb, var(--c-accent) 45%, transparent);
  animation: faceid-wave 2.6s var(--ease-out, ease-out) infinite;
}
.faceid-wait::after {
  animation-delay: 1.3s;
}
@keyframes faceid-wave {
  0% {
    transform: scale(1);
    opacity: 0.7;
  }
  100% {
    transform: scale(1.7);
    opacity: 0;
  }
}
.faceid-done {
  animation: faceid-pop 420ms var(--ease-out, ease-out);
}
@keyframes faceid-pop {
  0% {
    transform: scale(0.6);
    opacity: 0;
  }
  70% {
    transform: scale(1.08);
  }
  100% {
    transform: scale(1);
    opacity: 1;
  }
}
.faceid-state-enter-active,
.faceid-state-leave-active {
  transition: opacity 200ms var(--ease-out);
}
.faceid-state-enter-from,
.faceid-state-leave-to {
  opacity: 0;
}
@media (prefers-reduced-motion: reduce) {
  .faceid-wait::before,
  .faceid-wait::after,
  .faceid-done {
    animation: none;
  }
}
</style>
