<script setup lang="ts">
/**
 * Whom to call if something happens to them (up to three people): name, who they are to them, and
 * a phone that rings with one tap. hr.manage adds, changes and removes them in place.
 */
import { HeartHandshake, Pencil, Phone, Plus, Trash2 } from "@lucide/vue";
import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { formatPhone } from "@/lib/format";

import { hrApi, useHrMutation } from "../api";
import type { EmergencyContact, EmergencyContactInput } from "../types";

const MAX = 3;

const props = defineProps<{ memberId: number; contacts: EmergencyContact[]; canManage: boolean }>();

const { t } = useI18n();
const confirm = useConfirm();

/** The contact being edited (0 for a new one), or null. */
const editing = ref<number | null>(null);
const form = reactive<EmergencyContactInput>({ name: "", relation: "", phone: "" });
const errors = reactive<Record<string, string | undefined>>({});
const full = computed(() => props.contacts.length >= MAX);

function start(contact: EmergencyContact | null): void {
  for (const key of Object.keys(errors)) delete errors[key];
  Object.assign(form, contact ? { name: contact.name, relation: contact.relation, phone: contact.phone } : { name: "", relation: "", phone: "" });
  editing.value = contact?.id ?? 0;
}

const save = useHrMutation((cid, input: { id: number; body: EmergencyContactInput }) =>
  input.id ? hrApi.updateContact(cid, props.memberId, input.id, input.body) : hrApi.addContact(cid, props.memberId, input.body),
);
const remove = useHrMutation((cid, id: number) => hrApi.removeContact(cid, props.memberId, id));

async function submit(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.name.trim()) errors.name = t("hr.form.required");
  if (!form.phone.trim()) errors.phone = t("hr.form.required");
  if (errors.name || errors.phone) return;
  try {
    await save.mutateAsync({ id: editing.value ?? 0, body: { name: form.name.trim(), relation: form.relation.trim(), phone: form.phone.trim() } });
    toast.success(t("hr.contacts.saved"));
    editing.value = null;
  } catch (failure) {
    if (isApiError(failure)) for (const [field, messages] of Object.entries(failure.fieldErrors)) errors[field] = messages[0];
  }
}

async function drop(contact: EmergencyContact): Promise<void> {
  const answer = await confirm({
    title: t("hr.contacts.removeTitle", { name: contact.name }),
    tone: "danger",
    confirmLabel: t("common.delete"),
    icon: Trash2,
    onConfirm: () => remove.mutateAsync(contact.id),
  });
  if (answer) toast.success(t("hr.contacts.removed"));
}
</script>

<template>
  <section class="ui-card overflow-hidden" data-hr-contacts>
    <header class="flex items-center gap-2 border-b border-line px-5 py-3">
      <HeartHandshake :size="16" class="text-subtle" aria-hidden="true" />
      <h2 class="flex-1 text-md font-semibold text-fg">{{ t("hr.contacts.title") }}</h2>
      <span v-if="contacts.length" class="text-xs text-subtle">{{ contacts.length }}/{{ MAX }}</span>
      <UiButton v-if="canManage && !full && editing === null" size="sm" :icon="Plus" @click="start(null)">{{ t("hr.contacts.add") }}</UiButton>
    </header>

    <EmptyState v-if="!contacts.length && editing === null" size="sm" tone="neutral" :icon="HeartHandshake" :title="t('hr.contacts.emptyTitle')" :description="t('hr.contacts.emptyBody')" />
    <ul v-if="contacts.length" class="divide-y divide-[var(--c-border)]">
      <li v-for="contact in contacts" :key="contact.id" class="flex min-h-14 items-center gap-3 px-5 py-2.5">
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold text-fg">{{ contact.name }}</p>
          <p class="truncate text-xs text-muted">{{ contact.relation || t("hr.contacts.noRelation") }}</p>
        </div>
        <a :href="`tel:${contact.phone}`" class="pressable inline-flex h-10 items-center gap-1.5 rounded-button px-2.5 text-sm font-medium tabular-nums text-fg hover:bg-highlight sm:h-8">
          <Phone :size="14" class="text-subtle" aria-hidden="true" />{{ formatPhone(contact.phone) }}
        </a>
        <template v-if="canManage">
          <IconButton :icon="Pencil" :label="t('common.edit')" @click="start(contact)" />
          <IconButton :icon="Trash2" :label="t('common.delete')" @click="drop(contact)" />
        </template>
      </li>
    </ul>

    <form v-if="editing !== null" class="flex flex-col gap-3 border-t border-line bg-surface-2/40 p-4" @submit.prevent="submit">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('hr.contacts.name')" :error="errors.name" required>
          <TextInput v-model="form.name" :maxlength="120" autofocus :invalid="!!errors.name" />
        </FormField>
        <FormField :label="t('hr.contacts.relation')" :error="errors.relation" optional>
          <TextInput v-model="form.relation" :maxlength="60" :placeholder="t('hr.contacts.relationPlaceholder')" />
        </FormField>
      </div>
      <FormField :label="t('hr.contacts.phone')" :error="errors.phone" required>
        <TextInput v-model="form.phone" type="tel" inputmode="tel" :maxlength="20" placeholder="+998 90 123 45 67" :invalid="!!errors.phone" />
      </FormField>
      <div class="flex justify-end gap-2">
        <UiButton variant="ghost" @click="editing = null">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" type="submit" :loading="save.isPending.value">{{ t("common.save") }}</UiButton>
      </div>
    </form>
  </section>
</template>
