<script setup lang="ts" generic="Multiple extends boolean = false">
/**
 * Pick a position (or several with `multiple`): "Cashier", "Shift lead". Reads `GET positions/` once
 * per company; `positions` replaces it with your own list.
 *
 *   <PositionPicker v-model="audience.positions" multiple />
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import ComboBox from "./ComboBox.vue";
import type { ControlSize } from "./field";
import MultiSelect from "./MultiSelect.vue";
import { positionToOption, useCompanyPositions, type PositionOption } from "./pickers";

type Value = Multiple extends true ? number[] : number | null;

const model = defineModel<Value>({ required: true });

const props = withDefaults(
  defineProps<{
    multiple?: Multiple;
    positions?: PositionOption[];
    placeholder?: string;
    clearable?: boolean;
    size?: ControlSize;
    disabled?: boolean;
    invalid?: boolean;
    id?: string;
  }>(),
  { multiple: undefined, positions: undefined, placeholder: undefined, clearable: true, size: "md", disabled: false, invalid: false, id: undefined },
);

const { t } = useI18n();
// Generic props have no Boolean runtime type, so a bare `multiple` attribute arrives as "".
const isMultiple = computed(() => props.multiple === true || (props.multiple as unknown) === "");
const query = useCompanyPositions(computed(() => !props.positions));
const options = computed(() => (props.positions ?? query.data.value ?? []).map(positionToOption));
const placeholderText = computed(() => props.placeholder ?? t(isMultiple.value ? "common.picker.positions" : "common.picker.position"));
</script>

<template>
  <MultiSelect
    v-if="isMultiple"
    :model-value="(model as number[])"
    :options="options"
    :placeholder="placeholderText"
    :size="size"
    :disabled="disabled"
    :invalid="invalid"
    :id="id"
    @update:model-value="(value: number[]) => (model = value as Value)"
  />
  <ComboBox
    v-else
    :model-value="(model as number | null)"
    :options="options"
    :placeholder="placeholderText"
    :clearable="clearable"
    :size="size"
    :disabled="disabled"
    :invalid="invalid"
    :id="id"
    @update:model-value="(value: number | null) => (model = value as Value)"
  />
</template>
