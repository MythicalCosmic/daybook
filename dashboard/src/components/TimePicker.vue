<script setup lang="ts">
/**
 * A time of day, 24-hour ("HH:MM" or null). Type it the quick way ("9" → 09:00, "930" → 09:30,
 * "21.15" → 21:15), step with ↑/↓ by `step` minutes, or pick from the list behind the clock button.
 *
 *   <TimePicker v-model="branch.opens_at" :step="15" />
 */
import { Clock3 } from "@lucide/vue";
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { fromMinutes, parseTime, toMinutes } from "@/lib/time";

import { controlIconSize, controlSizeClass, controlState, useControl, type ControlSize } from "./field";
import UiPopover from "./UiPopover.vue";

defineOptions({ inheritAttrs: false });

const model = defineModel<string | null>({ default: null });

const props = withDefaults(
  defineProps<{
    step?: number;
    min?: string;
    max?: string;
    placeholder?: string;
    size?: ControlSize;
    disabled?: boolean;
    readonly?: boolean;
    invalid?: boolean;
    id?: string;
  }>(),
  { step: 30, min: "00:00", max: "23:59", placeholder: "--:--", size: "md", disabled: false, readonly: false, invalid: false, id: undefined },
);

const { t } = useI18n();
const control = useControl(props);
const input = ref<HTMLInputElement | null>(null);
const list = ref<HTMLElement | null>(null);
const open = ref(false);
const text = ref(model.value ?? "");

watch(model, (value) => (text.value = value ?? ""));

function clamp(time: string): string {
  const value = toMinutes(time);
  return fromMinutes(Math.min(toMinutes(props.max), Math.max(toMinutes(props.min), value)));
}

function commit(): void {
  if (!text.value.trim()) {
    model.value = null;
    return;
  }
  const parsed = parseTime(text.value);
  if (parsed) model.value = clamp(parsed);
  text.value = model.value ?? "";
}

function stepBy(direction: 1 | -1): void {
  const base = model.value ? toMinutes(model.value) : toMinutes("09:00") - direction * props.step;
  const snapped = Math.round(base / props.step) * props.step;
  const next = snapped === base ? base + direction * props.step : direction > 0 ? Math.ceil(base / props.step) * props.step : Math.floor(base / props.step) * props.step;
  model.value = clamp(fromMinutes(next));
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter") {
    event.preventDefault();
    commit();
  } else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
    event.preventDefault();
    stepBy(event.key === "ArrowUp" ? 1 : -1);
  }
}

const slots = computed(() => {
  const out: string[] = [];
  for (let m = toMinutes(props.min); m <= toMinutes(props.max); m += props.step) out.push(fromMinutes(m));
  return out;
});

function pick(time: string): void {
  model.value = time;
  open.value = false;
  input.value?.focus();
}

watch(open, async (isOpen) => {
  if (!isOpen) return;
  await nextTick();
  const target = list.value?.querySelector<HTMLElement>('[aria-selected="true"]') ?? list.value?.querySelector<HTMLElement>('[data-near="true"]');
  target?.scrollIntoView?.({ block: "center" });
  target?.focus();
});

const nearest = computed(() => {
  const value = model.value ? toMinutes(model.value) : toMinutes("09:00");
  return slots.value.reduce((best, slot) => (Math.abs(toMinutes(slot) - value) < Math.abs(toMinutes(best) - value) ? slot : best), slots.value[0] ?? "09:00");
});

function onListKeydown(event: KeyboardEvent): void {
  const items = [...(list.value?.querySelectorAll<HTMLElement>("[role=option]") ?? [])];
  const index = items.indexOf(document.activeElement as HTMLElement);
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    items[Math.min(items.length - 1, Math.max(0, index + (event.key === "ArrowDown" ? 1 : -1)))]?.focus();
  }
}
</script>

<template>
  <div
    :class="['ui-control w-[124px] !pr-1', controlSizeClass[size], $attrs.class]"
    :style="$attrs.style as never"
    v-bind="controlState({ invalid: control.invalid.value, disabled: control.disabled.value, readonly })"
  >
    <input
      :id="control.id.value"
      ref="input"
      v-model="text"
      type="text"
      inputmode="numeric"
      autocomplete="off"
      maxlength="5"
      class="ui-input font-medium tabular-nums"
      :placeholder="placeholder"
      :disabled="control.disabled.value"
      :readonly="readonly"
      :aria-invalid="control.invalid.value || undefined"
      :aria-describedby="control.describedBy.value"
      :required="control.required.value || undefined"
      v-bind="{ ...$attrs, class: undefined, style: undefined }"
      @blur="commit"
      @keydown="onKeydown"
    />
    <UiPopover v-if="!readonly" v-model:open="open" :padded="false" width="124px" align="end">
      <template #trigger>
        <button
          type="button"
          class="pressable grid size-6 shrink-0 place-items-center rounded-[5px] text-subtle hover:bg-highlight hover:text-fg"
          :aria-label="t('common.time.pick')"
          :disabled="control.disabled.value"
        >
          <Clock3 :size="controlIconSize[size]" />
        </button>
      </template>
      <div ref="list" role="listbox" :aria-label="t('common.time.pick')" class="max-h-[240px] overflow-y-auto p-1" @keydown="onListKeydown">
        <button
          v-for="slot in slots"
          :key="slot"
          type="button"
          role="option"
          :aria-selected="slot === model"
          :data-near="slot === nearest"
          :class="[
            'flex h-8 w-full items-center justify-center rounded-[7px] text-base tabular-nums outline-none hover:bg-highlight focus-visible:bg-highlight',
            slot === model ? 'bg-accent-soft font-semibold text-accent-fg' : 'text-fg',
          ]"
          @click="pick(slot)"
        >
          {{ slot }}
        </button>
      </div>
    </UiPopover>
  </div>
</template>
