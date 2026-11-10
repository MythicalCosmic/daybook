<script setup lang="ts">
/**
 * A plain editor for a policy's text when the knowledge base's editor isn't available: headings,
 * bold, italic, underline and lists (Tiptap's starter kit). `v-model` is the HTML.
 */
import { Placeholder } from "@tiptap/extensions";
import StarterKit from "@tiptap/starter-kit";
import { EditorContent, useEditor } from "@tiptap/vue-3";
import { Bold, Heading2, Heading3, Italic, List, ListOrdered, Redo2, Underline, Undo2 } from "@lucide/vue";
import { computed, onBeforeUnmount, shallowRef, watch } from "vue";
import { useI18n } from "vue-i18n";

import UiTooltip from "@/components/UiTooltip.vue";
import { useBreakpoints } from "@/lib/useBreakpoints";

import "./policy.css";

const model = defineModel<string>({ default: "" });
const props = withDefaults(defineProps<{ placeholder?: string }>(), { placeholder: undefined });

const { t } = useI18n();
const { isPhone } = useBreakpoints();
const tick = shallowRef(0);

const editor = useEditor({
  content: model.value,
  extensions: [
    StarterKit.configure({ heading: { levels: [2, 3] }, codeBlock: false, code: false, link: false }),
    Placeholder.configure({ placeholder: props.placeholder ?? "" }),
  ],
  editorProps: { attributes: { class: "hr-prose", role: "textbox", "aria-multiline": "true", "aria-label": t("hr.policy.field.text") } },
  onUpdate: ({ editor: current }) => {
    model.value = current.isEmpty ? "" : current.getHTML();
  },
  onTransaction: () => {
    tick.value += 1;
  },
});

watch(model, (html) => {
  const current = editor.value;
  if (!current) return;
  const now = current.isEmpty ? "" : current.getHTML();
  if (html !== now) current.commands.setContent(html || "", { emitUpdate: false });
});
onBeforeUnmount(() => editor.value?.destroy());

type Tool = { key: string; icon: typeof Bold; label: string; active: () => boolean; run: () => void; disabled?: () => boolean };
const tools = computed<Tool[][]>(() => {
  void tick.value;
  const e = editor.value;
  const chain = () => e!.chain().focus();
  return [
    [
      { key: "h2", icon: Heading2, label: t("hr.template.tool.heading"), active: () => !!e?.isActive("heading", { level: 2 }), run: () => chain().toggleHeading({ level: 2 }).run() },
      { key: "h3", icon: Heading3, label: t("hr.template.tool.subheading"), active: () => !!e?.isActive("heading", { level: 3 }), run: () => chain().toggleHeading({ level: 3 }).run() },
    ],
    [
      { key: "bold", icon: Bold, label: t("hr.template.tool.bold"), active: () => !!e?.isActive("bold"), run: () => chain().toggleBold().run() },
      { key: "italic", icon: Italic, label: t("hr.template.tool.italic"), active: () => !!e?.isActive("italic"), run: () => chain().toggleItalic().run() },
      { key: "underline", icon: Underline, label: t("hr.template.tool.underline"), active: () => !!e?.isActive("underline"), run: () => chain().toggleUnderline().run() },
    ],
    [
      { key: "bullets", icon: List, label: t("hr.template.tool.bullets"), active: () => !!e?.isActive("bulletList"), run: () => chain().toggleBulletList().run() },
      { key: "numbers", icon: ListOrdered, label: t("hr.template.tool.numbers"), active: () => !!e?.isActive("orderedList"), run: () => chain().toggleOrderedList().run() },
    ],
    [
      { key: "undo", icon: Undo2, label: t("hr.template.tool.undo"), active: () => false, run: () => chain().undo().run(), disabled: () => !e?.can().undo() },
      { key: "redo", icon: Redo2, label: t("hr.template.tool.redo"), active: () => false, run: () => chain().redo().run(), disabled: () => !e?.can().redo() },
    ],
  ];
});
</script>

<template>
  <div class="flex min-w-0 flex-col">
    <div class="-mx-1 mb-4 flex flex-wrap items-center gap-0.5 rounded-[10px] border border-line bg-surface-2/60 p-1" role="toolbar" :aria-label="t('hr.template.toolbar')">
      <template v-for="(group, index) in tools" :key="index">
        <span v-if="index" class="mx-1 h-5 w-px bg-line" aria-hidden="true" />
        <UiTooltip v-for="tool in group" :key="tool.key" :content="tool.label">
          <button
            type="button"
            :class="['pressable grid place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg disabled:opacity-40', isPhone ? 'size-10' : 'size-8', tool.active() && 'bg-accent-soft text-accent-fg']"
            :aria-label="tool.label"
            :aria-pressed="tool.active()"
            :disabled="tool.disabled?.()"
            @click="tool.run()"
          >
            <component :is="tool.icon" :size="16" />
          </button>
        </UiTooltip>
      </template>
    </div>
    <EditorContent :editor="editor" class="min-w-0" />
  </div>
</template>
