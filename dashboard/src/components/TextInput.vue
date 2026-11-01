<script setup lang="ts">
/**
 * A one-line text field. `icon` leads, `prefix`/`suffix` add fixed text ("+998", "km"), `clearable`
 * adds a clear button, and the `leading`/`trailing` slots take anything else. Inside a FormField it
 * picks up the label, hint and error wiring by itself.
 *
 *   <TextInput v-model="name" :placeholder="t('people.name')" />
 *   <TextInput v-model="q" type="search" :icon="Search" clearable size="sm" />
 *
 * `debounce` (ms) passes the text on once typing pauses (Enter, clearing and leaving the field pass
 * it at once): a search that asks the server then asks once per word, not once per key.
 */
import { X } from "@lucide/vue";
import { computed, onBeforeUnmount, ref, watch, type Component } from "vue";
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
    /** Milliseconds to wait after the last key before `v-model` gets the text (0: at once). */
    debounce?: number;
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
    debounce: 0,
  },
);

const emit = defineEmits<{ enter: [event: KeyboardEvent]; clear: [] }>();

const { t } = useI18n();
const control = useControl(props);
const input = ref<HTMLInputElement | null>(null);

// What the field shows; `model` follows it at once, or once typing pauses with `debounce`.
const text = ref(model.value ?? "");
let timer: ReturnType<typeof setTimeout> | undefined;
function commit(): void {
  clearTimeout(timer);
  timer = undefined;
  if ((model.value ?? "") !== text.value) model.value = text.value;
}
function onInput(event: Event): void {
  if ((event as InputEvent).isComposing) return;
  text.value = (event.target as HTMLInputElement).value;
  // Without `debounce` the model follows each key at once, as v-model does.
  if (!props.debounce) return commit();
  clearTimeout(timer);
  timer = setTimeout(commit, props.debounce);
}
// A change from outside (Back, a cleared filter) shows at once, unless the person is mid-word.
watch(model, (value) => {
  if (timer === undefined) text.value = value ?? "";
});
onBeforeUnmount(() => clearTimeout(timer));

const showClear = computed(() => props.clearable && !!text.value && !control.disabled.value && !props.readonly);

function clear(): void {
  text.value = "";
  commit();
  emit("clear");
  input.value?.focus();
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.isComposing) {
    commit();
    emit("enter", event);
  }
  if (event.key === "Escape" && props.clearable && text.value) {
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
      :value="text"
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
      @input="onInput"
      @compositionend="onInput"
      @keydown="onKeydown"
      @blur="commit"
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
