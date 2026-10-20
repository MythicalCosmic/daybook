<script setup lang="ts" generic="Multiple extends boolean = false">
/**
 * Pick a person (or several with `multiple`) from the company's team, with photos and positions.
 * Reads `GET people/` once per company (cached); `filters` narrows it (`{ branch: [1, 2] }`),
 * `people` replaces it with your own list, `exclude` hides ids (the current assignee).
 *
 *   <PersonPicker v-model="form.values.assignee" />
 *   <PersonPicker v-model="form.values.reviewers" multiple :filters="{ position: 3 }" />
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import ComboBox from "./ComboBox.vue";
import type { ControlSize } from "./field";
import MultiSelect from "./MultiSelect.vue";
import { personToOption, useCompanyPeople, type PersonOption } from "./pickers";

type Value = Multiple extends true ? number[] : number | null;

const model = defineModel<Value>({ required: true });

const props = withDefaults(
  defineProps<{
    multiple?: Multiple;
    people?: PersonOption[];
    filters?: Record<string, string | number | boolean | readonly (string | number)[] | undefined>;
    exclude?: number[];
    placeholder?: string;
    clearable?: boolean;
    size?: ControlSize;
    disabled?: boolean;
    invalid?: boolean;
    id?: string;
  }>(),
  {
    multiple: undefined,
    people: undefined,
    filters: () => ({ status: "active" }),
    exclude: () => [],
    placeholder: undefined,
    clearable: true,
    size: "md",
    disabled: false,
    invalid: false,
    id: undefined,
  },
);

const { t } = useI18n();
const query = useCompanyPeople(
  computed(() => !props.people),
  computed(() => props.filters),
);
const options = computed(() =>
  (props.people ?? query.data.value ?? []).filter((person) => !props.exclude.includes(person.id)).map(personToOption),
);
const placeholderText = computed(() => props.placeholder ?? t(props.multiple ? "common.picker.people" : "common.picker.person"));
</script>

<template>
  <MultiSelect
    v-if="multiple"
    :model-value="(model as number[])"
    :options="options"
    :placeholder="placeholderText"
    :search-placeholder="t('common.picker.searchPeople')"
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
    :search-placeholder="t('common.picker.searchPeople')"
    :clearable="clearable"
    :size="size"
    :disabled="disabled"
    :invalid="invalid"
    :id="id"
    @update:model-value="(value: number | null) => (model = value as Value)"
  />
</template>
