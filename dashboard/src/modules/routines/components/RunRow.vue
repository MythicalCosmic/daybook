<script setup lang="ts">
/**
 * One person's run of a routine on a day: who, how it stands ("Done 08:50", "Waiting · done 09:20",
 * "Late · due 09:00", "To do · due 18:00"), the proof photo (opens the lightbox) or the report, and
 * Confirm / Send back when the run waits for the viewer's check.
 */
import { Check, FileText, RotateCcw } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import IconButton from "@/components/IconButton.vue";
import ProofThumb from "@/components/ProofThumb.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { RUN_LOOK, runText } from "../lib";
import type { RoutineRun } from "../types";

const props = withDefaults(defineProps<{ run: RoutineRun; title: string; busy?: boolean }>(), { busy: false });
const emit = defineEmits<{ confirm: [run: RoutineRun]; sendBack: [run: RoutineRun] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
// Confirm and send back are finger-sized on phones.
const { isPhone } = useBreakpoints();
const tap = computed(() => (isPhone.value ? "lg" : "sm"));
const look = computed(() => RUN_LOOK[props.run.state]);
const text = computed(() => runText(props.run, t, (iso) => fmt.instant(iso, "time")));
const tone = computed(
  () =>
    ({
      success: "text-success",
      warning: "text-warning",
      danger: "text-danger",
      neutral: "text-muted",
      info: "text-info",
      primary: "text-accent-fg",
    })[look.value.tone],
);
const caption = computed(() => `${props.run.member.name} · ${props.title}${props.run.completed_at ? ` · ${fmt.instant(props.run.completed_at, "short")}` : ""}`);
</script>

<template>
  <li
    :class="[
      'flex min-w-0 items-center gap-3 rounded-[10px] border bg-surface px-3 py-2.5 transition-colors',
      run.state === 'late' || run.state === 'missed' ? 'border-[color-mix(in_srgb,var(--c-danger)_35%,transparent)]' : 'border-line',
      run.state === 'cancelled' && 'opacity-60',
    ]"
    :data-run-state="run.state"
  >
    <UserAvatar :name="run.member.name" :src="run.member.photo_url" :size="32" />
    <div class="min-w-0 flex-1">
      <!-- The task itself (checklist, comments, timeline) opens in Tasks; Back returns here. -->
      <RouterLink :to="`/c/${company.currentId}/tasks?task=${run.id}&routines=1`" class="block truncate text-sm font-medium text-fg hover:underline" :title="t('routines.today.openTask', { name: run.member.name })">{{ run.member.name }}</RouterLink>
      <p :class="['mt-0.5 flex min-w-0 items-center gap-1 text-xs font-medium tabular-nums', tone]">
        <component :is="look.icon" :size="12" class="shrink-0" aria-hidden="true" />
        <span class="truncate max-sm:whitespace-normal" :title="text">{{ text }}</span>
      </p>
    </div>
    <ProofThumb
      v-if="run.proof_thumb"
      :src="run.proof_thumb"
      :images="[{ src: run.proof_photo ?? run.proof_thumb, caption }]"
      :alt="caption"
      size="sm"
      class="shrink-0"
    />
    <span v-else-if="run.proof_text" class="grid size-10 shrink-0 place-items-center rounded-[7px] bg-surface-2 text-subtle" :title="run.proof_text" :aria-label="run.proof_text">
      <FileText :size="16" aria-hidden="true" />
    </span>
    <div v-if="run.can_confirm" class="flex shrink-0 items-center gap-0.5">
      <IconButton :icon="Check" :label="t('routines.confirm.one')" :size="tap" variant="soft" :disabled="busy" @click="emit('confirm', run)" />
      <IconButton :icon="RotateCcw" :label="t('routines.confirm.sendBack')" :size="tap" :disabled="busy" @click="emit('sendBack', run)" />
    </div>
  </li>
</template>
