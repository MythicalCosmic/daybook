<script setup lang="ts">
/**
 * A lesson's notes in the learning module (extension point `learning.lesson.notes`,
 * docs/PLAN-LEARNING.md §11): the knowledge base's editor for whoever may change the lesson, its
 * prose for everyone else. The lesson editor passes `{ html, editable, placeholder, update,
 * upload }`: `update` takes the edited HTML, `upload` answers a picture (lesson notes take none).
 */
import { computed } from "vue";

import "../prose.css";
import RichEditor from "./editor/RichEditor.vue";

const props = withDefaults(defineProps<{ context?: Record<string, unknown> }>(), { context: () => ({}) });

const html = computed(() => (typeof props.context.html === "string" ? props.context.html : ""));
const editable = computed(() => props.context.editable === true);
const placeholder = computed(() => (typeof props.context.placeholder === "string" ? props.context.placeholder : undefined));
const refuse = async (): Promise<{ id: number; url: string }> => {
  throw new Error("lesson notes take no pictures");
};
const upload = computed(() => (props.context.upload as ((file: File) => Promise<{ id: number; url: string }>) | undefined) ?? refuse);

function update(value: string): void {
  (props.context.update as ((value: string) => void) | undefined)?.(value);
}
</script>

<template>
  <RichEditor v-if="editable" :model-value="html" :upload="upload" :placeholder="placeholder" @update:model-value="update" />
  <!-- eslint-disable-next-line vue/no-v-html -- notes are cleaned by the server (knowledge sanitizer) -->
  <div v-else class="kb-prose text-sm" v-html="html" />
</template>
