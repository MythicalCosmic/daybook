<script setup lang="ts">
/**
 * The page editor (Tiptap 3): a sticky toolbar for headings, marks, links, lists, checklists,
 * quotes, callouts, tables, pictures and dividers, and the document below it in the same styles as
 * the reading view. Pictures upload through `upload` (re-encoded and kept private by the server),
 * also when pasted or dropped. `v-model` is the HTML; the server cleans it before storing.
 */
import {
  Bold,
  ChevronDown,
  Code,
  Columns3,
  Heading2,
  ImagePlus,
  Italic,
  Lightbulb,
  Link2,
  List,
  ListChecks,
  ListOrdered,
  Minus,
  Redo2,
  Rows3,
  Strikethrough,
  Table2,
  TextQuote,
  Trash2,
  Underline,
  Undo2,
} from "@lucide/vue";
import { EditorContent, useEditor } from "@tiptap/vue-3";
import { computed, onBeforeUnmount, ref, shallowRef, watch } from "vue";
import { useI18n } from "vue-i18n";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import IconButton from "@/components/IconButton.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiPopover from "@/components/UiPopover.vue";
import UiSpinner from "@/components/UiSpinner.vue";
import { toast } from "@/components/useToast";

import "../../prose.css";
import { buildExtensions, CALLOUT_TONES, inTable, type CalloutTone, type TableCommand } from "./extensions";

const model = defineModel<string>({ default: "" });
const props = withDefaults(defineProps<{ upload: (file: File) => Promise<{ id: number; url: string }>; placeholder?: string; autofocus?: boolean }>(), {
  placeholder: undefined,
  autofocus: false,
});

const { t } = useI18n();
const uploading = ref(0);
const fileInput = ref<HTMLInputElement | null>(null);
// Bumped on every transaction, so the toolbar's active states follow the cursor.
const tick = shallowRef(0);

const editor = useEditor({
  content: model.value,
  extensions: buildExtensions(props.placeholder ?? t("knowledge.editor.placeholder")),
  autofocus: props.autofocus ? "end" : false,
  editorProps: {
    attributes: { class: "kb-prose", "aria-label": t("knowledge.editor.body"), role: "textbox", "aria-multiline": "true" },
    handlePaste: (_view, event) => takeImages(event.clipboardData?.files),
    handleDrop: (_view, event) => takeImages((event as DragEvent).dataTransfer?.files),
  },
  onUpdate: ({ editor: current }) => {
    model.value = current.isEmpty ? "" : current.getHTML();
  },
  onTransaction: () => {
    tick.value += 1;
  },
});

// An outside change (a restored version, a reload) replaces the document.
watch(model, (html) => {
  const current = editor.value;
  if (!current) return;
  const now = current.isEmpty ? "" : current.getHTML();
  if (html !== now) current.commands.setContent(html || "", { emitUpdate: false });
});

onBeforeUnmount(() => editor.value?.destroy());

function takeImages(files: FileList | null | undefined): boolean {
  const images = Array.from(files ?? []).filter((file) => file.type.startsWith("image/"));
  if (!images.length) return false;
  for (const file of images) void addImage(file);
  return true;
}

async function addImage(file: File): Promise<void> {
  if (file.size > 20 * 1024 * 1024) {
    toast.error(t("knowledge.editor.imageTooBig"));
    return;
  }
  uploading.value += 1;
  try {
    const image = await props.upload(file);
    editor.value?.chain().focus().insertImage({ id: image.id, src: image.url, alt: file.name.replace(/\.[^.]+$/, "") }).run();
  } catch {
    // The HTTP layer showed the server's reason.
  } finally {
    uploading.value -= 1;
  }
}

function onFile(event: Event): void {
  const input = event.target as HTMLInputElement;
  takeImages(input.files);
  input.value = "";
}

const is = (name: string, attrs?: Record<string, unknown>) => {
  void tick.value;
  return editor.value?.isActive(name, attrs) ?? false;
};

const blockLabel = computed(() => {
  void tick.value;
  if (is("heading", { level: 2 })) return t("knowledge.editor.h2");
  if (is("heading", { level: 3 })) return t("knowledge.editor.h3");
  if (is("heading", { level: 4 })) return t("knowledge.editor.h4");
  return t("knowledge.editor.paragraph");
});

const blockMenu = computed<MenuEntry[]>(() => [
  { label: t("knowledge.editor.paragraph"), onSelect: () => editor.value?.chain().focus().setParagraph().run() },
  { label: t("knowledge.editor.h2"), shortcut: "##", onSelect: () => editor.value?.chain().focus().toggleHeading({ level: 2 }).run() },
  { label: t("knowledge.editor.h3"), shortcut: "###", onSelect: () => editor.value?.chain().focus().toggleHeading({ level: 3 }).run() },
  { label: t("knowledge.editor.h4"), onSelect: () => editor.value?.chain().focus().toggleHeading({ level: 4 }).run() },
  { label: t("knowledge.editor.codeBlock"), icon: Code, onSelect: () => editor.value?.chain().focus().toggleCodeBlock().run() },
]);

const calloutMenu = computed<MenuEntry[]>(() => {
  void tick.value;
  const inCallout = is("callout");
  const entries: MenuEntry[] = CALLOUT_TONES.map((tone: CalloutTone) => ({
    label: t(`knowledge.callout.${tone}`),
    onSelect: () => {
      const chain = editor.value?.chain().focus();
      if (!chain) return;
      if (inCallout) chain.setCalloutTone(tone).run();
      else chain.setCallout(tone).run();
    },
  }));
  if (inCallout) entries.push({ label: t("knowledge.callout.remove"), icon: Trash2, danger: true, onSelect: () => editor.value?.chain().focus().unsetCallout().run() });
  return entries;
});

const tableActive = computed(() => {
  void tick.value;
  return editor.value ? inTable(editor.value) : false;
});

function table(command: TableCommand): void {
  editor.value?.chain().focus().tableCommand(command).run();
}

// Links: a small popover with the address.
const linkOpen = ref(false);
const linkUrl = ref("");
watch(linkOpen, (open) => {
  if (open) linkUrl.value = (editor.value?.getAttributes("link").href as string | undefined) ?? "";
});

function applyLink(): void {
  const url = linkUrl.value.trim();
  const chain = editor.value?.chain().focus().extendMarkRange("link");
  if (!chain) return;
  if (!url) chain.unsetLink().run();
  else chain.setLink({ href: /^(https?:|mailto:|tel:)/i.test(url) ? url : `https://${url}` }).run();
  linkOpen.value = false;
}

defineExpose({ focus: () => editor.value?.commands.focus("end") });
</script>

<template>
  <div class="kb-editor flex min-w-0 flex-col">
    <div
      class="sticky top-[var(--kb-toolbar-top,0px)] z-10 -mx-1 mb-5 flex flex-wrap items-center gap-0.5 rounded-[10px] border border-line bg-surface/95 p-1 shadow-xs backdrop-blur"
      role="toolbar"
      :aria-label="t('knowledge.editor.toolbar')"
    >
      <DropdownMenu :items="blockMenu" align="start" width="200px">
        <template #trigger>
          <button type="button" class="pressable inline-flex h-7 items-center gap-1 rounded-[7px] px-2 text-sm font-medium text-fg hover:bg-highlight" :aria-label="t('knowledge.editor.textStyle')">
            <Heading2 :size="15" class="text-muted" />
            <span class="max-w-[110px] truncate">{{ blockLabel }}</span>
            <ChevronDown :size="13" class="text-subtle" />
          </button>
        </template>
      </DropdownMenu>
      <span class="mx-1 h-5 w-px bg-line" aria-hidden="true" />
      <IconButton :icon="Bold" :label="t('knowledge.editor.bold')" shortcut="mod+b" size="sm" :active="is('bold')" @click="editor?.chain().focus().toggleBold().run()" />
      <IconButton :icon="Italic" :label="t('knowledge.editor.italic')" shortcut="mod+i" size="sm" :active="is('italic')" @click="editor?.chain().focus().toggleItalic().run()" />
      <IconButton :icon="Underline" :label="t('knowledge.editor.underline')" shortcut="mod+u" size="sm" :active="is('underline')" @click="editor?.chain().focus().toggleUnderline().run()" />
      <IconButton :icon="Strikethrough" :label="t('knowledge.editor.strike')" size="sm" :active="is('strike')" @click="editor?.chain().focus().toggleStrike().run()" />
      <IconButton :icon="Code" :label="t('knowledge.editor.code')" size="sm" :active="is('code')" @click="editor?.chain().focus().toggleCode().run()" />
      <UiPopover v-model:open="linkOpen" width="300px" align="start">
        <template #trigger>
          <IconButton :icon="Link2" :label="t('knowledge.editor.link')" shortcut="mod+k" size="sm" :active="is('link')" />
        </template>
        <form class="flex flex-col gap-2" @submit.prevent="applyLink">
          <label class="text-xs font-semibold text-muted" for="kb-link-url">{{ t("knowledge.editor.linkUrl") }}</label>
          <TextInput id="kb-link-url" v-model="linkUrl" type="url" placeholder="https://" autofocus />
          <div class="flex justify-end gap-2">
            <UiButton v-if="is('link')" size="sm" variant="ghost" @click="linkUrl = ''; applyLink()">{{ t("knowledge.editor.unlink") }}</UiButton>
            <UiButton size="sm" variant="primary" type="submit">{{ t("common.apply") }}</UiButton>
          </div>
        </form>
      </UiPopover>
      <span class="mx-1 h-5 w-px bg-line" aria-hidden="true" />
      <IconButton :icon="List" :label="t('knowledge.editor.bullets')" size="sm" :active="is('bulletList')" @click="editor?.chain().focus().toggleBulletList().run()" />
      <IconButton :icon="ListOrdered" :label="t('knowledge.editor.numbers')" size="sm" :active="is('orderedList')" @click="editor?.chain().focus().toggleOrderedList().run()" />
      <IconButton :icon="ListChecks" :label="t('knowledge.editor.checklist')" size="sm" :active="is('taskList')" @click="editor?.chain().focus().toggleTaskList().run()" />
      <IconButton :icon="TextQuote" :label="t('knowledge.editor.quote')" size="sm" :active="is('blockquote')" @click="editor?.chain().focus().toggleBlockquote().run()" />
      <DropdownMenu :items="calloutMenu" align="start" width="200px">
        <template #trigger>
          <IconButton :icon="Lightbulb" :label="t('knowledge.editor.callout')" size="sm" :active="is('callout')" />
        </template>
      </DropdownMenu>
      <span class="mx-1 h-5 w-px bg-line" aria-hidden="true" />
      <IconButton :icon="Table2" :label="t('knowledge.editor.table')" size="sm" :active="tableActive" @click="editor?.chain().focus().insertTable(3, 3).run()" />
      <IconButton :icon="ImagePlus" :label="t('knowledge.editor.image')" size="sm" :loading="uploading > 0" @click="fileInput?.click()" />
      <IconButton :icon="Minus" :label="t('knowledge.editor.divider')" size="sm" @click="editor?.chain().focus().setHorizontalRule().run()" />
      <span class="flex-1" />
      <template v-if="tableActive">
        <IconButton :icon="Rows3" :label="t('knowledge.editor.addRow')" size="sm" @click="table('addRow')" />
        <IconButton :icon="Columns3" :label="t('knowledge.editor.addColumn')" size="sm" @click="table('addColumn')" />
        <DropdownMenu
          :items="[
            { label: t('knowledge.editor.toggleHeader'), onSelect: () => table('toggleHeader') },
            { label: t('knowledge.editor.deleteRow'), onSelect: () => table('deleteRow') },
            { label: t('knowledge.editor.deleteColumn'), onSelect: () => table('deleteColumn') },
            { label: t('knowledge.editor.deleteTable'), icon: Trash2, danger: true, onSelect: () => table('deleteTable') },
          ]"
          width="200px"
        >
          <template #trigger>
            <IconButton :icon="Trash2" :label="t('knowledge.editor.tableMore')" size="sm" />
          </template>
        </DropdownMenu>
        <span class="mx-1 h-5 w-px bg-line" aria-hidden="true" />
      </template>
      <IconButton :icon="Undo2" :label="t('knowledge.editor.undo')" shortcut="mod+z" size="sm" :disabled="!editor?.can().undo()" @click="editor?.chain().focus().undo().run()" />
      <IconButton :icon="Redo2" :label="t('knowledge.editor.redo')" shortcut="mod+shift+z" size="sm" :disabled="!editor?.can().redo()" @click="editor?.chain().focus().redo().run()" />
      <input ref="fileInput" type="file" accept="image/*" class="hidden" multiple @change="onFile" />
    </div>
    <div v-if="uploading" class="mb-3 flex items-center gap-2 text-sm text-muted" aria-live="polite"><UiSpinner :size="14" />{{ t("knowledge.editor.uploading") }}</div>
    <EditorContent :editor="editor" class="min-w-0" />
  </div>
</template>
