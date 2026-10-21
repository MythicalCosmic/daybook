<script setup lang="ts">
/**
 * "How to do this": link the page to a routine or a task, so whoever does it finds the page from
 * the task. Routines come first (a page usually explains a recurring job).
 */
import { Check, ListTodo, Repeat, Search } from "@lucide/vue";
import { refDebounced } from "@vueuse/core";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { knowledgeApi, usePutPage, useRefresh, useTargets } from "../api";
import type { PageDetail, Target } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ page: PageDetail }>();

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const putPage = usePutPage();
const query = ref("");
const debounced = refDebounced(query, 200);
const targets = useTargets(debounced, open);
const busy = ref<string | null>(null);

watch(open, (isOpen) => {
  if (isOpen) query.value = "";
});

const linked = computed(() => new Set(props.page.links.map((link) => `${link.target_type}:${link.target_id}`)));

async function link(target: Target): Promise<void> {
  const key = `${target.type}:${target.id}`;
  if (linked.value.has(key)) return;
  busy.value = key;
  try {
    await knowledgeApi.link(company.currentId ?? 0, props.page.id, target.type, target.id);
    putPage(await knowledgeApi.page(company.currentId ?? 0, props.page.id));
    void refresh();
    toast.success(t("knowledge.links.linked", { name: target.title }));
    open.value = false;
  } catch {
    // Shown by the HTTP layer.
  } finally {
    busy.value = null;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('knowledge.links.dialogTitle')" :description="t('knowledge.links.dialogHint')" size="md">
    <div class="flex flex-col gap-3">
      <TextInput v-model="query" type="search" :icon="Search" :placeholder="t('knowledge.links.search')" autofocus clearable />
      <div v-if="targets.isPending.value" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 4" :key="n" height="44px" radius="8px" /></div>
      <EmptyState v-else-if="!(targets.data.value ?? []).length" size="sm" tone="neutral" :icon="Search" :title="t('knowledge.links.none')" :description="t('knowledge.links.noneHint')" />
      <ul v-else class="flex max-h-[360px] flex-col overflow-y-auto">
        <li v-for="target in targets.data.value" :key="`${target.type}:${target.id}`">
          <button
            type="button"
            class="flex w-full items-center gap-3 rounded-[8px] px-2 py-2 text-left hover:bg-highlight disabled:opacity-60"
            :disabled="busy !== null || linked.has(`${target.type}:${target.id}`)"
            @click="link(target)"
          >
            <span :class="['grid size-8 shrink-0 place-items-center rounded-[8px]', target.type === 'routine' ? 'bg-info-soft text-info' : 'bg-accent-soft text-accent-fg']" aria-hidden="true">
              <Repeat v-if="target.type === 'routine'" :size="15" />
              <ListTodo v-else :size="15" />
            </span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-semibold text-fg">{{ target.title }}</span>
              <span class="block text-xs text-muted">{{ t(`knowledge.links.${target.type}`) }} · {{ target.subtitle }}</span>
            </span>
            <Check v-if="linked.has(`${target.type}:${target.id}`)" :size="16" class="shrink-0 text-success" :aria-label="t('knowledge.links.already')" />
          </button>
        </li>
      </ul>
    </div>
  </UiDialog>
</template>
