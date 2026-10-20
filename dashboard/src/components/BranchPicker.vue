<script setup lang="ts" generic="Multiple extends boolean = false">
/**
 * Pick a branch (or several with `multiple`) among the ones the person may see in this company
 * (`me` branches limited by their branch scope, plan §2.6). No request. A short list renders as a
 * plain select; `branches` replaces the list.
 *
 *   <BranchPicker v-model="filters.branch" multiple />
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { BranchRef } from "@/api/types";

import ComboBox from "./ComboBox.vue";
import type { ControlSize } from "./field";
import MultiSelect from "./MultiSelect.vue";
import { branchToOption, useScopedBranches } from "./pickers";
import SelectBox from "./SelectBox.vue";

type Value = Multiple extends true ? number[] : number | null;

const model = defineModel<Value>({ required: true });

const props = withDefaults(
  defineProps<{
    multiple?: Multiple;
    branches?: BranchRef[];
    placeholder?: string;
    clearable?: boolean;
    size?: ControlSize;
    disabled?: boolean;
    invalid?: boolean;
    id?: string;
  }>(),
  { multiple: undefined, branches: undefined, placeholder: undefined, clearable: true, size: "md", disabled: false, invalid: false, id: undefined },
);

const { t } = useI18n();
const scoped = useScopedBranches();
const options = computed(() => (props.branches ?? scoped.value).map(branchToOption));
const placeholderText = computed(() => props.placeholder ?? t(props.multiple ? "common.picker.branches" : "common.picker.branch"));
</script>

<template>
  <MultiSelect
    v-if="multiple"
    :model-value="(model as number[])"
    :options="options"
    :placeholder="placeholderText"
    :size="size"
    :disabled="disabled"
    :invalid="invalid"
    :id="id"
    @update:model-value="(value: number[]) => (model = value as Value)"
  />
  <SelectBox
    v-else-if="options.length <= 8"
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
