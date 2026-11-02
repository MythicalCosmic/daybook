<script setup lang="ts">
/**
 * A contract template's text (Tiptap 3): headings, bold, italic, underline and lists, plus the
 * placeholder chips that put `{{employee_full_name}}` and the rest (plan §3.11's fixed list) where
 * the cursor is. Placeholders are tinted in the text; an unknown one (a typo) is tinted red, since
 * the server would print it as written. "HTML" shows the source for pasting a lawyer's text.
 * `v-model` is the HTML; the server sanitizes it again.
 */
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import StarterKit from "@tiptap/starter-kit";
import { EditorContent, useEditor } from "@tiptap/vue-3";
import { Bold, Braces, Code2, Heading2, Heading3, Italic, List, ListOrdered, LockKeyhole, Redo2, Underline, Undo2 } from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from "vue";
import { useI18n } from "vue-i18n";

import TextArea from "@/components/TextArea.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { useBreakpoints } from "@/lib/useBreakpoints";

import { insertPlaceholder, PLACEHOLDERS, token } from "../lib";
import "../contract.css";

const model = defineModel<string>({ default: "" });
withDefaults(defineProps<{ invalid?: boolean }>(), { invalid: false });

const { t } = useI18n();
const { isPhone } = useBreakpoints();
const source = ref(false);
const tick = shallowRef(0);

const TOKEN = /\{\{\s*([a-z_]+)\s*\}\}/g;

/** Tints every `{{placeholder}}` in the text; unknown ones in red. */
const PlaceholderTint = Extension.create({
  name: "placeholderTint",
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey("placeholderTint"),
        props: {
          decorations(state) {
            const marks: Decoration[] = [];
            state.doc.descendants((node, pos) => {
              if (!node.isText || !node.text) return;
              for (const match of node.text.matchAll(TOKEN)) {
                const from = pos + (match.index ?? 0);
                const known = (PLACEHOLDERS as readonly string[]).includes(match[1]!);
                marks.push(Decoration.inline(from, from + match[0].length, { class: known ? "hr-token" : "hr-token hr-token-unknown" }));
              }
            });
            return DecorationSet.create(state.doc, marks);
          },
        },
      }),
    ];
  },
});

const editor = useEditor({
  content: model.value,
  extensions: [
    StarterKit.configure({ heading: { levels: [1, 2, 3] }, codeBlock: false, code: false, blockquote: false, link: false }),
    PlaceholderTint,
  ],
  editorProps: { attributes: { class: "hr-paper hr-paper-edit", role: "textbox", "aria-multiline": "true", "aria-label": t("hr.template.body") } },
  onUpdate: ({ editor: current }) => {
    model.value = current.isEmpty ? "" : current.getHTML();
  },
  onTransaction: () => {
    tick.value += 1;
  },
});

// An outside change (loading the template, the HTML view) replaces the document.
watch(model, (html) => {
  const current = editor.value;
  if (!current || source.value) return;
  const now = current.isEmpty ? "" : current.getHTML();
  if (html !== now) current.commands.setContent(html || "", { emitUpdate: false });
});
watch(source, (on) => {
  if (!on) editor.value?.commands.setContent(model.value || "", { emitUpdate: false });
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

// Placeholders --------------------------------------------------------------------------------
const area = ref<InstanceType<typeof TextArea> | null>(null);

async function insert(key: string): Promise<void> {
  if (!source.value) {
    editor.value?.chain().focus().insertContent(token(key)).run();
    return;
  }
  const el = area.value?.el as HTMLTextAreaElement | null | undefined;
  const text = model.value ?? "";
  const next = insertPlaceholder(text, el?.selectionStart ?? text.length, el?.selectionEnd ?? text.length, key);
  model.value = next.text;
  await nextTick();
  el?.focus();
  el?.setSelectionRange(next.caret, next.caret);
}

defineExpose({ insert });
</script>

<template>
  <div :class="['flex min-w-0 flex-col overflow-hidden rounded-card border bg-surface', invalid ? 'border-danger' : 'border-line']">
    <div class="flex flex-wrap items-center gap-0.5 border-b border-line bg-surface-2/60 p-1" role="toolbar" :aria-label="t('hr.template.toolbar')">
      <template v-for="(group, index) in tools" :key="index">
        <span v-if="index" class="mx-1 h-5 w-px bg-line" aria-hidden="true" />
        <UiTooltip v-for="tool in group" :key="tool.key" :content="tool.label">
          <button
            type="button"
            :class="[
              'pressable grid place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg disabled:opacity-40',
              isPhone ? 'size-10' : 'size-8',
              tool.active() && 'bg-accent-soft text-accent-fg',
            ]"
            :aria-label="tool.label"
            :aria-pressed="tool.active()"
            :disabled="source || tool.disabled?.()"
            @click="tool.run()"
          >
            <component :is="tool.icon" :size="16" />
          </button>
        </UiTooltip>
      </template>
      <span class="flex-1" />
      <button
        type="button"
        :class="['pressable inline-flex items-center gap-1.5 rounded-[7px] px-2.5 text-xs font-semibold', isPhone ? 'h-10' : 'h-8', source ? 'bg-accent-soft text-accent-fg' : 'text-muted hover:bg-highlight hover:text-fg']"
        :aria-pressed="source"
        @click="source = !source"
      >
        <Code2 :size="15" />HTML
      </button>
    </div>

    <!-- The placeholder chips: a tap puts the value's name where the cursor is. -->
    <div class="flex flex-wrap items-center gap-1.5 border-b border-line px-3 py-2.5" :aria-label="t('hr.template.placeholders')" role="group">
      <span class="mr-1 inline-flex items-center gap-1 text-xs font-semibold text-muted"><Braces :size="13" aria-hidden="true" />{{ t("hr.template.insert") }}</span>
      <button
        v-for="key in PLACEHOLDERS"
        :key="key"
        type="button"
        class="pressable inline-flex h-8 items-center gap-1 rounded-full border border-[color-mix(in_srgb,var(--c-primary)_30%,transparent)] bg-accent-soft px-2.5 text-xs font-semibold text-accent-fg hover:border-[var(--c-primary)] pointer-coarse:h-9"
        :title="token(key)"
        @mousedown.prevent
        @click="insert(key)"
      >
        <LockKeyhole v-if="key === 'salary_text'" :size="12" aria-hidden="true" />{{ t(`hr.placeholder.${key}`) }}
      </button>
    </div>

    <TextArea v-if="source" ref="area" v-model="model" :rows="18" :max-rows="40" class="!rounded-none !border-0 font-mono text-sm" :aria-label="t('hr.template.body')" />
    <EditorContent v-else :editor="editor" class="min-w-0 px-4 py-4 sm:px-6" />
  </div>
</template>
