<script setup lang="ts">
/**
 * A one-line text field. `icon` leads, `prefix`/`suffix` add fixed text ("+998", "km"), `clearable`
 * adds a clear button, and the `leading`/`trailing` slots take anything else. Inside a FormField it
 * picks up the label, hint and error wiring by itself.
 *
 *   <TextInput v-model="name" :placeholder="t('people.name')" />
 *   <TextInput v-model="q" type="search" :icon="Search" clearable size="sm" />
 */
import { X } from "@lucide/vue";
import { computed, ref, type Component } from "vue";
import { useI18n } from "vue-i18n";

import { controlIconSize, controlSizeClass, controlState, useControl, type ControlSize } from "./field";

defineOptions({ inheritAttrs: false });

const model = defineModel<string | null>({ default: "" });

const props = withDefaults(
  defineProps<{
    type?: "text" | "email" | "tel" | "url" | "search" | "password";
    placeholder?: string;
    size?: ControlSize;
    icon?: Component;
    prefix?: string;
    suffix?: string;
    clearable?: boolean;
    disabled?: boolean;
    readonly?: boolean;
    invalid?: boolean;
    id?: string;
    maxlength?: number;
    autocomplete?: string;
    inputmode?: "text" | "numeric" | "decimal" | "tel" | "email" | "url" | "search" | "none";
    autofocus?: boolean;
    /** Monospace digits and letters (codes, keys, phone numbers). */
    mono?: boolean;
  }>(),
  {
    type: "text",
    placeholder: undefined,
    size: "md",
    icon: undefined,
    prefix: undefined,
    suffix: undefined,
    clearable: false,
    disabled: false,
    readonly: false,
    invalid: false,
    id: undefined,
    maxlength: undefined,
    autocomplete: undefined,
    inputmode: undefined,
    autofocus: false,
    mono: false,
  },
);

const emit = defineEmits<{ enter: [event: KeyboardEvent]; clear: [] }>();

const { t } = useI18n();
const control = useControl(props);
const input = ref<HTMLInputElement | null>(null);

const showClear = computed(() => props.clearable && !!model.value && !control.disabled.value && !props.readonly);

function clear(): void {
  model.value = "";
  emit("clear");
  input.value?.focus();
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.isComposing) emit("enter", event);
  if (event.key === "Escape" && props.clearable && model.value) {
    event.stopPropagation();
    clear();
  }
}

defineExpose({ focus: () => input.value?.focus(), select: () => input.value?.select(), el: input });
</script>

<template>
  <div
    :class="['ui-control', controlSizeClass[size], $attrs.class]"
    :style="$attrs.style as never"
    v-bind="controlState({ invalid: control.invalid.value, disabled: control.disabled.value, readonly })"
    @click="input?.focus()"
  >
    <slot name="leading">
      <component :is="icon" v-if="icon" :size="controlIconSize[size]" class="ui-adorn -ml-0.5" aria-hidden="true" />
    </slot>
    <span v-if="prefix" class="ui-adorn text-muted">{{ prefix }}</span>
    <input
      :id="control.id.value"
      ref="input"
      v-model="model"
      :type="type"
      :class="['ui-input', mono && 'font-mono text-[0.95em] tracking-tight']"
      :placeholder="placeholder"
      :disabled="control.disabled.value"
      :readonly="readonly"
      :maxlength="maxlength"
      :autocomplete="autocomplete"
      :inputmode="inputmode"
      :autofocus="autofocus"
      :required="control.required.value || undefined"
      :aria-invalid="control.invalid.value || undefined"
      :aria-describedby="control.describedBy.value"
      :data-clearable="clearable || undefined"
      v-bind="{ ...$attrs, class: undefined, style: undefined }"
      @keydown="onKeydown"
    />
    <span v-if="suffix" class="ui-adorn text-muted">{{ suffix }}</span>
    <button
      v-if="showClear"
      type="button"
      class="pressable -mr-1 grid size-5 shrink-0 place-items-center rounded-full text-subtle hover:bg-highlight hover:text-fg"
      :aria-label="t('common.clear')"
      @click.stop="clear"
    >
      <X :size="13" />
    </button>
    <slot name="trailing" />
  </div>
</template>
