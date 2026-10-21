<script setup lang="ts">
/**
 * Settings → Reminders (plan §6.2 "B (reminder defaults)"): the company's default policy, used by
 * every routine and task without one of its own, edited in place. The Settings page gives it its
 * title and description; changes wait in the sticky bar like every other settings form.
 */
import { ArrowUpRight } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { usePolicies, useSavePolicy } from "../api";
import { emptyDraft, toDraft, toInput } from "../draft";
import PolicyForm, { type PolicyDraft } from "./PolicyForm.vue";

const { t } = useI18n();
const company = useCompanyStore();
const query = usePolicies();
const save = useSavePolicy();
const policy = computed(() => query.data.value?.find((p) => p.is_default) ?? null);
const draft = ref<PolicyDraft>(emptyDraft());
const errors = ref<Record<string, string>>({});
const dirty = computed(() => !!policy.value && JSON.stringify(toInput(draft.value)) !== JSON.stringify(toInput(toDraft(policy.value))));

watch(policy, (value) => value && (draft.value = toDraft(value)), { immediate: true });

async function submit(): Promise<void> {
  if (!policy.value) return;
  try {
    await save.mutateAsync({ id: policy.value.id, input: toInput(draft.value) });
    toast.success(t("reminders.toast.saved"));
    errors.value = {};
  } catch (error) {
    if (isApiError(error)) errors.value = Object.fromEntries(Object.entries(error.fieldErrors).map(([key, messages]) => [key, messages[0] ?? ""]));
  }
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="-mt-2 flex justify-end">
      <UiButton variant="ghost" size="sm" :icon-right="ArrowUpRight" :to="`/c/${company.currentId}/reminders`">{{ t("reminders.defaults.allPolicies") }}</UiButton>
    </div>
    <div v-if="query.isPending.value" class="flex flex-col gap-3"><SkeletonBlock height="120px" radius="12px" /><SkeletonBlock height="200px" radius="12px" /></div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="policy">
      <PolicyForm v-model="draft" :errors="errors" />
      <StickyActionBar :show="dirty" :message="t('common.unsaved')" tone="warning">
        <UiButton variant="ghost" @click="draft = toDraft(policy)">{{ t("common.discard") }}</UiButton>
        <UiButton variant="primary" :loading="save.isPending.value" @click="submit">{{ t("common.save") }}</UiButton>
      </StickyActionBar>
    </template>
  </div>
</template>
