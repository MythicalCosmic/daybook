<script setup lang="ts">
/**
 * A secret typed or pasted once (the current password, its repeat, a bot token): the input with
 * show and hide. New passwords use components/fields/PasswordField.vue (the strength meter and
 * "Suggest a strong password").
 */
import { Eye, EyeOff } from "@lucide/vue";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import TextInput from "@/components/TextInput.vue";

const model = defineModel<string>({ default: "" });

withDefaults(
  defineProps<{ autocomplete?: string; placeholder?: string; invalid?: boolean; disabled?: boolean; id?: string; mono?: boolean }>(),
  { autocomplete: "off", placeholder: undefined, invalid: false, disabled: false, id: undefined, mono: false },
);

const emit = defineEmits<{ blur: [] }>();

const { t } = useI18n();
const visible = ref(false);
</script>

<template>
  <TextInput
    :id="id"
    v-model="model"
    :type="visible ? 'text' : 'password'"
    :autocomplete="autocomplete"
    :placeholder="placeholder"
    :invalid="invalid"
    :disabled="disabled"
    :mono="mono || (visible && !!model)"
    spellcheck="false"
    autocapitalize="none"
    @blur="emit('blur')"
  >
    <template #trailing>
      <button
        type="button"
        class="pressable -mr-1 grid size-7 shrink-0 place-items-center rounded-[6px] text-subtle hover:bg-highlight hover:text-fg"
        :aria-label="visible ? t('davomat.login.hide') : t('davomat.login.show')"
        :aria-pressed="visible"
        :disabled="disabled"
        data-toggle-visibility
        @click.stop="visible = !visible"
      >
        <EyeOff v-if="visible" :size="16" />
        <Eye v-else :size="16" />
      </button>
    </template>
  </TextInput>
</template>
