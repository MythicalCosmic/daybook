<script setup lang="ts">
/**
 * Pairing a Ko‘z box (docs/KOZ.md §5.1, §6.8): a name and a branch, then the code, shown once,
 * big, with its 15-minute countdown and the command to paste on the pharmacy's PC; the page follows
 * the box (every 2 s) until it is paired, then celebrates as its cameras arrive one by one. A new
 * code for an existing box opens straight on the code.
 */
import { Check, Copy, Cpu, RefreshCw, Sparkles, Terminal } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { unshownFieldError } from "@/api/http";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { createAgent, newPairing, useAgents, useCameras, useRefresh } from "../api";
import { useSecondClock } from "../lib/clock";
import { formatClock } from "../lib/tracks";
import type { Agent, Pairing } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{
  /** A box that needs a new code (re-pairing); none for a new box. */
  agent?: Agent | null;
  /** Its new pairing, already asked for. */
  pairing?: Pairing | null;
}>();
const emit = defineEmits<{ done: [] }>();

const { t } = useI18n();
const company = useCompanyStore();
const companyId = useCompanyId();
const clock = useSecondClock();
const refresh = useRefresh();

const step = ref<"form" | "code" | "paired">("form");
const name = ref("");
const branchId = ref<number | null>(null);
const errors = ref<Record<string, string>>({});
const failure = ref<string | null>(null);
const busy = ref(false);
const box = ref<Agent | null>(null);
const code = ref<Pairing | null>(null);
const copied = ref<"code" | "command" | null>(null);

const branches = computed(() => company.current?.branches ?? []);
const agents = useAgents(computed(() => open.value && step.value !== "form"), computed(() => open.value));
const cameras = useCameras(null, computed(() => step.value === "paired"));
const arrived = computed(() => (cameras.data.value ?? []).filter((camera) => camera.agent_id === box.value?.id));

/** The person typed a name or picked a branch: the defaults no longer move. */
const touched = ref(false);
watch(
  open,
  (value) => {
    if (!value) return;
    touched.value = false;
    start();
  },
  { immediate: true },
);
// The boxes arrive after the dialog opened from the URL: pick the first free branch then.
watch(
  () => agents.data.value,
  () => {
    if (open.value && step.value === "form" && !touched.value) start();
  },
);

function start(): void {
  errors.value = {};
  failure.value = null;
  copied.value = null;
  if (props.agent && props.pairing) {
    box.value = props.agent;
    code.value = props.pairing;
    step.value = "code";
    return;
  }
  box.value = null;
  code.value = null;
  step.value = "form";
  const taken = new Set((agents.data.value ?? []).map((a) => a.branch.id));
  const free = branches.value.find((b) => !taken.has(b.id)) ?? branches.value[0];
  branchId.value = free?.id ?? null;
  name.value = free ? t("vision.pair.defaultName", { branch: free.name }) : "";
}

// The box paired: on to the celebration, its cameras arriving.
watch(
  () => (agents.data.value ?? []).find((a) => a.id === box.value?.id),
  (current) => {
    if (step.value === "code" && current?.paired) {
      box.value = current;
      step.value = "paired";
      refresh();
    }
  },
);

const total = 15 * 60;
const left = computed(() => (code.value ? Math.max(0, Math.round((new Date(code.value.expires_at).getTime() - clock.value) / 1000)) : 0));
const expired = computed(() => step.value === "code" && !!code.value && left.value <= 0);

async function submit(): Promise<void> {
  errors.value = {};
  failure.value = null;
  if (!name.value.trim()) errors.value.name = t("common.form.required");
  if (!branchId.value) errors.value.branch_id = t("common.form.required");
  if (Object.keys(errors.value).length) return;
  busy.value = true;
  try {
    const created = await createAgent(companyId.value, { name: name.value.trim(), branch_id: branchId.value! });
    box.value = created.agent;
    code.value = created.pairing;
    step.value = "code";
    refresh();
  } catch (error) {
    const fields = (error as { fieldErrors?: Record<string, string[]> }).fieldErrors ?? {};
    for (const [key, messages] of Object.entries(fields)) if (messages[0]) errors.value[key] = messages[0];
    failure.value = unshownFieldError(error, ["name", "branch_id"]);
  } finally {
    busy.value = false;
  }
}

async function renew(): Promise<void> {
  if (!box.value) return;
  busy.value = true;
  try {
    code.value = await newPairing(companyId.value, box.value.id);
  } catch {
    // The HTTP layer said why.
  } finally {
    busy.value = false;
  }
}

async function copy(what: "code" | "command"): Promise<void> {
  const text = what === "code" ? code.value?.code : code.value?.command;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    copied.value = what;
    setTimeout(() => copied.value === what && (copied.value = null), 1800);
  } catch {
    // Clipboard blocked: the text is selectable.
  }
}

function finish(): void {
  open.value = false;
  emit("done");
}

const steps = computed(() => [
  { title: t("vision.pair.step1.title"), body: t("vision.pair.step1.body") },
  { title: t("vision.pair.step2.title"), body: t("vision.pair.step2.body") },
  { title: t("vision.pair.step3.title"), body: t("vision.pair.step3.body") },
]);
const dialogTitle = computed(() => (step.value === "paired" && box.value ? t("vision.pair.paired", { name: box.value.name }) : t("vision.pair.title")));
</script>

<template>
  <UiDialog v-model:open="open" :title="dialogTitle" :description="step === 'form' ? t('vision.pair.description') : undefined" size="lg">
    <!-- 1. Name and branch. -->
    <form v-if="step === 'form'" id="koz-pair" class="flex flex-col gap-4" novalidate @submit.prevent="submit">
      <FormField :label="t('vision.pair.name')" :error="errors.name" required>
        <TextInput v-model="name" :placeholder="t('vision.pair.namePlaceholder')" :invalid="!!errors.name" autofocus @input="touched = true" />
      </FormField>
      <FormField :label="t('vision.pair.branch')" :error="errors.branch_id" required>
        <SelectBox v-model="branchId" :options="branches.map((b) => ({ value: b.id, label: b.name }))" :invalid="!!errors.branch_id" @update:model-value="touched = true" />
      </FormField>
      <InlineAlert v-if="failure" tone="danger" size="sm" :description="failure" />
    </form>

    <!-- 2. The code and the command, the box awaited. -->
    <div v-else-if="step === 'code' && code" class="flex flex-col gap-5" data-pair="code">
      <div class="-mt-1 flex flex-wrap items-center justify-between gap-2">
        <p class="text-sm font-semibold text-fg">{{ t("vision.pair.codeTitle") }}</p>
        <span v-if="box" class="rounded-full bg-surface-2 px-2.5 py-0.5 text-xs font-medium text-muted dark:bg-surface-3">{{ box.name }} · {{ box.branch.name }}</span>
      </div>
      <div class="koz-code relative overflow-hidden rounded-[16px] p-5 text-center">
        <p class="text-xs font-semibold uppercase tracking-[0.12em] text-muted">{{ t("vision.pair.codeLabel") }}</p>
        <p :class="['koz-code-text mt-2 select-all font-mono font-bold text-fg', expired && 'line-through opacity-40']" data-code>{{ code.code }}</p>
        <div class="mt-3 flex flex-wrap items-center justify-center gap-3">
          <span class="inline-flex items-center gap-2 text-sm text-muted">
            <ProgressRing :value="left" :max="total" :size="22" :stroke="3" :tone="left < 120 ? 'warning' : 'primary'" />
            <span class="tabular-nums">{{ expired ? t("vision.pair.expired") : t("vision.pair.expires", { time: formatClock(left) }) }}</span>
          </span>
          <UiButton v-if="!expired" size="sm" variant="secondary" :icon="copied === 'code' ? Check : Copy" @click="copy('code')">{{ copied === "code" ? t("common.copied") : t("common.copy") }}</UiButton>
          <UiButton v-else size="sm" variant="primary" :icon="RefreshCw" :loading="busy" @click="renew">{{ t("vision.pair.newCode") }}</UiButton>
        </div>
      </div>

      <div>
        <p class="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted"><Terminal :size="13" />{{ t("vision.pair.command") }}</p>
        <div class="flex items-center gap-2 rounded-[10px] border border-line bg-[#171411] py-1.5 pl-3 pr-1.5 text-[#f3ece1]">
          <code class="min-w-0 flex-1 overflow-x-auto whitespace-nowrap py-1 font-mono text-[13px]">{{ code.command }}</code>
          <button type="button" class="pressable grid size-8 shrink-0 place-items-center rounded-[7px] text-white/70 hover:bg-white/10 hover:text-white" :aria-label="copied === 'command' ? t('common.copied') : t('common.copy')" @click="copy('command')">
            <Check v-if="copied === 'command'" :size="15" class="text-[#7fd6aa]" />
            <Copy v-else :size="15" />
          </button>
        </div>
      </div>

      <ol class="flex flex-col gap-3">
        <li v-for="(item, index) in steps" :key="item.title" class="flex gap-3">
          <span :class="['grid size-7 shrink-0 place-items-center rounded-full text-xs font-bold', index === 2 ? 'koz-wait-step bg-accent-soft text-accent-fg' : 'bg-surface-2 text-muted dark:bg-surface-3']">{{ index + 1 }}</span>
          <span class="min-w-0 pt-0.5">
            <span class="block text-sm font-semibold text-fg">{{ item.title }}</span>
            <span class="block text-sm text-muted">{{ item.body }}</span>
          </span>
        </li>
      </ol>
      <p v-if="!expired" class="flex items-center justify-center gap-2.5 rounded-[12px] bg-surface-2 px-4 py-3 text-sm font-medium text-fg dark:bg-surface-3" aria-live="polite">
        <span class="koz-dots" aria-hidden="true"><span /><span /><span /></span>{{ t("vision.pair.waiting") }}
      </p>
    </div>

    <!-- 3. Paired: the moment, and the cameras arriving. -->
    <div v-else-if="step === 'paired' && box" class="flex flex-col items-center gap-5 pb-1 text-center" data-pair="paired">
      <div class="koz-success relative grid size-20 place-items-center">
        <span class="koz-success-ring absolute inset-0 rounded-full" />
        <span class="relative grid size-16 place-items-center rounded-full bg-success text-white"><Check :size="34" stroke-width="2.5" /></span>
        <Sparkles :size="18" class="koz-spark absolute -right-1 top-0 text-warning" />
      </div>
      <div>
        <p class="text-sm text-muted">{{ t("vision.pair.pairedBody") }}</p>
        <p v-if="box.host" class="mt-2 inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-3 py-1 text-xs font-medium text-muted dark:bg-surface-3"><Cpu :size="13" />{{ box.host.hostname }} · {{ box.host.os }}</p>
      </div>
      <div class="w-full text-left">
        <p class="mb-2 text-xs font-semibold text-muted">{{ t("vision.pair.found", { n: arrived.length }, arrived.length) }}</p>
        <TransitionGroup tag="ul" name="koz-arrive" class="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <li v-for="camera in arrived" :key="camera.id" class="overflow-hidden rounded-[10px] border border-line bg-surface">
            <img v-if="camera.snapshot_url" :src="camera.snapshot_url" alt="" class="aspect-video w-full object-cover" />
            <span v-else class="block aspect-video bg-surface-2" />
            <span class="block truncate px-2 py-1.5 text-xs font-semibold text-fg">{{ camera.name }}</span>
          </li>
        </TransitionGroup>
      </div>
    </div>

    <template #footer>
      <template v-if="step === 'form'">
        <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" type="submit" form="koz-pair" :loading="busy">{{ t("vision.pair.create") }}</UiButton>
      </template>
      <UiButton v-else-if="step === 'code'" variant="ghost" @click="open = false">{{ t("common.close") }}</UiButton>
      <UiButton v-else variant="primary" @click="finish">{{ t("vision.pair.done") }}</UiButton>
    </template>
  </UiDialog>
</template>

<style scoped>
.koz-code {
  background:
    radial-gradient(90% 120% at 50% 0%, color-mix(in srgb, var(--c-primary) 10%, transparent), transparent 70%),
    var(--c-surface-2);
  border: 1px solid var(--c-border);
}
.koz-code-text {
  font-size: clamp(1.6rem, 7vw, 2.6rem);
  letter-spacing: 0.08em;
  line-height: 1.1;
}
.koz-dots {
  display: inline-flex;
  gap: 4px;
}
.koz-dots span {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: var(--c-primary);
  animation: koz-dot 1.2s ease-in-out infinite;
}
.koz-dots span:nth-child(2) {
  animation-delay: 0.15s;
}
.koz-dots span:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes koz-dot {
  0%,
  100% {
    opacity: 0.3;
    transform: translateY(0);
  }
  40% {
    opacity: 1;
    transform: translateY(-3px);
  }
}
.koz-wait-step {
  box-shadow: 0 0 0 0 color-mix(in srgb, var(--c-primary) 40%, transparent);
  animation: koz-step 1.8s ease-out infinite;
}
@keyframes koz-step {
  70% {
    box-shadow: 0 0 0 7px color-mix(in srgb, var(--c-primary) 0%, transparent);
  }
}
.koz-success span:last-of-type,
.koz-success > span:nth-child(2) {
  animation: koz-pop 0.5s var(--ease-out) both;
}
.koz-success-ring {
  background: color-mix(in srgb, var(--c-success) 30%, transparent);
  animation: koz-ring 1.2s var(--ease-out) both;
}
.koz-spark {
  animation: koz-pop 0.6s 0.25s var(--ease-out) both;
}
@keyframes koz-pop {
  from {
    transform: scale(0.4);
    opacity: 0;
  }
}
@keyframes koz-ring {
  from {
    transform: scale(0.6);
    opacity: 0.9;
  }
  to {
    transform: scale(1.35);
    opacity: 0;
  }
}
.koz-arrive-enter-active {
  transition:
    opacity 0.4s var(--ease-out),
    transform 0.5s var(--ease-out);
}
.koz-arrive-enter-from {
  opacity: 0;
  transform: translateY(10px) scale(0.96);
}
:root[data-motion="reduced"] .koz-dots span,
:root[data-motion="reduced"] .koz-wait-step,
:root[data-motion="reduced"] .koz-success-ring,
:root[data-motion="reduced"] .koz-success > span,
:root[data-motion="reduced"] .koz-spark {
  animation: none;
}
</style>
