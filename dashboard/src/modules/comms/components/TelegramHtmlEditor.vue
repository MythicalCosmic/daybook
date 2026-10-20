<script setup lang="ts">
/**
 * The announcement composer's editor (plan §6.2, C's own component): Tiptap limited to what
 * Telegram shows: bold, italic, underline, strike, link, code and spoiler, paragraphs and line
 * breaks. `v-model` is the editor's HTML; the page turns it into Telegram HTML (and the server
 * cleans it again). Shortcuts: ⌘B, ⌘I, ⌘U, ⌘⇧S (strike), ⌘E (code), ⌘K (link).
 */
import { Mark, mergeAttributes } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { EditorContent, useEditor } from "@tiptap/vue-3";
import { Bold, Code, EyeOff, Italic, Link2, Link2Off, RemoveFormatting, Strikethrough, Underline } from "@lucide/vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiPopover from "@/components/UiPopover.vue";
import UiTooltip from "@/components/UiTooltip.vue";

const model = defineModel<string>({ default: "" });
const props = withDefaults(defineProps<{ placeholder?: string; invalid?: boolean; minHeight?: string }>(), { placeholder: "", invalid: false, minHeight: "180px" });

const { t } = useI18n();

/** Telegram's spoiler: hidden until tapped. Stored as <span class="tg-spoiler">, sent as <tg-spoiler>. */
const Spoiler = Mark.create({
  name: "spoiler",
  parseHTML: () => [{ tag: "tg-spoiler" }, { tag: "span.tg-spoiler" }],
  renderHTML: ({ HTMLAttributes }) => ["span", mergeAttributes(HTMLAttributes, { class: "tg-spoiler" }), 0],
  addKeyboardShortcuts() {
    return { "Mod-Shift-p": () => this.editor.commands.toggleMark(this.name) };
  },
});

const editor = useEditor({
  content: model.value,
  extensions: [
    StarterKit.configure({
      heading: false,
      blockquote: false,
      bulletList: false,
      orderedList: false,
      listItem: false,
      listKeymap: false,
      codeBlock: false,
      horizontalRule: false,
      link: { openOnClick: false, autolink: true, protocols: ["tg", "mailto"], HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" } },
    }),
    Spoiler,
  ],
  editorProps: {
    attributes: { class: "tg-editor", "aria-multiline": "true", role: "textbox" },
    handleKeyDown: (_view, event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openLink();
        return true;
      }
      return false;
    },
  },
  onUpdate: ({ editor: instance }) => {
    model.value = instance.isEmpty ? "" : instance.getHTML();
  },
});

watch(model, (value) => {
  const instance = editor.value;
  if (!instance) return;
  const current = instance.isEmpty ? "" : instance.getHTML();
  if (value !== current) instance.commands.setContent(value || "", { emitUpdate: false });
});

onBeforeUnmount(() => editor.value?.destroy());

const empty = computed(() => !model.value);

type Tool = { key: string; icon: typeof Bold; label: string; shortcut: string; active: () => boolean; run: () => void };
const tools = computed<Tool[]>(() => {
  const e = editor.value;
  return [
    { key: "bold", icon: Bold, label: t("comms.editor.bold"), shortcut: "⌘B", active: () => !!e?.isActive("bold"), run: () => e?.chain().focus().toggleBold().run() },
    { key: "italic", icon: Italic, label: t("comms.editor.italic"), shortcut: "⌘I", active: () => !!e?.isActive("italic"), run: () => e?.chain().focus().toggleItalic().run() },
    { key: "underline", icon: Underline, label: t("comms.editor.underline"), shortcut: "⌘U", active: () => !!e?.isActive("underline"), run: () => e?.chain().focus().toggleUnderline().run() },
    { key: "strike", icon: Strikethrough, label: t("comms.editor.strike"), shortcut: "⌘⇧S", active: () => !!e?.isActive("strike"), run: () => e?.chain().focus().toggleStrike().run() },
    { key: "code", icon: Code, label: t("comms.editor.code"), shortcut: "⌘E", active: () => !!e?.isActive("code"), run: () => e?.chain().focus().toggleCode().run() },
    { key: "spoiler", icon: EyeOff, label: t("comms.editor.spoiler"), shortcut: "⌘⇧P", active: () => !!e?.isActive("spoiler"), run: () => e?.chain().focus().toggleMark("spoiler").run() },
  ];
});

// Links --------------------------------------------------------------------------------------
const linkOpen = ref(false);
const linkUrl = ref("");
function openLink(): void {
  linkOpen.value = true;
}
watch(linkOpen, (value) => {
  if (value) linkUrl.value = (editor.value?.getAttributes("link").href as string | undefined) ?? "";
});
function applyLink(): void {
  const e = editor.value;
  if (!e) return;
  let url = linkUrl.value.trim();
  if (url && !/^(https?:\/\/|tg:\/\/|mailto:)/i.test(url)) url = `https://${url}`;
  if (!url) e.chain().focus().extendMarkRange("link").unsetLink().run();
  else e.chain().focus().extendMarkRange("link").setLink({ href: url }).run();
  linkOpen.value = false;
}
function unlink(): void {
  editor.value?.chain().focus().extendMarkRange("link").unsetLink().run();
}

defineExpose({ focus: () => editor.value?.commands.focus(), insertText: (text: string) => editor.value?.chain().focus().insertContent(text).run() });
</script>

<template>
  <div :class="['ui-control !block !p-0', invalid && 'is-invalid']" :data-invalid="invalid || undefined">
    <div class="flex flex-wrap items-center gap-0.5 border-b border-line px-1.5 py-1" role="toolbar" :aria-label="t('comms.editor.toolbar')">
      <UiTooltip v-for="tool in tools" :key="tool.key" :content="tool.label" :shortcut="tool.shortcut">
        <button
          type="button"
          :class="['grid size-8 place-items-center rounded-[7px] transition-colors', tool.active() ? 'bg-accent-soft text-accent-fg' : 'text-muted hover:bg-highlight hover:text-fg']"
          :aria-label="tool.label"
          :aria-pressed="tool.active()"
          @click="tool.run()"
        >
          <component :is="tool.icon" :size="16" />
        </button>
      </UiTooltip>
      <span class="mx-1 h-5 w-px bg-line" aria-hidden="true" />
      <UiPopover v-model:open="linkOpen" side="bottom" align="start" :padded="false">
        <template #trigger>
          <button
            type="button"
            :class="['grid size-8 place-items-center rounded-[7px] transition-colors', editor?.isActive('link') ? 'bg-accent-soft text-accent-fg' : 'text-muted hover:bg-highlight hover:text-fg']"
            :aria-label="t('comms.editor.link')"
          >
            <Link2 :size="16" />
          </button>
        </template>
        <form class="flex w-[300px] flex-col gap-2 p-3" @submit.prevent="applyLink">
          <label class="text-xs font-medium text-muted" for="tg-link">{{ t("comms.editor.linkLabel") }}</label>
          <TextInput id="tg-link" v-model="linkUrl" type="url" placeholder="https://" autofocus />
          <div class="flex justify-end gap-2">
            <UiButton v-if="editor?.isActive('link')" size="sm" variant="ghost" :icon="Link2Off" @click="unlink(), (linkOpen = false)">{{ t("comms.editor.unlink") }}</UiButton>
            <UiButton size="sm" variant="primary" type="submit">{{ t("common.apply") }}</UiButton>
          </div>
        </form>
      </UiPopover>
      <UiTooltip :content="t('comms.editor.clear')">
        <button type="button" class="grid size-8 place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg" :aria-label="t('comms.editor.clear')" @click="editor?.chain().focus().unsetAllMarks().run()">
          <RemoveFormatting :size="16" />
        </button>
      </UiTooltip>
      <span class="flex-1" />
      <slot name="tools" />
    </div>
    <div class="relative">
      <p v-if="empty" class="pointer-events-none absolute left-3.5 top-3 text-base text-subtle">{{ props.placeholder }}</p>
      <EditorContent :editor="editor" class="tg-editor-wrap" :style="{ '--min-h': minHeight }" />
    </div>
  </div>
</template>

<style scoped>
.tg-editor-wrap :deep(.tg-editor) {
  min-height: var(--min-h);
  max-height: 520px;
  overflow-y: auto;
  padding: 12px 14px;
  outline: none;
  font-size: var(--text-md);
  line-height: 1.55;
  color: var(--c-text);
  white-space: pre-wrap;
  word-break: break-word;
}
.tg-editor-wrap :deep(.tg-editor p) {
  margin: 0;
  min-height: 1.55em;
}
.tg-editor-wrap :deep(.tg-editor a) {
  color: var(--c-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.tg-editor-wrap :deep(.tg-editor code) {
  padding: 1px 5px;
  border-radius: 5px;
  background: var(--c-surface-2);
  font-family: var(--font-mono);
  font-size: 0.9em;
}
.tg-editor-wrap :deep(.tg-editor .tg-spoiler) {
  border-radius: 4px;
  background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--c-text) 14%, transparent) 0 3px, color-mix(in srgb, var(--c-text) 6%, transparent) 3px 6px);
}
</style>
