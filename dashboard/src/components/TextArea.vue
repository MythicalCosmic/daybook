<script setup lang="ts">
/**
 * Multi-line text. Grows with its content between `rows` and `maxRows` (then scrolls). ⌘/Ctrl+Enter
 * emits `submit`, so a comment box can send without a button press.
 */
import { nextTick, onMounted, ref, watch } from "vue";

import { controlState, useControl } from "./field";

defineOptions({ inheritAttrs: false });

const model = defineModel<string | null>({ default: "" });

const props = withDefaults(
  defineProps<{
    placeholder?: string;
    rows?: number;
    maxRows?: number;
    autosize?: boolean;
    disabled?: boolean;
    readonly?: boolean;
    invalid?: boolean;
    id?: string;
    maxlength?: number;
    autofocus?: boolean;
  }>(),
  { placeholder: undefined, rows: 3, maxRows: 12, autosize: true, disabled: false, readonly: false, invalid: false, id: undefined, maxlength: undefined, autofocus: false },
);

const emit = defineEmits<{ submit: [] }>();

const control = useControl(props);
const area = ref<HTMLTextAreaElement | null>(null);

function resize(): void {
  const el = area.value;
  if (!el || !props.autosize) return;
  const style = getComputedStyle(el);
  const line = parseFloat(style.lineHeight) || 20;
  const padding = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
  el.style.height = "auto";
  const max = line * props.maxRows + padding;
  const min = line * props.rows + padding;
  el.style.height = `${Math.min(max, Math.max(min, el.scrollHeight))}px`;
  el.style.overflowY = el.scrollHeight > max ? "auto" : "hidden";
}

watch(model, () => nextTick(resize));
onMounted(resize);

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    event.preventDefault();
    emit("submit");
  }
}

defineExpose({ focus: () => area.value?.focus(), el: area });
</script>

<template>
  <div
    :class="['ui-control !items-stretch !px-0', $attrs.class]"
    :style="$attrs.style as never"
    v-bind="controlState({ invalid: control.invalid.value, disabled: control.disabled.value, readonly })"
  >
    <textarea
      :id="control.id.value"
      ref="area"
      v-model="model"
      :rows="rows"
      class="ui-input resize-none px-2.5 py-[7px] leading-5"
      :placeholder="placeholder"
      :disabled="control.disabled.value"
      :readonly="readonly"
      :maxlength="maxlength"
      :autofocus="autofocus"
      :required="control.required.value || undefined"
      :aria-invalid="control.invalid.value || undefined"
      :aria-describedby="control.describedBy.value"
      v-bind="{ ...$attrs, class: undefined, style: undefined }"
      @keydown="onKeydown"
    />
  </div>
</template>
