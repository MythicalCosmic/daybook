<script setup lang="ts">
/**
 * The numbers the terminals know a person by (their "Employee No." on the device), as chips. Type
 * a number and press Enter, a comma or a space; a pasted list ("2, 15 31") adds them all; Backspace
 * in the empty field takes the last one back. A number a terminal can't have is refused with a
 * line under the field.
 */
import { ScanFace, X } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { FACE_NUMBER, splitFaceNumbers } from "./team";

const model = defineModel<string[]>({ default: () => [] });
const props = withDefaults(defineProps<{ id?: string; invalid?: boolean; disabled?: boolean }>(), { id: undefined, invalid: false, disabled: false });

const { t } = useI18n();
const draft = ref("");
const refused = ref(false);
const input = ref<HTMLInputElement | null>(null);

const invalid = computed(() => props.invalid || refused.value);

function add(text: string): boolean {
  const numbers = splitFaceNumbers(text);
  if (!numbers.length) return true;
  const bad = numbers.filter((number) => !FACE_NUMBER.test(number));
  refused.value = bad.length > 0;
  const good = numbers.filter((number) => FACE_NUMBER.test(number) && !model.value.includes(number));
  if (good.length) model.value = [...model.value, ...good];
  return bad.length === 0;
}

function commit(): void {
  if (add(draft.value)) draft.value = "";
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "Enter" || event.key === "," || (event.key === " " && draft.value.trim())) {
    event.preventDefault();
    commit();
  } else if (event.key === "Backspace" && !draft.value && model.value.length) {
    model.value = model.value.slice(0, -1);
  }
}

function onPaste(event: ClipboardEvent): void {
  const text = event.clipboardData?.getData("text") ?? "";
  if (!/[\s,;]/.test(text)) return;
  event.preventDefault();
  if (!add(text)) draft.value = text;
}

function remove(number: string): void {
  model.value = model.value.filter((item) => item !== number);
  input.value?.focus();
}
</script>

<template>
  <div>
    <div
      :class="['ui-control flex min-h-[var(--control-h)] flex-wrap items-center gap-1.5 px-2 py-1', disabled && 'pointer-events-none']"
      :data-invalid="invalid || undefined"
      :data-disabled="disabled || undefined"
      @click="input?.focus()"
    >
      <ScanFace :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
      <span v-for="number in model" :key="number" class="ui-chip font-mono tabular-nums" data-face-number>
        {{ number }}
        <button
          type="button"
          class="grid size-4 place-items-center rounded-full text-muted hover:bg-highlight hover:text-fg"
          :aria-label="t('davomat.team.face.remove', { number })"
          @click.stop="remove(number)"
        >
          <X :size="11" />
        </button>
      </span>
      <input
        :id="id"
        ref="input"
        v-model="draft"
        type="text"
        inputmode="numeric"
        autocomplete="off"
        spellcheck="false"
        :disabled="disabled"
        :aria-label="t('davomat.team.face.label')"
        :aria-invalid="invalid || undefined"
        :placeholder="model.length ? '' : t('davomat.team.face.placeholder')"
        class="min-w-[8rem] flex-1 bg-transparent py-0.5 font-mono text-base text-fg outline-none placeholder:font-sans placeholder:text-subtle pointer-coarse:text-md"
        @keydown="onKey"
        @paste="onPaste"
        @blur="commit"
        @input="refused = false"
      />
    </div>
    <p v-if="refused" class="mt-1 text-sm text-danger" role="alert">{{ t("davomat.team.face.invalid") }}</p>
  </div>
</template>
