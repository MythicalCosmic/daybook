<script setup lang="ts">
/**
 * The "Get started" progress pill at the top of the sidebar (`shell.nav.top`, plan §6.1): shown
 * until the checklist is finished or dismissed. On the collapsed rail it is a progress ring.
 */
import { Rocket } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import ProgressBar from "@/components/ProgressBar.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { useCompanyStore } from "@/stores/company";

import { useSetup } from "../api";

const props = withDefaults(defineProps<{ context?: { rail?: boolean } }>(), { context: () => ({}) });

const { t } = useI18n();
const route = useRoute();
const company = useCompanyStore();
const wanted = computed(() => !!company.current && !company.current.setup_completed);
const setup = useSetup(wanted);

const data = computed(() => setup.data.value);
const visible = computed(() => wanted.value && !!data.value && data.value.total > 0 && data.value.done < data.value.total && !data.value.dismissed);
const to = computed(() => `/c/${company.currentId}/get-started`);
const active = computed(() => route.path === to.value);
const label = computed(() => (data.value ? t("setup.pill", { done: data.value.done, total: data.value.total }) : ""));
</script>

<template>
  <!-- Own spacing: the slot host can't pass its padding to a component (see the hand-off). -->
  <div v-if="visible && data" :class="props.context.rail ? 'flex justify-center px-2 pt-2' : 'px-3 pt-2'">
    <UiTooltip v-if="props.context.rail" :content="label" side="right">
      <RouterLink :to="to" class="pressable grid size-10 place-items-center rounded-[10px] hover:bg-[var(--c-nav-hover)]" :aria-label="label">
        <span class="relative grid place-items-center">
          <ProgressRing :value="data.done" :max="data.total" :size="30" :stroke="3" />
          <Rocket :size="13" class="absolute text-primary" />
        </span>
      </RouterLink>
    </UiTooltip>
    <RouterLink
      v-else
      :to="to"
      :class="[
        'pressable group flex flex-col gap-2 rounded-[12px] border px-3 py-2.5 transition-colors',
        active ? 'border-[color-mix(in_srgb,var(--c-primary)_40%,var(--c-border))] bg-surface' : 'border-line bg-surface hover:border-line-strong',
      ]"
    >
      <span class="flex items-center gap-2">
        <span class="grid size-6 shrink-0 place-items-center rounded-[7px] bg-accent-soft text-accent-fg"><Rocket :size="14" /></span>
        <span class="min-w-0 flex-1 truncate text-sm font-semibold text-fg">{{ t("setup.title") }}</span>
        <span class="text-xs font-semibold tabular-nums text-muted">{{ data.done }}/{{ data.total }}</span>
      </span>
      <ProgressBar :value="data.done" :max="data.total" size="sm" />
    </RouterLink>
  </div>
</template>
