<script setup lang="ts">
/**
 * Where a policy's text is written: the knowledge base's editor (extension point `hr.policy.body`:
 * headings, lists, checklists, callouts, tables, links; no pictures, a policy's go in its file),
 * or a plain editor when the knowledge base isn't there. `v-model` is the HTML; the server cleans
 * it before storing.
 */
import { computed, ref } from "vue";

import ExtensionSlot from "@/components/ExtensionSlot.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { hasExtension } from "@/core/extensions";
import { findModule } from "@/core/modules";
import { ensureModuleMessages } from "@/i18n";
import { useCompanyStore } from "@/stores/company";

import PolicyPlainEditor from "./PolicyPlainEditor.vue";

const model = defineModel<string>({ default: "" });
const props = withDefaults(defineProps<{ placeholder?: string; invalid?: boolean }>(), { placeholder: undefined, invalid: false });

const company = useCompanyStore();
const rich = computed(() => hasExtension("hr.policy.body", company.current));

// The knowledge base's toolbar speaks its own words: they load with the editor.
const knowledge = findModule("knowledge");
const ready = ref(!knowledge);
if (knowledge) {
  void ensureModuleMessages(knowledge)
    .catch(() => undefined)
    .finally(() => (ready.value = true));
}

const context = computed(() => ({
  html: model.value,
  editable: true,
  placeholder: props.placeholder,
  update: (value: string) => (model.value = value),
}));
</script>

<template>
  <div :class="['min-w-0 rounded-card border bg-surface px-4 pb-5 pt-3 sm:px-6', invalid ? 'border-danger' : 'border-line']" data-policy-text>
    <template v-if="rich">
      <ExtensionSlot v-if="ready" name="hr.policy.body" :context="context" class="[--kb-toolbar-top:8px]" />
      <div v-else class="flex flex-col gap-3 py-2" aria-hidden="true"><SkeletonBlock height="32px" /><SkeletonBlock :lines="6" /></div>
    </template>
    <PolicyPlainEditor v-else v-model="model" :placeholder="placeholder" />
  </div>
</template>
