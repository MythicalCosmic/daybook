<script setup lang="ts">
/**
 * An applicant on the board (and in the phone list): who, when, their phone, the first answers,
 * whether they came by the QR code and sent a diploma photo; a hired one links to their profile.
 * The arrow moves them one stage on (it asks first where the bot would tell them something).
 */
import { ChevronRight, FileImage, QrCode, UserCheck } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UiTooltip from "@/components/UiTooltip.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useFormat } from "@/lib/useFormat";

import { formatPhone, highlights, nextStage } from "../lib";
import type { Answer, Applicant } from "../types";

const props = withDefaults(defineProps<{ applicant: Applicant; canAct?: boolean }>(), { canAct: true });
const emit = defineEmits<{ open: [applicant: Applicant]; advance: [applicant: Applicant] }>();

const { t } = useI18n();
const fmt = useFormat();

const shown = computed(() => highlights(props.applicant.answers));
const next = computed(() => nextStage(props.applicant.stage));

function answer(row: Answer): string {
  if (row.kind === "yes_no") return row.answer === "yes" ? t("common.yes") : t("common.no");
  return row.answer;
}
</script>

<template>
  <article class="flex flex-col gap-2" data-applicant-card :data-applicant="applicant.id">
    <div class="flex items-start gap-2">
      <UserAvatar :name="applicant.name" :size="28" class="mt-0.5" />
      <button type="button" class="min-w-0 flex-1 text-left outline-none" @click.stop="emit('open', applicant)">
        <span class="block truncate text-sm font-semibold text-fg hover:text-primary" :title="applicant.name">{{ applicant.name }}</span>
        <span v-if="applicant.phone" class="block truncate text-xs tabular-nums text-muted">{{ formatPhone(applicant.phone) }}</span>
      </button>
      <UiTooltip v-if="canAct && next" :content="t('hr.hiring.card.moveTo', { stage: t(`hr.hiring.stage.${next}`) })">
        <button
          type="button"
          class="pressable -mr-1.5 -mt-0.5 grid size-6 shrink-0 place-items-center rounded-[7px] text-subtle opacity-70 transition-opacity hover:bg-highlight hover:text-fg group-hover/card:opacity-100"
          :aria-label="t('hr.hiring.card.moveTo', { stage: t(`hr.hiring.stage.${next}`) })"
          data-advance
          @click.stop="emit('advance', applicant)"
        >
          <ChevronRight :size="16" />
        </button>
      </UiTooltip>
    </div>
    <dl v-if="shown.length" class="flex flex-col gap-1 rounded-[8px] bg-surface-2/60 px-2 py-1.5 text-xs dark:bg-surface-2">
      <div v-for="row in shown" :key="row.id" class="flex min-w-0 items-baseline gap-2">
        <dt class="min-w-0 flex-1 truncate text-muted" :title="row.text">{{ row.text }}</dt>
        <dd :class="['max-w-[55%] shrink-0 truncate font-semibold', row.kind === 'yes_no' && row.answer === 'no' ? 'text-danger' : 'text-fg']" :title="answer(row)">{{ answer(row) }}</dd>
      </div>
    </dl>
    <div class="flex flex-wrap items-center gap-1.5">
      <span class="mr-auto text-[11px] text-subtle" :title="fmt.instant(applicant.created_at)">{{ fmt.relative(applicant.created_at) }}</span>
      <span v-if="applicant.source === 'qr'" class="inline-flex h-5 items-center gap-1 rounded-full bg-info-soft px-2 text-[11px] font-semibold text-info"><QrCode :size="11" aria-hidden="true" />{{ t("hr.hiring.source.qr") }}</span>
      <span v-if="applicant.has_document" class="inline-flex h-5 items-center gap-1 rounded-full bg-accent-soft px-2 text-[11px] font-semibold text-accent-fg"><FileImage :size="11" aria-hidden="true" />{{ t("hr.hiring.card.document") }}</span>
      <span v-if="applicant.member" class="inline-flex h-5 items-center gap-1 rounded-full bg-success-soft px-2 text-[11px] font-semibold text-success"><UserCheck :size="11" aria-hidden="true" />{{ t("hr.hiring.card.onTeam") }}</span>
    </div>
    <p v-if="applicant.stage === 'rejected' && applicant.rejected_reason" class="line-clamp-2 text-xs text-muted">{{ applicant.rejected_reason }}</p>
  </article>
</template>
