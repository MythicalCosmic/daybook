<script setup lang="ts">
/** One question an offboarding step asks (a registered `FieldSpec`), drawn by its kind. */
import { computed } from "vue";

import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";

import type { OffboardField } from "../types";

const model = defineModel<unknown>();
const props = defineProps<{ field: OffboardField; error?: string; exclude?: number[] }>();

const choices = computed(() => props.field.choices.map(([value, label]) => ({ value, label })));
const text = computed({ get: () => (model.value as string | null) ?? "", set: (value: string | null) => (model.value = value ?? "") });
const flag = computed({ get: () => Boolean(model.value), set: (value: boolean) => (model.value = value) });
const choice = computed({ get: () => (model.value as string | null) ?? null, set: (value: string | null) => (model.value = value) });
const day = computed({ get: () => (model.value as string | null) ?? null, set: (value: string | null) => (model.value = value) });
const money = computed({ get: () => (model.value as string | null) ?? null, set: (value: string | null) => (model.value = value) });
const number = computed({ get: () => (typeof model.value === "number" ? model.value : null), set: (value: number | null) => (model.value = value) });
const person = computed({ get: () => (typeof model.value === "number" ? model.value : null), set: (value: number | null) => (model.value = value) });
</script>

<template>
  <ToggleSwitch v-if="field.kind === 'bool'" v-model="flag" layout="row" :label="field.label" :description="field.help || undefined" />
  <FormField v-else :label="field.label" :hint="field.help || undefined" :error="error" :required="field.required">
    <TextArea v-if="field.kind === 'textarea'" v-model="text" :rows="3" />
    <SelectBox v-else-if="field.kind === 'choice'" v-model="choice" :options="choices" />
    <DatePicker v-else-if="field.kind === 'date'" v-model="day" />
    <MoneyInput v-else-if="field.kind === 'money'" v-model="money" />
    <NumberInput v-else-if="field.kind === 'number'" v-model="number" />
    <PersonPicker v-else-if="field.kind === 'member'" v-model="person" :exclude="exclude" />
    <TextInput v-else v-model="text" />
  </FormField>
</template>
