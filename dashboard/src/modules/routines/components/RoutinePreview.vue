<script setup lang="ts">
/**
 * "Who gets it tomorrow" (plan §1.3): the people a routine names and whether they get the task
 * on a day, by the same rules as daily generation (time off, other apps' days off, the routine's
 * branch, registration). The day is pickable.
 */
import { CalendarOff, Check, ChevronLeft, ChevronRight, Minus, PartyPopper } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { addDays, todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useCompanyStore } from "@/stores/company";

import { usePreview } from "../api";

const props = withDefaults(defineProps<{ routineId: number; compact?: boolean }>(), { compact: false });
const { t } = useI18n();
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));
const day = ref<string | null>(addDays(today.value, 1));

const query = usePreview(computed(() => props.routineId), day);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const data = computed(() => query.data.value);
const getting = computed(() => data.value?.people.filter((row) => row.gets).length ?? 0);
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="flex items-center gap-1">
      <IconButton :icon="ChevronLeft" :label="t('routines.preview.previous')" size="sm" variant="secondary" @click="day = addDays(day ?? today, -1)" />
      <DatePicker v-model="day" size="sm" format="weekday" class="min-w-0 flex-1" />
      <IconButton :icon="ChevronRight" :label="t('routines.preview.next')" size="sm" variant="secondary" @click="day = addDays(day ?? today, 1)" />
    </div>

    <div v-if="skeleton" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 3" :key="n" height="28px" /></div>
    <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="data">
      <p v-if="data.holiday" class="flex items-center gap-2 rounded-[8px] bg-info-soft px-3 py-2 text-sm text-info"><PartyPopper :size="15" />{{ t("routines.preview.holiday") }}</p>
      <p v-else-if="!data.due" class="flex items-center gap-2 rounded-[8px] bg-surface-2 px-3 py-2 text-sm text-muted"><CalendarOff :size="15" />{{ t("routines.preview.notDue") }}</p>
      <p v-else class="text-sm text-muted">{{ t("routines.preview.summary", { n: getting, total: data.people.length }, getting) }}</p>
      <ul v-if="data.people.length" :class="['flex flex-col', compact ? 'gap-1' : 'gap-1.5']">
        <li v-for="row in data.people" :key="row.member.id" class="flex min-w-0 items-center gap-2.5 rounded-[8px] px-1.5 py-1">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="24" />
          <div class="min-w-0 flex-1">
            <p :class="['truncate text-sm', row.gets ? 'font-medium text-fg' : 'text-muted']">{{ row.member.name }}</p>
            <p v-if="row.reason" class="truncate text-xs text-subtle">{{ t(`routines.preview.reason.${row.reason}`) }}</p>
          </div>
          <span v-if="row.gets" class="grid size-5 place-items-center rounded-full bg-success-soft text-success" :aria-label="t('routines.preview.gets')"><Check :size="12" :stroke-width="3" /></span>
          <span v-else class="grid size-5 place-items-center rounded-full bg-surface-2 text-subtle" :aria-label="t('routines.preview.skips')"><Minus :size="12" :stroke-width="3" /></span>
        </li>
      </ul>
      <p v-else class="text-sm text-subtle">{{ t("routines.preview.nobody") }}</p>
    </template>
  </div>
</template>
