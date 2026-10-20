<script setup lang="ts">
/**
 * One company-local day ("2026-10-20" or null). The field shows it in words ("20-okt, 2026");
 * the calendar opens on the chosen month, "Today" means today in the company's timezone, and
 * `min`/`max`/`disabledDays` limit the choice.
 *
 *   <DatePicker v-model="form.values.due_on" :min="today" clearable />
 */
import { CalendarDays, ChevronLeft, ChevronRight, X } from "@lucide/vue";
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { formatDay, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { clampDay, monthOf, shiftMonth } from "./calendar";
import CalendarGrid from "./CalendarGrid.vue";
import { controlIconSize, controlSizeClass, controlState, useControl, type ControlSize } from "./field";
import UiPopover from "./UiPopover.vue";

const model = defineModel<string | null>({ default: null });

const props = withDefaults(
  defineProps<{
    placeholder?: string;
    min?: string | null;
    max?: string | null;
    disabledDays?: (day: string) => boolean;
    clearable?: boolean;
    size?: ControlSize;
    disabled?: boolean;
    invalid?: boolean;
    id?: string;
    /** "weekday" reads "Tuesday, 20 October". */
    format?: "medium" | "long" | "weekday";
  }>(),
  { placeholder: undefined, min: null, max: null, disabledDays: undefined, clearable: false, size: "md", disabled: false, invalid: false, id: undefined, format: "medium" },
);

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const control = useControl(props);
const open = ref(false);
const today = computed(() => todayIn(company.timezone));
const month = ref(monthOf(model.value ?? today.value));
const focusDay = ref<string | null>(null);
const grid = ref<InstanceType<typeof CalendarGrid> | null>(null);
const trigger = ref<HTMLButtonElement | null>(null);

watch(open, async (isOpen) => {
  if (!isOpen) return;
  month.value = monthOf(model.value ?? clampDay(today.value, props.min, props.max));
  focusDay.value = model.value ?? clampDay(today.value, props.min, props.max);
  await nextTick();
  grid.value?.focus();
});

function select(day: string): void {
  model.value = day;
  open.value = false;
  trigger.value?.focus();
}

const label = computed(() => (model.value ? formatDay(model.value, fmt.lang.value, props.format) : null));
const canPickToday = computed(() => {
  const day = today.value;
  return !(props.min && day < props.min) && !(props.max && day > props.max) && !props.disabledDays?.(day);
});
</script>

<template>
  <div class="relative min-w-0">
    <UiPopover v-model:open="open" :padded="false" align="start">
      <template #trigger>
        <button
          :id="control.id.value"
          ref="trigger"
          type="button"
          aria-haspopup="dialog"
          :aria-expanded="open"
          :aria-labelledby="control.labelId.value ? `${control.labelId.value} ${control.id.value}` : undefined"
          :aria-describedby="control.describedBy.value"
          :aria-invalid="control.invalid.value || undefined"
          :disabled="control.disabled.value"
          :data-state="open ? 'open' : 'closed'"
          :class="['ui-control w-full', controlSizeClass[size], clearable && model && '!pr-8']"
          v-bind="controlState({ invalid: control.invalid.value, disabled: control.disabled.value })"
        >
          <CalendarDays :size="controlIconSize[size]" class="-ml-0.5 shrink-0 text-subtle" aria-hidden="true" />
          <span v-if="label" class="min-w-0 flex-1 truncate tabular-nums">{{ label }}</span>
          <span v-else class="min-w-0 flex-1 truncate text-subtle">{{ placeholder ?? t("common.date.placeholder") }}</span>
        </button>
      </template>
      <div class="w-[296px] p-3">
        <div class="mb-2 flex items-center gap-1">
          <button
            type="button"
            class="pressable grid size-8 place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg"
            :aria-label="t('common.date.prevMonth')"
            @click="month = shiftMonth(month, -1)"
          >
            <ChevronLeft :size="16" />
          </button>
          <p class="flex-1 text-center text-base font-semibold text-fg" aria-live="polite">{{ formatDay(`${month}-01`, fmt.lang.value, "monthYear") }}</p>
          <button
            type="button"
            class="pressable grid size-8 place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg"
            :aria-label="t('common.date.nextMonth')"
            @click="month = shiftMonth(month, 1)"
          >
            <ChevronRight :size="16" />
          </button>
        </div>
        <CalendarGrid
          ref="grid"
          v-model:focus-day="focusDay"
          :month="month"
          :today="today"
          :selected="model"
          :min="min"
          :max="max"
          :disabled-days="disabledDays"
          @select="select"
          @navigate="(next) => (month = next)"
        />
        <div class="mt-2 flex items-center justify-between border-t border-line pt-2">
          <button
            type="button"
            class="rounded-[6px] px-2 py-1 text-sm font-semibold text-primary hover:bg-accent-soft disabled:opacity-40"
            :disabled="!canPickToday"
            @click="select(today)"
          >
            {{ t("common.today") }}
          </button>
          <button
            v-if="model && clearable"
            type="button"
            class="rounded-[6px] px-2 py-1 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg"
            @click="
              model = null;
              open = false;
            "
          >
            {{ t("common.clear") }}
          </button>
        </div>
      </div>
    </UiPopover>
    <button
      v-if="clearable && model && !control.disabled.value"
      type="button"
      class="pressable absolute right-2 top-1/2 grid size-5 -translate-y-1/2 place-items-center rounded-full text-subtle hover:bg-highlight hover:text-fg"
      :aria-label="t('common.clear')"
      @click="model = null"
    >
      <X :size="13" />
    </button>
  </div>
</template>
