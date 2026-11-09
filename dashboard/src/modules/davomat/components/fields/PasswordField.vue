<script setup lang="ts">
/**
 * A new password: the field with show/hide, a four-step strength meter under it, and (for admins
 * setting someone else's) "Suggest a strong password" with a copy button. The server's validators
 * decide; the meter only helps.
 */
import { Check, Copy, Eye, EyeOff, LockKeyhole, Sparkles } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import TextInput from "@/components/TextInput.vue";
import { toast } from "@/components/useToast";

import { generatePassword, passwordStrength, STRENGTH_KEYS, strengthTone } from "../../lib/password";

const props = withDefaults(
  defineProps<{ username?: string; generator?: boolean; invalid?: boolean; autocomplete?: string; id?: string; size?: "md" | "lg"; meter?: boolean }>(),
  { username: "", generator: false, invalid: false, autocomplete: "new-password", id: undefined, size: "md", meter: true },
);
const model = defineModel<string>({ default: "" });

const { t } = useI18n();
const reveal = ref(false);
const copied = ref(false);
const input = ref<InstanceType<typeof TextInput> | null>(null);

const score = computed(() => passwordStrength(model.value, props.username));
const tone = computed(() => strengthTone(score.value));
const label = computed(() => (model.value ? t(`davomat.password.strength.${STRENGTH_KEYS[score.value]}`) : ""));
const barClass: Record<ReturnType<typeof strengthTone>, string> = { danger: "bg-danger", warning: "bg-warning", info: "bg-info", success: "bg-success" };
const textClass: Record<ReturnType<typeof strengthTone>, string> = { danger: "text-danger", warning: "text-warning", info: "text-info", success: "text-success" };

function suggest(): void {
  model.value = generatePassword();
  reveal.value = true;
  copied.value = false;
}

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(model.value);
    copied.value = true;
    toast.success(t("davomat.password.copied"));
    setTimeout(() => (copied.value = false), 1800);
  } catch {
    input.value?.select();
  }
}

defineExpose({ focus: () => input.value?.focus() });
</script>

<template>
  <div class="flex flex-col gap-2">
    <TextInput
      :id="id"
      ref="input"
      v-model="model"
      :size="size"
      :type="reveal ? 'text' : 'password'"
      :icon="LockKeyhole"
      :autocomplete="autocomplete"
      :invalid="invalid"
      :mono="reveal && generator"
      spellcheck="false"
      autocapitalize="none"
    >
      <template #trailing>
        <button
          v-if="generator && model"
          type="button"
          class="pressable grid size-8 shrink-0 place-items-center rounded-[8px] text-muted hover:bg-highlight hover:text-fg"
          :aria-label="t('davomat.password.copy')"
          @click.stop="copy"
        >
          <Check v-if="copied" :size="16" class="text-success" />
          <Copy v-else :size="16" />
        </button>
        <button
          type="button"
          class="pressable -mr-1 grid size-8 shrink-0 place-items-center rounded-[8px] text-muted hover:bg-highlight hover:text-fg"
          :aria-label="reveal ? t('davomat.login.hide') : t('davomat.login.show')"
          :aria-pressed="reveal"
          @click.stop="reveal = !reveal"
        >
          <EyeOff v-if="reveal" :size="16" />
          <Eye v-else :size="16" />
        </button>
      </template>
    </TextInput>
    <div v-if="meter || generator" class="flex items-center gap-3">
      <div v-if="meter" class="flex flex-1 items-center gap-1.5" :aria-label="label || undefined" role="meter" :aria-valuenow="score" aria-valuemin="0" aria-valuemax="4">
        <span v-for="step in 4" :key="step" :class="['h-1.5 flex-1 rounded-full transition-colors duration-200', model && step <= score ? barClass[tone] : 'bg-surface-3']" />
      </div>
      <span v-if="meter && label" :class="['w-[68px] shrink-0 text-right text-xs font-semibold', textClass[tone]]">{{ label }}</span>
      <button
        v-if="generator"
        type="button"
        class="pressable inline-flex shrink-0 items-center gap-1.5 rounded-[8px] px-2 py-1 text-xs font-semibold text-primary hover:bg-accent-soft"
        @click="suggest"
      >
        <Sparkles :size="13" aria-hidden="true" />
        {{ t("davomat.password.generate") }}
      </button>
    </div>
  </div>
</template>
