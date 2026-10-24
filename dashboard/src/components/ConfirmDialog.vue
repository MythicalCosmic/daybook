<script setup lang="ts">
/**
 * "Are you sure?" for actions that matter: delete, void, block, reject, finalize. `reason` asks for
 * a reason ("optional" or "required"); `onConfirm` may be async: the button spins, the dialog closes
 * when it resolves and stays open (the error already toasted) when it throws.
 *
 *   <ConfirmDialog v-model:open="voiding" :title="t('finance.voidTitle')" :message="t('finance.voidBody')"
 *     tone="danger" reason="required" :confirm-label="t('finance.void')" :on-confirm="(reason) => voidTxn(id, reason)" />
 *
 * Or without markup: `const ok = await useConfirm()({ title, tone: "danger" })` (ConfirmHost in App.vue).
 *
 * `reasonChips` offers ready answers above the text (chips first, typing optional: a send-back
 * reason is a tap, not a sentence typed on a phone). A picked chip is the reason; a note typed under
 * it is added after a colon. `reasonOther` is the chip that means "I'll write it": it needs text.
 */
import { CircleAlert, ShieldQuestion } from "@lucide/vue";
import { computed, ref, watch, type Component } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "./FormField.vue";
import TextArea from "./TextArea.vue";
import UiButton from "./UiButton.vue";
import UiDialog from "./UiDialog.vue";

const open = defineModel<boolean>("open", { default: false });

const props = withDefaults(
  defineProps<{
    title: string;
    message?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    tone?: "primary" | "danger";
    reason?: "none" | "optional" | "required";
    reasonLabel?: string;
    reasonPlaceholder?: string;
    /** Ready answers shown as chips above the text. */
    reasonChips?: string[];
    /** The chip that asks for the person's own words (picked, the text is required). */
    reasonOther?: string;
    /** The text's placeholder once a ready answer is picked ("Add a detail, if you like"). */
    reasonNotePlaceholder?: string;
    icon?: Component;
    onConfirm?: (reason: string) => unknown;
  }>(),
  {
    message: undefined,
    confirmLabel: undefined,
    cancelLabel: undefined,
    tone: "primary",
    reason: "none",
    reasonLabel: undefined,
    reasonPlaceholder: undefined,
    reasonChips: () => [],
    reasonOther: undefined,
    reasonNotePlaceholder: undefined,
    icon: undefined,
    onConfirm: undefined,
  },
);

const emit = defineEmits<{ confirm: [reason: string]; cancel: [] }>();

const { t } = useI18n();
const text = ref("");
const chip = ref<string | null>(null);
const busy = ref(false);
const touched = ref(false);
const textArea = ref<InstanceType<typeof TextArea> | null>(null);
let decided = false;

watch(open, (isOpen) => {
  if (isOpen) {
    text.value = "";
    chip.value = null;
    touched.value = false;
    decided = false;
  } else if (!decided) {
    emit("cancel");
  }
});

const chips = computed(() => (props.reason === "none" ? [] : [...props.reasonChips, ...(props.reasonOther ? [props.reasonOther] : [])]));
/** A ready answer is picked: the text becomes an optional detail. */
const readyAnswer = computed(() => chip.value !== null && chip.value !== props.reasonOther);
const missing = computed(() => props.reason === "required" && !readyAnswer.value && !text.value.trim());

function pick(label: string): void {
  chip.value = chip.value === label ? null : label;
  touched.value = false;
  // "Other": straight to typing.
  if (chip.value === props.reasonOther) textArea.value?.focus();
}

/** What the reason says: the picked chip, then the note after a colon; or just what was typed. */
function finalReason(): string {
  const note = text.value.trim();
  if (!readyAnswer.value) return note;
  return note ? `${chip.value}: ${note}` : chip.value!;
}

async function confirm(): Promise<void> {
  touched.value = true;
  if (missing.value || busy.value) return;
  const reason = finalReason();
  if (props.onConfirm) {
    busy.value = true;
    try {
      await props.onConfirm(reason);
    } catch {
      return;
    } finally {
      busy.value = false;
    }
  }
  decided = true;
  emit("confirm", reason);
  open.value = false;
}
</script>

<template>
  <UiDialog v-model:open="open" :title="title" size="sm" :dismissable="!busy" hide-header mobile="sheet">
    <form class="flex flex-col gap-4" @submit.prevent="confirm">
      <div class="flex items-start gap-3.5">
        <span
          :class="['grid size-10 shrink-0 place-items-center rounded-full', tone === 'danger' ? 'bg-danger-soft text-danger' : 'bg-accent-soft text-accent-fg']"
          aria-hidden="true"
        >
          <component :is="icon ?? (tone === 'danger' ? CircleAlert : ShieldQuestion)" :size="19" />
        </span>
        <div class="min-w-0 flex-1 pt-0.5">
          <h2 class="text-md font-semibold leading-6 text-fg">{{ title }}</h2>
          <p v-if="message" class="mt-1 text-base text-muted">{{ message }}</p>
          <slot />
        </div>
      </div>
      <FormField
        v-if="reason !== 'none'"
        :label="reasonLabel ?? t('common.reason')"
        :required="reason === 'required' && !readyAnswer"
        :optional="reason === 'optional' || readyAnswer"
        :error="touched && missing ? t('common.confirm.reasonRequired') : null"
      >
        <div class="flex flex-col gap-2.5">
          <div v-if="chips.length" class="flex flex-wrap gap-1.5" role="group" :aria-label="reasonLabel ?? t('common.reason')" data-testid="reason-chips">
            <button
              v-for="label in chips"
              :key="label"
              type="button"
              :aria-pressed="chip === label"
              :class="[
                'pressable h-8 rounded-full border px-3 text-sm transition-colors',
                chip === label ? 'border-primary bg-accent-soft font-semibold text-accent-fg' : 'border-line bg-surface text-fg hover:bg-highlight',
              ]"
              @click="pick(label)"
            >
              {{ label }}
            </button>
          </div>
          <TextArea
            ref="textArea"
            v-model="text"
            :rows="chips.length ? 2 : 3"
            :placeholder="readyAnswer ? (reasonNotePlaceholder ?? t('common.reasonNotePlaceholder')) : (reasonPlaceholder ?? t('common.reasonPlaceholder'))"
            :autofocus="!chips.length"
            @submit="confirm"
          />
        </div>
      </FormField>
      <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <UiButton variant="ghost" :disabled="busy" @click="open = false">{{ cancelLabel ?? t("common.cancel") }}</UiButton>
        <UiButton type="submit" :variant="tone === 'danger' ? 'danger' : 'primary'" :loading="busy">{{ confirmLabel ?? t("common.confirm") }}</UiButton>
      </div>
    </form>
  </UiDialog>
</template>
