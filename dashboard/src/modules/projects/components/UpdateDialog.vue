<script setup lang="ts">
/** Post a project update: how it's going (on track, at risk, off track) and a few lines. */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";

import { postUpdate, useCompanyId, useRefreshProjects } from "../api";
import { healthVar } from "../lib";
import { HEALTHS, type Health, type ProjectDetail } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ project: ProjectDetail }>();

const { t } = useI18n();
const companyId = useCompanyId();
const refresh = useRefreshProjects();
const health = ref<Health>("on_track");
const text = ref("");
const saving = ref(false);

watch(open, (value) => {
  if (!value) return;
  health.value = props.project.reported?.health ?? props.project.health ?? "on_track";
  text.value = "";
});

const suggested = computed(() => props.project.health);

async function save(): Promise<void> {
  saving.value = true;
  try {
    await postUpdate(companyId.value, props.project.id, { health: health.value, text: text.value.trim() });
    toast.success(t("projects.updates.posted"));
    open.value = false;
    void refresh();
  } catch {
    // The HTTP layer showed why.
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('projects.updates.newTitle')" :description="`${project.key} · ${project.name}`" size="md">
    <form id="post-update" class="flex flex-col gap-4" @submit.prevent="save">
      <FormField :label="t('projects.updates.how')">
        <div class="grid grid-cols-1 gap-2 sm:grid-cols-3" role="radiogroup" :aria-label="t('projects.updates.how')">
          <button
            v-for="option in HEALTHS"
            :key="option"
            type="button"
            role="radio"
            :aria-checked="health === option"
            class="flex items-center gap-2.5 rounded-[10px] border px-3 py-2.5 text-left transition-colors"
            :class="health === option ? 'border-transparent' : 'border-line hover:bg-highlight'"
            :style="health === option ? { boxShadow: `inset 0 0 0 1.5px ${healthVar(option)}`, backgroundColor: `color-mix(in srgb, ${healthVar(option)} 12%, var(--c-surface))` } : undefined"
            @click="health = option"
          >
            <span class="size-2.5 shrink-0 rounded-full" :style="{ background: healthVar(option) }" />
            <span class="min-w-0">
              <span class="block text-sm font-semibold text-fg">{{ t(`projects.health.${option}`) }}</span>
              <span v-if="suggested === option" class="block text-[11px] text-muted">{{ t("projects.updates.suggested") }}</span>
            </span>
          </button>
        </div>
      </FormField>
      <FormField :label="t('projects.updates.text')" :hint="t('projects.updates.textHint')" :count="text.length" :max="4000" optional>
        <TextArea v-model="text" :rows="5" :maxlength="4000" autofocus :placeholder="t('projects.updates.placeholder')" />
      </FormField>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="post-update" :loading="saving">{{ t("projects.updates.post") }}</UiButton>
    </template>
  </UiDialog>
</template>
