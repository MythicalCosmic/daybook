<script setup lang="ts">
/**
 * "Who is number 00000002?": link a terminal's number to a Daybook person. The closest names come
 * first as one-tap choices (the terminal often holds only a first name, in either script); anyone
 * else is a search away. Earlier scans of the number count for the person from then on.
 */
import { Check } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";

import { useLink } from "../api";
import type { Suggestion } from "../types";
import Snapshot from "./Snapshot.vue";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ employeeNo: string; nameOnDevice?: string; photoUrl?: string | null; suggestions?: Suggestion[] }>(), {
  nameOnDevice: "",
  photoUrl: null,
  suggestions: () => [],
});

const { t } = useI18n();
const link = useLink();
const picked = ref<number | null>(null);

watch(
  open,
  (value) => {
    if (value) picked.value = props.suggestions[0]?.member.id ?? null;
  },
  { immediate: true },
);

const title = computed(() => t("faceid.people.whoIs", { number: props.employeeNo }));

async function save(memberId: number | null = picked.value): Promise<void> {
  if (!memberId) return;
  await link.mutateAsync({ employeeNo: props.employeeNo, memberId });
  toast.success(t("faceid.people.linked"));
  open.value = false;
}
</script>

<template>
  <UiDialog v-model:open="open" size="md" :title="title" :description="nameOnDevice ? t('faceid.people.onDevice', { name: nameOnDevice }) : undefined">
    <div class="flex flex-col gap-4 pt-1">
      <div class="flex items-center gap-3">
        <Snapshot :src="photoUrl" :name="nameOnDevice || employeeNo" :size="56" ring="var(--c-warning)" />
        <div class="min-w-0">
          <p class="truncate text-sm font-semibold text-fg">{{ nameOnDevice || t("faceid.feed.number", { number: employeeNo }) }}</p>
          <p class="text-xs text-muted">{{ t("faceid.feed.number", { number: employeeNo }) }}</p>
        </div>
      </div>

      <div v-if="suggestions.length" class="flex flex-col gap-2">
        <p class="text-xs font-medium uppercase tracking-wide text-subtle">{{ t("faceid.people.suggestions") }}</p>
        <div class="flex flex-col gap-1.5">
          <button
            v-for="suggestion in suggestions"
            :key="suggestion.member.id"
            type="button"
            :class="[
              'flex items-center gap-3 rounded-[10px] border px-3 py-2 text-left transition-colors duration-150',
              picked === suggestion.member.id ? 'border-[var(--c-primary)] bg-accent-soft' : 'border-line hover:bg-highlight',
            ]"
            @click="picked = suggestion.member.id"
            @dblclick="save(suggestion.member.id)"
          >
            <UserAvatar :name="suggestion.member.name" :src="suggestion.member.photo_url" :size="32" />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-medium text-fg">{{ suggestion.member.name }}</span>
              <span class="block truncate text-xs text-muted">
                {{ suggestion.member.position?.name ?? "" }}<template v-if="suggestion.has_number"> · {{ t("faceid.people.hasNumber") }}</template>
              </span>
            </span>
            <span class="text-xs tabular-nums text-subtle">{{ suggestion.score }}%</span>
            <Check v-if="picked === suggestion.member.id" :size="16" class="text-[var(--c-primary)]" aria-hidden="true" />
          </button>
        </div>
      </div>

      <FormField :label="suggestions.length ? t('faceid.people.someoneElse') : t('faceid.people.person')">
        <PersonPicker v-model="picked" :placeholder="t('faceid.people.pick')" clearable />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="Check" :disabled="!picked" :loading="link.isPending.value" @click="save()">{{ t("faceid.people.link") }}</UiButton>
    </template>
  </UiDialog>
</template>
