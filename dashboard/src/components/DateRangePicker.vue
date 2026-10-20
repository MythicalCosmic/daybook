<script setup lang="ts">
/**
 * A period with presets and an optional comparison (plan §6.2: "range presets with compare
 * toggle"). Presets apply at once; a custom range is picked with two clicks on the calendars and
 * applied with "Apply". Days are company-local; the comparison period follows lib/dates.compareRange
 * (October 1–20 compares with September 1–20).
 *
 *   const period = ref(rangeValue("month", company.timezone, "prev"));
 *   <DateRangePicker v-model="period" />            → rangeParams(period) for the API
 */
import { ArrowRight, CalendarRange, ChevronLeft, ChevronRight } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { compareOf, customValue, type DateRangeValue, type RangePreset } from "@/lib/dateRange";
import { DATE_PRESETS, formatDay, formatRange, presetRange, todayIn, type CompareMode, type DatePreset } from "@/lib/dates";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { monthOf, pickRangeDay, previewRange, shiftMonth, type RangeDraft } from "./calendar";
import CalendarGrid from "./CalendarGrid.vue";
import { controlIconSize, controlSizeClass, controlState, useControl, type ControlSize } from "./field";
import SegmentedControl from "./SegmentedControl.vue";
import UiButton from "./UiButton.vue";
import UiPopover from "./UiPopover.vue";

const model = defineModel<DateRangeValue>({ required: true });

const props = withDefaults(
  defineProps<{
    presets?: readonly DatePreset[];
    compare?: boolean;
    min?: string | null;
    max?: string | null;
    size?: ControlSize;
    variant?: "field" | "ghost";
    disabled?: boolean;
    id?: string;
    align?: "start" | "end";
  }>(),
  { presets: () => DATE_PRESETS, compare: true, min: null, max: undefined, size: "md", variant: "field", disabled: false, id: undefined, align: "start" },
);

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const control = useControl(props);
const { isPhone } = useBreakpoints();

const open = ref(false);
const today = computed(() => todayIn(company.timezone));
const maxDay = computed(() => (props.max === undefined ? today.value : props.max));

// The draft lives while the popover is open; "Apply" (or a preset) commits it.
const preset = ref<RangePreset>(model.value.preset);
const draft = ref<RangeDraft>({ anchor: null, range: { ...model.value.range } });
const compareMode = ref<CompareMode>(model.value.compare);
const hover = ref<string | null>(null);
const focusDay = ref<string | null>(null);
const rightMonth = ref(monthOf(model.value.range.to));
const leftMonth = computed(() => (isPhone.value ? rightMonth.value : shiftMonth(rightMonth.value, -1)));

watch(open, (isOpen) => {
  if (!isOpen) return;
  preset.value = model.value.preset;
  draft.value = { anchor: null, range: { ...model.value.range } };
  compareMode.value = model.value.compare;
  rightMonth.value = monthOf(model.value.range.to);
  focusDay.value = model.value.range.to;
  hover.value = null;
});

const shown = computed(() => previewRange(draft.value, hover.value));
const draftValue = computed<DateRangeValue | null>(() =>
  draft.value.range && draft.value.anchor === null ? { preset: preset.value, range: draft.value.range, compare: compareMode.value } : null,
);
const draftCompare = computed(() => (draftValue.value ? compareOf(draftValue.value) : null));

function choosePreset(next: DatePreset): void {
  const range = presetRange(next, company.timezone);
  preset.value = next;
  draft.value = { anchor: null, range };
  rightMonth.value = monthOf(range.to);
  commit();
}

function pickDay(day: string): void {
  draft.value = pickRangeDay(draft.value, day);
  preset.value = "custom";
}

function commit(): void {
  const value = draftValue.value;
  if (!value) return;
  model.value = value.preset === "custom" ? customValue(value.range, value.compare) : { ...value, range: { ...value.range } };
  open.value = false;
}

const compareOptions = computed(() => [
  { value: "none" as CompareMode, label: t("common.date.compareNone") },
  { value: "prev" as CompareMode, label: t("common.date.comparePrev") },
  { value: "year" as CompareMode, label: t("common.date.compareYear") },
]);

const triggerLabel = computed(() => {
  const value = model.value;
  const range = formatRange(value.range, fmt.lang.value);
  return value.preset === "custom" ? range : `${t(`common.date.preset.${value.preset}`)} · ${range}`;
});
const triggerCompare = computed(() => {
  const range = compareOf(model.value);
  return range ? t("common.date.vs", { range: formatRange(range, fmt.lang.value) }) : null;
});

function moveMonths(direction: 1 | -1): void {
  rightMonth.value = shiftMonth(rightMonth.value, direction);
}

function onNavigate(month: string, side: "left" | "right"): void {
  rightMonth.value = side === "left" && !isPhone.value ? shiftMonth(month, 1) : month;
}
</script>

<template>
  <UiPopover v-model:open="open" :padded="false" :align="align" width="min(700px, calc(100vw - 16px))">
    <template #trigger>
      <button
        :id="control.id.value"
        type="button"
        aria-haspopup="dialog"
        :aria-expanded="open"
        :aria-labelledby="control.labelId.value ? `${control.labelId.value} ${control.id.value}` : undefined"
        :disabled="control.disabled.value"
        :data-state="open ? 'open' : 'closed'"
        :class="[
          'ui-control max-w-full',
          controlSizeClass[size],
          variant === 'ghost' && '!border-transparent !bg-transparent !shadow-none hover:!bg-highlight',
        ]"
        v-bind="controlState({ disabled: control.disabled.value })"
      >
        <CalendarRange :size="controlIconSize[size]" class="-ml-0.5 shrink-0 text-subtle" aria-hidden="true" />
        <span class="min-w-0 truncate font-medium">{{ triggerLabel }}</span>
        <span v-if="triggerCompare" class="hidden min-w-0 truncate text-muted sm:inline">{{ triggerCompare }}</span>
      </button>
    </template>

    <div class="flex flex-col sm:flex-row">
      <!-- Presets -->
      <div
        role="listbox"
        :aria-label="t('common.date.presets')"
        class="no-scrollbar flex shrink-0 gap-1 overflow-x-auto border-b border-line p-2 sm:w-[168px] sm:flex-col sm:overflow-visible sm:border-b-0 sm:border-r"
      >
        <button
          v-for="item in presets"
          :key="item"
          type="button"
          role="option"
          :aria-selected="preset === item"
          :class="[
            'shrink-0 whitespace-nowrap rounded-[7px] px-2.5 py-1.5 text-left text-sm font-medium transition-colors',
            preset === item ? 'bg-accent-soft font-semibold text-accent-fg' : 'text-fg hover:bg-highlight',
          ]"
          @click="choosePreset(item)"
        >
          {{ t(`common.date.preset.${item}`) }}
        </button>
        <span
          :class="[
            'shrink-0 whitespace-nowrap rounded-[7px] px-2.5 py-1.5 text-sm font-medium',
            preset === 'custom' ? 'bg-accent-soft font-semibold text-accent-fg' : 'text-subtle',
          ]"
          >{{ t("common.date.preset.custom") }}</span
        >
      </div>

      <!-- Calendars -->
      <div class="min-w-0 flex-1 p-3">
        <div class="mb-2 flex items-center gap-1">
          <button
            type="button"
            class="pressable grid size-8 place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg"
            :aria-label="t('common.date.prevMonth')"
            @click="moveMonths(-1)"
          >
            <ChevronLeft :size="16" />
          </button>
          <p class="flex-1 text-center text-base font-semibold text-fg sm:text-left sm:pl-12">{{ formatDay(`${leftMonth}-01`, fmt.lang.value, "monthYear") }}</p>
          <p v-if="!isPhone" class="flex-1 pr-12 text-right text-base font-semibold text-fg">{{ formatDay(`${rightMonth}-01`, fmt.lang.value, "monthYear") }}</p>
          <button
            type="button"
            class="pressable grid size-8 place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg"
            :aria-label="t('common.date.nextMonth')"
            @click="moveMonths(1)"
          >
            <ChevronRight :size="16" />
          </button>
        </div>
        <div class="flex justify-center gap-6">
          <CalendarGrid
            v-model:focus-day="focusDay"
            :month="leftMonth"
            :today="today"
            :range="shown"
            :compare="draftCompare"
            :min="min"
            :max="maxDay"
            :hide-outside="!isPhone"
            @select="pickDay"
            @hover="(day) => (hover = day)"
            @navigate="(month) => onNavigate(month, 'left')"
          />
          <CalendarGrid
            v-if="!isPhone"
            v-model:focus-day="focusDay"
            :month="rightMonth"
            :today="today"
            :range="shown"
            :compare="draftCompare"
            :min="min"
            :max="maxDay"
            hide-outside
            @select="pickDay"
            @hover="(day) => (hover = day)"
            @navigate="(month) => onNavigate(month, 'right')"
          />
        </div>

        <div v-if="compare" class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line pt-3">
          <span class="text-sm font-semibold text-fg">{{ t("common.date.compare") }}</span>
          <SegmentedControl v-model="compareMode" :options="compareOptions" size="sm" :aria-label="t('common.date.compare')" />
          <span v-if="draftCompare" class="flex items-center gap-1.5 text-xs text-muted">
            <span class="h-0.5 w-3 rounded-full bg-[var(--c-chart-3)]" aria-hidden="true" />
            {{ formatRange(draftCompare, fmt.lang.value) }}
          </span>
        </div>

        <div class="mt-3 flex items-center gap-2 border-t border-line pt-3">
          <p class="flex min-w-0 flex-1 items-center gap-1.5 truncate text-sm font-medium tabular-nums text-fg">
            <template v-if="shown">
              <span>{{ formatDay(shown.from, fmt.lang.value, "medium") }}</span>
              <ArrowRight :size="13" class="shrink-0 text-subtle" aria-hidden="true" />
              <span :class="draft.anchor ? 'text-subtle' : ''">{{ formatDay(shown.to, fmt.lang.value, "medium") }}</span>
            </template>
          </p>
          <UiButton size="sm" variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
          <UiButton size="sm" variant="primary" :disabled="!draftValue" @click="commit">{{ t("common.apply") }}</UiButton>
        </div>
      </div>
    </div>
  </UiPopover>
</template>
