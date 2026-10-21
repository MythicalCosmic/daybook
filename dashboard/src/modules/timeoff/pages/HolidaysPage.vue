<script setup lang="ts">
/**
 * Holidays (plan §6.2 "holidays editor"): the company's days off for everyone, a year at a time.
 * No routine tasks or reminders on those days and they never count as leave. One click adds
 * Uzbekistan's fixed public holidays; the two Hayit days move every year and are added by hand.
 */
import { CalendarHeart, ChevronLeft, ChevronRight, Ellipsis, Flag, Pencil, Plus, Trash2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import DropdownMenu from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { diffDays, parseDay, todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useHolidayMutations, useHolidays } from "../api";
import type { Holiday } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const confirm = useConfirm();

const today = computed(() => todayIn(company.timezone));
const year = useRouteState("year", rs.number(Number(todayIn(company.timezone).slice(0, 4))));
const holidays = useHolidays(year);
const skeleton = useDelayedPending(computed(() => holidays.isPending.value));
const { create, update, remove, addPublic } = useHolidayMutations();

const rows = computed(() => holidays.data.value ?? []);
const months = computed(() => {
  const groups: Array<{ month: string; label: string; items: Holiday[] }> = [];
  for (const holiday of rows.value) {
    const month = holiday.date.slice(0, 7);
    let group = groups.find((g) => g.month === month);
    if (!group) {
      group = { month, label: fmt.day(`${month}-01`, "monthYear"), items: [] };
      groups.push(group);
    }
    group.items.push(holiday);
  }
  return groups;
});
const upcoming = computed(() => rows.value.filter((h) => h.date >= today.value).length);

// Add / edit ----------------------------------------------------------------------------
const addParam = useRouteState("add", rs.boolean(false));
const editing = ref<Holiday | null>(null);
const date = ref<string | null>(null);
const name = ref("");
const dialogOpen = computed({
  get: () => addParam.value || editing.value !== null,
  set: (value: boolean) => {
    if (!value) {
      addParam.value = false;
      editing.value = null;
    }
  },
});
watch(
  addParam,
  (value) => {
    if (value) {
      editing.value = null;
      date.value = null;
      name.value = "";
    }
  },
  { immediate: true },
);
function openEdit(holiday: Holiday): void {
  editing.value = holiday;
  date.value = holiday.date;
  name.value = holiday.name;
}

async function submit(): Promise<void> {
  if (!date.value || !name.value.trim()) return;
  try {
    if (editing.value) {
      await update.mutateAsync({ id: editing.value.id, body: { date: date.value, name: name.value.trim() } });
      toast.success(t("timeoff.holidays.saved", { name: name.value.trim() }));
    } else {
      await create.mutateAsync({ date: date.value, name: name.value.trim() });
      toast.success(t("timeoff.holidays.added", { name: name.value.trim() }));
    }
    dialogOpen.value = false;
  } catch {
    // Shown (a holiday on that day already).
  }
}

async function deleteHoliday(holiday: Holiday): Promise<void> {
  const answer = await confirm({ title: t("timeoff.holidays.deleteTitle", { name: holiday.name }), message: t("timeoff.holidays.deleteBody"), tone: "danger", confirmLabel: t("common.delete") });
  if (!answer) return;
  try {
    await remove.mutateAsync(holiday.id);
    toast.success(t("timeoff.holidays.deleted", { name: holiday.name }));
  } catch {
    // Shown.
  }
}

async function addPublicHolidays(): Promise<void> {
  try {
    const added = await addPublic.mutateAsync(year.value);
    if (added.length) toast.success(t("timeoff.holidays.publicAdded", { n: added.length }, added.length), { description: t("timeoff.holidays.publicHint") });
    else toast.info(t("timeoff.holidays.publicNone", { year: year.value }));
  } catch {
    // Shown.
  }
}

function weekday(day: string): string {
  return fmt.day(day, "weekday").split(",")[0] ?? "";
}
function away(day: string): string | null {
  const days = diffDays(today.value, day);
  if (days < 0 || days > 60) return null;
  return days === 0 ? t("timeoff.holidays.todayLabel") : t("timeoff.holidays.inDays", { n: days }, days);
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader class="!mb-0" :title="t('timeoff.holidays.title')" :description="t('timeoff.holidays.description')" :back="`/c/${company.currentId}/time-off`" :back-label="t('timeoff.title')">
      <!-- An empty year offers both in its empty state instead. -->
      <template v-if="!(holidays.data.value && !rows.length)" #actions>
        <UiButton :icon="Flag" :loading="addPublic.isPending.value" @click="addPublicHolidays">{{ t("timeoff.holidays.addPublic", { year }) }}</UiButton>
        <UiButton variant="primary" :icon="Plus" @click="addParam = true">{{ t("timeoff.holidays.add") }}</UiButton>
      </template>
    </PageHeader>

    <div class="flex items-center gap-2">
      <IconButton :icon="ChevronLeft" :label="t('timeoff.holidays.prevYear')" variant="secondary" @click="year -= 1" />
      <span class="min-w-[64px] text-center text-lg font-semibold tabular-nums text-fg">{{ year }}</span>
      <IconButton :icon="ChevronRight" :label="t('timeoff.holidays.nextYear')" variant="secondary" @click="year += 1" />
      <span class="ml-2 text-sm text-muted">{{ t("timeoff.holidays.count", { n: rows.length }, rows.length) }}<template v-if="upcoming && year === Number(today.slice(0, 4))"> · {{ t("timeoff.holidays.upcoming", { n: upcoming }, upcoming) }}</template></span>
    </div>

    <div v-if="skeleton" class="grid grid-cols-1 gap-3 md:grid-cols-2"><SkeletonBlock v-for="n in 6" :key="n" height="72px" radius="12px" /></div>
    <ErrorState v-else-if="holidays.isError.value" class="ui-card" :error="holidays.error.value" :retry="() => holidays.refetch()" />
    <div v-else-if="holidays.data.value && !rows.length" class="ui-card">
      <EmptyState :icon="CalendarHeart" :title="t('timeoff.holidays.emptyTitle', { year })" :description="t('timeoff.holidays.emptyBody')">
        <UiButton variant="primary" :icon="Flag" :loading="addPublic.isPending.value" @click="addPublicHolidays">{{ t("timeoff.holidays.addPublic", { year }) }}</UiButton>
        <UiButton :icon="Plus" @click="addParam = true">{{ t("timeoff.holidays.add") }}</UiButton>
      </EmptyState>
    </div>
    <div v-else class="flex flex-col gap-6">
      <section v-for="group in months" :key="group.month" class="flex flex-col gap-2">
        <h2 class="text-sm font-semibold text-muted">{{ group.label }}</h2>
        <div class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          <article
            v-for="holiday in group.items"
            :key="holiday.id"
            :class="['ui-card group flex items-center gap-3 p-3 transition-colors hover:border-line-strong', holiday.date < today && 'opacity-70']"
          >
            <div class="grid size-12 shrink-0 place-items-center rounded-[12px] bg-accent-soft text-accent-fg">
              <span class="text-center leading-none">
                <span class="block text-lg font-semibold tabular-nums">{{ parseDay(holiday.date).getUTCDate() }}</span>
                <span class="block text-[10px] font-semibold uppercase">{{ fmt.day(holiday.date, "short").replace(/^\d+[-\s.]*/, "") }}</span>
              </span>
            </div>
            <div class="min-w-0 flex-1">
              <p class="truncate text-base font-semibold text-fg">{{ holiday.name }}</p>
              <p class="truncate text-sm capitalize text-muted">{{ weekday(holiday.date) }}</p>
            </div>
            <StatusPill v-if="away(holiday.date)" size="sm" tone="primary" :label="away(holiday.date)!" />
            <DropdownMenu
              :items="[
                { label: t('common.edit'), icon: Pencil, onSelect: () => openEdit(holiday) },
                { type: 'separator' },
                { label: t('common.delete'), icon: Trash2, danger: true, onSelect: () => void deleteHoliday(holiday) },
              ]"
              align="end"
            >
              <template #trigger><IconButton :icon="Ellipsis" :label="t('timeoff.holidays.options', { name: holiday.name })" size="sm" /></template>
            </DropdownMenu>
          </article>
        </div>
      </section>
      <InlineAlert tone="info" :description="t('timeoff.holidays.hayitNote')" />
    </div>

    <UiDialog v-model:open="dialogOpen" :title="editing ? t('timeoff.holidays.editTitle') : t('timeoff.holidays.addTitle')" :description="t('timeoff.holidays.dialogHint')" size="sm">
      <form id="holiday-form" class="flex flex-col gap-4" @submit.prevent="submit">
        <FormField :label="t('timeoff.holidays.date')" required>
          <DatePicker v-model="date" format="weekday" />
        </FormField>
        <FormField :label="t('timeoff.holidays.name')" required>
          <TextInput v-model="name" :maxlength="100" :placeholder="t('timeoff.holidays.namePlaceholder')" />
        </FormField>
      </form>
      <template #footer>
        <UiButton variant="ghost" @click="dialogOpen = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" type="submit" form="holiday-form" :loading="create.isPending.value || update.isPending.value" :disabled="!date || !name.trim()">{{ editing ? t("common.save") : t("common.create") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
