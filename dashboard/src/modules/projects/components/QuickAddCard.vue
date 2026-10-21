<script setup lang="ts">
/**
 * Quick add at the bottom of a list: type a title, optionally pick who and when, Enter adds it and
 * stays open for the next one (Trello-style); Escape closes. The card is a task made through the
 * task app, so it gets reminders like any other.
 */
import { CalendarDays, CornerDownLeft } from "@lucide/vue";
import { computed, nextTick, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { addDays, todayIn } from "@/lib/dates";
import { useCompanyStore } from "@/stores/company";

import { useCreateCard } from "../api";
import type { Person, ProjectDetail } from "../types";

const props = defineProps<{ project: ProjectDetail; listId: number; people: Person[] }>();
const emit = defineEmits<{ close: [] }>();

const { t } = useI18n();
const company = useCompanyStore();
const create = useCreateCard(() => props.project.id);
const title = ref("");
const assignee = ref<number | null>(null);
const due = ref<"today" | "tomorrow" | "week" | null>("week");
const input = ref<HTMLTextAreaElement | null>(null);

const canAssign = computed(() => company.can("tasks.assign"));
const presets = computed(() => [
  { id: "today" as const, label: t("projects.quick.today") },
  { id: "tomorrow" as const, label: t("projects.quick.tomorrow") },
  { id: "week" as const, label: t("projects.quick.week") },
]);

/** 18:00 on the chosen day (week: Friday), in the company's timezone, as an ISO string with its offset. */
function dueAt(): string | null {
  if (!due.value) return null;
  const today = todayIn(company.timezone);
  const day = due.value === "today" ? today : due.value === "tomorrow" ? addDays(today, 1) : addDays(today, daysToFriday(today));
  const offset = tzOffset(company.timezone, day);
  return `${day}T18:00:00${offset}`;
}

/** Days until this week's Friday (next week's when today is Friday or later). */
function daysToFriday(day: string): number {
  const weekday = (new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7;
  const days = 4 - weekday;
  return days > 0 ? days : days + 7;
}

/** "+05:00" for a timezone on a day (Tashkent has no DST, but others might). */
function tzOffset(timeZone: string, day: string): string {
  const date = new Date(`${day}T12:00:00Z`);
  const local = new Date(date.toLocaleString("en-US", { timeZone }));
  const utc = new Date(date.toLocaleString("en-US", { timeZone: "UTC" }));
  const minutes = Math.round((local.getTime() - utc.getTime()) / 60000);
  const sign = minutes >= 0 ? "+" : "-";
  const abs = Math.abs(minutes);
  return `${sign}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
}

async function add(): Promise<void> {
  const text = title.value.trim();
  if (!text || create.isPending.value) return;
  try {
    const card = await create.mutateAsync({ title: text, list: props.listId, assignee: assignee.value, due_at: dueAt() });
    title.value = "";
    toast.success(t("projects.quick.added", { key: card.key }), { id: "projects-quick-add" });
    await nextTick();
    input.value?.focus();
  } catch {
    // The HTTP layer showed why.
  }
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void add();
  } else if (event.key === "Escape") {
    event.preventDefault();
    emit("close");
  }
}

onMounted(() => input.value?.focus());
</script>

<template>
  <div class="flex flex-col gap-2" @keydown.stop>
    <textarea
      ref="input"
      v-model="title"
      rows="2"
      maxlength="200"
      :placeholder="t('projects.quick.placeholder')"
      class="w-full resize-none rounded-[6px] bg-transparent px-1 text-sm text-fg outline-none placeholder:text-subtle"
      :aria-label="t('projects.quick.placeholder')"
      @keydown="onKey"
    />
    <div v-if="canAssign && people.length" class="flex flex-wrap items-center gap-1" role="radiogroup" :aria-label="t('projects.quick.who')">
      <UiTooltip v-for="person in people.slice(0, 7)" :key="person.id" :content="person.name">
        <button
          type="button"
          role="radio"
          :aria-checked="assignee === person.id"
          :aria-label="person.name"
          class="rounded-full ring-2 ring-offset-1 ring-offset-surface transition-shadow"
          :class="assignee === person.id ? 'ring-primary' : 'ring-transparent'"
          @click="assignee = assignee === person.id ? null : person.id"
        >
          <UserAvatar :name="person.name" :src="person.photo_url" :size="22" />
        </button>
      </UiTooltip>
    </div>
    <div class="flex flex-wrap items-center gap-1" role="radiogroup" :aria-label="t('projects.quick.when')">
      <CalendarDays :size="13" class="mr-0.5 text-subtle" aria-hidden="true" />
      <button
        v-for="preset in presets"
        :key="preset.id"
        type="button"
        role="radio"
        :aria-checked="due === preset.id"
        class="h-6 rounded-full px-2 text-[11px] font-semibold transition-colors"
        :class="due === preset.id ? 'bg-accent-soft text-accent-fg' : 'text-muted hover:bg-highlight'"
        @click="due = due === preset.id ? null : preset.id"
      >
        {{ preset.label }}
      </button>
    </div>
    <div class="flex items-center gap-2">
      <UiButton size="sm" variant="primary" :loading="create.isPending.value" :disabled="!title.trim()" :icon-right="CornerDownLeft" @click="add">{{ t("projects.quick.add") }}</UiButton>
      <UiButton size="sm" variant="ghost" @click="emit('close')">{{ t("common.close") }}</UiButton>
    </div>
  </div>
</template>
