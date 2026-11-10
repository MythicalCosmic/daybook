<script setup lang="ts">
/**
 * "Get today's scans now". While a terminal uploads its old history, today's scans wait behind
 * it; the catch-up helper (deploy/faceid/catchup.py, downloaded with this terminal's address on
 * the server filled in) runs on a computer in the terminal's network and sends them at once, and
 * stops by itself when the terminal catches up. Why, the download, the command to run with a copy
 * button (Windows' too) and that it stops. The parent shows it to people who manage terminals
 * only. `collapsible` (the terminal's card) folds it under one line; the wizard shows it open.
 */
import { Check, ChevronDown, Copy, Download, SquareTerminal, Zap } from "@lucide/vue";
import { computed, ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useCompanyId } from "@/stores/company";

import { downloadCatchup } from "../api";
import { catchupCommand } from "../lib";

const props = withDefaults(defineProps<{ deviceId: number; ip?: string | null; collapsible?: boolean }>(), { ip: null, collapsible: false });

const { t } = useI18n();
const companyId = useCompanyId();
const panelId = useId();
const open = ref(!props.collapsible);
const downloading = ref(false);
const copied = ref(false);

const address = computed(() => props.ip?.trim() || t("faceid.catchup.address"));
const command = computed(() => catchupCommand(address.value));
const windows = computed(() => catchupCommand(address.value, "windows"));

async function download(): Promise<void> {
  downloading.value = true;
  try {
    await downloadCatchup(companyId.value, props.deviceId);
  } catch {
    // The HTTP client toasts the reason.
  } finally {
    downloading.value = false;
  }
}

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(command.value);
    copied.value = true;
    setTimeout(() => (copied.value = false), 1500);
  } catch {
    toast.error(t("faceid.wizard.copyFailed"));
  }
}
</script>

<template>
  <section :class="['text-left', !collapsible && 'rounded-[12px] border border-line bg-surface p-4']" :aria-label="t('faceid.catchup.title')">
    <button
      v-if="collapsible"
      type="button"
      class="pressable inline-flex items-start gap-1.5 rounded-[6px] text-left text-xs font-semibold text-current hover:underline focus-visible:underline"
      :aria-expanded="open"
      :aria-controls="panelId"
      @click="open = !open"
    >
      <Zap :size="13" class="mt-px shrink-0" aria-hidden="true" />
      <span>{{ t("faceid.catchup.title") }}</span>
      <ChevronDown :size="13" :class="['mt-px shrink-0 transition-transform duration-200', open && 'rotate-180']" aria-hidden="true" />
    </button>
    <header v-else class="flex items-center gap-2.5">
      <span class="grid size-7 shrink-0 place-items-center rounded-full bg-accent-soft text-accent-fg" aria-hidden="true"><Zap :size="14" /></span>
      <h3 class="text-sm font-semibold text-fg">{{ t("faceid.catchup.title") }}</h3>
    </header>

    <div v-show="open" :id="panelId" :class="['flex flex-col gap-3', collapsible ? 'mt-2 rounded-[10px] bg-surface p-3 text-fg' : 'mt-3']">
      <p class="text-sm text-muted">{{ t("faceid.catchup.why") }}</p>
      <div>
        <UiButton size="sm" :icon="Download" :loading="downloading" data-testid="catchup-download" @click="download">{{ t("faceid.catchup.download") }}</UiButton>
      </div>
      <div class="flex items-start gap-2 rounded-[9px] border border-line bg-surface-2/70 py-1.5 pl-2.5 pr-1.5">
        <SquareTerminal :size="15" class="mt-[5px] shrink-0 text-subtle" aria-hidden="true" />
        <code class="min-w-0 flex-1 break-words py-1 font-mono text-[12.5px] leading-5 text-fg" :aria-label="t('faceid.catchup.command')" data-testid="catchup-command">{{ command }}</code>
        <button
          type="button"
          class="pressable grid size-7 shrink-0 place-items-center rounded-button text-muted hover:bg-highlight hover:text-fg"
          :aria-label="copied ? t('faceid.catchup.copied') : t('faceid.catchup.copy')"
          :title="t('faceid.catchup.copy')"
          data-testid="catchup-copy"
          @click="copy"
        >
          <Check v-if="copied" :size="15" class="text-success" />
          <Copy v-else :size="15" />
        </button>
      </div>
      <p class="-mt-1 text-xs text-subtle">{{ t("faceid.catchup.windows", { command: windows }) }}</p>
      <p class="text-xs font-medium text-muted">{{ t("faceid.catchup.stops") }}</p>
    </div>
  </section>
</template>
