<script setup lang="ts">
/**
 * An administrator sets a new password for someone who forgot theirs (docs/DAVOMAT.md §1.3,
 * `users/{id}/password/`): the old one stops working at once, and the dialog ends on the new one
 * with Copy, so it can be passed on.
 */
import { Check, Copy, KeyRound } from "@lucide/vue";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { z } from "zod";

import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useForm } from "@/lib/useForm";
import { useCompanyStore } from "@/stores/company";

import { setUserPassword } from "../../api";
import { MIN_LENGTH } from "../../lib/password";
import type { User } from "../../types";
import PasswordField from "../fields/PasswordField.vue";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ user: User | null }>();
const emit = defineEmits<{ saved: [] }>();

const { t } = useI18n();
const company = useCompanyStore();

const schema = z.object({ password: z.string().min(MIN_LENGTH, "davomat.password.tooShort") });
const done = ref<string | null>(null);
const copied = ref(false);

const form = useForm(schema, { password: "" }, {
  onSubmit: async ({ password }) => {
    if (!props.user) return;
    await setUserPassword(company.currentId ?? 0, props.user.id, password);
    done.value = password;
    emit("saved");
  },
});

watch(open, (isOpen) => {
  if (!isOpen) return;
  done.value = null;
  copied.value = false;
  form.reset({ password: "" });
});

const name = () => (props.user ? [props.user.first_name, props.user.last_name].filter(Boolean).join(" ") || props.user.username : "");

async function copy(): Promise<void> {
  if (!done.value) return;
  try {
    await navigator.clipboard.writeText(done.value);
    copied.value = true;
    setTimeout(() => (copied.value = false), 2000);
  } catch {
    // No clipboard: the password is on screen.
  }
}
</script>

<template>
  <UiDialog
    v-model:open="open"
    :title="done ? t('davomat.users.password.doneTitle') : t('davomat.users.password.title', { name: name() })"
    :description="done ? t('davomat.users.password.doneHint', { name: name() }) : t('davomat.users.password.hint')"
    size="sm"
  >
    <div v-if="done" class="flex flex-col items-center gap-4 py-2" data-done>
      <span class="grid size-12 place-items-center rounded-full bg-success-soft text-success"><KeyRound :size="22" /></span>
      <p class="select-all rounded-[10px] border border-line bg-surface-2 px-4 py-2.5 font-mono text-lg font-semibold tracking-wide text-fg" data-password>{{ done }}</p>
    </div>
    <form v-else id="davomat-password-form" class="flex flex-col gap-4" novalidate @submit="form.submit">
      <InlineAlert v-if="form.formError.value" tone="danger" :description="form.formError.value" />
      <FormField :label="t('davomat.users.fields.newPassword')" :error="form.errors.password" required>
        <PasswordField v-model="form.values.password" generator :username="user?.username ?? ''" :invalid="!!form.errors.password" data-field="password" />
      </FormField>
    </form>

    <template #footer>
      <template v-if="done">
        <UiButton variant="ghost" :icon="copied ? Check : Copy" @click="copy">{{ copied ? t("davomat.password.copied") : t("davomat.password.copy") }}</UiButton>
        <UiButton variant="primary" @click="open = false">{{ t("common.done") }}</UiButton>
      </template>
      <template v-else>
        <UiButton variant="ghost" :disabled="form.submitting.value" @click="open = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" type="submit" form="davomat-password-form" :loading="form.submitting.value">{{ t("davomat.users.password.save") }}</UiButton>
      </template>
    </template>
  </UiDialog>
</template>
