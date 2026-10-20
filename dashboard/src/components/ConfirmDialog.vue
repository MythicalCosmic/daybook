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
    icon: undefined,
    onConfirm: undefined,
  },
);

const emit = defineEmits<{ confirm: [reason: string]; cancel: [] }>();

const { t } = useI18n();
const text = ref("");
const busy = ref(false);
const touched = ref(false);
let decided = false;

watch(open, (isOpen) => {
  if (isOpen) {
    text.value = "";
    touched.value = false;
    decided = false;
  } else if (!decided) {
    emit("cancel");
  }
});

const missing = computed(() => props.reason === "required" && !text.value.trim());

async function confirm(): Promise<void> {
  touched.value = true;
  if (missing.value || busy.value) return;
  const reason = text.value.trim();
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
        :required="reason === 'required'"
        :optional="reason === 'optional'"
        :error="touched && missing ? t('common.confirm.reasonRequired') : null"
      >
        <TextArea v-model="text" :rows="3" :placeholder="reasonPlaceholder ?? t('common.reasonPlaceholder')" autofocus @submit="confirm" />
      </FormField>
      <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <UiButton variant="ghost" :disabled="busy" @click="open = false">{{ cancelLabel ?? t("common.cancel") }}</UiButton>
        <UiButton type="submit" :variant="tone === 'danger' ? 'danger' : 'primary'" :loading="busy">{{ confirmLabel ?? t("common.confirm") }}</UiButton>
      </div>
    </form>
  </UiDialog>
</template>
