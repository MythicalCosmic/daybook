<script setup lang="ts">
/**
 * Drop files here or click to choose (receipts, documents, photos). Checks type and size before
 * anything uploads and says why a file was refused; images get a preview. The value is the list
 * of chosen files; uploading is the page's job (`progress` shows its percentage per file name).
 *
 *   <FileDrop v-model="files" accept="image/*,application/pdf" :max-size="10 * 1024 * 1024" multiple />
 */
import { FileText, ImageUp, Paperclip, X } from "@lucide/vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { formatNumber } from "@/lib/format";
import { useFormat } from "@/lib/useFormat";

import { useControl } from "./field";

const model = defineModel<File[]>({ default: () => [] });

const props = withDefaults(
  defineProps<{
    accept?: string;
    multiple?: boolean;
    /** Bytes. Default 10 MB. */
    maxSize?: number;
    maxFiles?: number;
    /** Percent per file name while the page uploads. */
    progress?: Record<string, number>;
    compact?: boolean;
    disabled?: boolean;
    invalid?: boolean;
    id?: string;
    title?: string;
    hint?: string;
  }>(),
  {
    accept: undefined,
    multiple: false,
    maxSize: 10 * 1024 * 1024,
    maxFiles: 10,
    progress: () => ({}),
    compact: false,
    disabled: false,
    invalid: false,
    id: undefined,
    title: undefined,
    hint: undefined,
  },
);

const emit = defineEmits<{ rejected: [messages: string[]] }>();

const { t } = useI18n();
const fmt = useFormat();
const control = useControl(props);
const input = ref<HTMLInputElement | null>(null);
const over = ref(false);
const errors = ref<string[]>([]);
let depth = 0;

function sizeText(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${formatNumber(bytes / (1024 * 1024), fmt.lang.value, 1)} MB`;
  return `${formatNumber(Math.max(1, Math.round(bytes / 1024)), fmt.lang.value)} KB`;
}

function accepted(file: File): boolean {
  if (!props.accept) return true;
  const name = file.name.toLowerCase();
  return props.accept
    .split(",")
    .map((rule) => rule.trim().toLowerCase())
    .filter(Boolean)
    .some((rule) => {
      if (rule.startsWith(".")) return name.endsWith(rule);
      if (rule.endsWith("/*")) return file.type.startsWith(rule.slice(0, -1));
      return file.type === rule;
    });
}

function add(list: FileList | File[] | null | undefined): void {
  if (!list || control.disabled.value) return;
  const incoming = [...list];
  const problems: string[] = [];
  const ok: File[] = [];
  for (const file of incoming) {
    if (!accepted(file)) problems.push(t("common.file.wrongType", { name: file.name }));
    else if (file.size > props.maxSize) problems.push(t("common.file.tooBig", { name: file.name, size: sizeText(props.maxSize) }));
    else ok.push(file);
  }
  let next = props.multiple ? [...model.value, ...ok] : ok.slice(0, 1);
  if (next.length > props.maxFiles) {
    problems.push(t("common.file.tooMany", { n: props.maxFiles }));
    next = next.slice(0, props.maxFiles);
  }
  errors.value = problems;
  if (problems.length) emit("rejected", problems);
  if (ok.length) model.value = next;
}

function remove(index: number): void {
  model.value = model.value.filter((_, i) => i !== index);
}

function onDrop(event: DragEvent): void {
  over.value = false;
  depth = 0;
  add(event.dataTransfer?.files);
}

function onEnter(): void {
  depth += 1;
  over.value = true;
}

function onLeave(): void {
  depth = Math.max(0, depth - 1);
  if (depth === 0) over.value = false;
}

function onChange(event: Event): void {
  const target = event.target as HTMLInputElement;
  add(target.files);
  target.value = "";
}

function onPaste(event: ClipboardEvent): void {
  const files = event.clipboardData?.files;
  if (files?.length) add(files);
}

// Image previews, released when files leave.
const previews = ref(new Map<File, string>());
watch(
  model,
  (files) => {
    const next = new Map<File, string>();
    for (const file of files) {
      const existing = previews.value.get(file);
      if (existing) next.set(file, existing);
      else if (file.type.startsWith("image/") && typeof URL.createObjectURL === "function") next.set(file, URL.createObjectURL(file));
    }
    for (const [file, url] of previews.value) if (!next.has(file)) URL.revokeObjectURL(url);
    previews.value = next;
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  for (const url of previews.value.values()) URL.revokeObjectURL(url);
});

const hintText = computed(() => {
  if (props.hint) return props.hint;
  const types = props.accept
    ? props.accept
        .split(",")
        .map((rule) => rule.trim().replace("image/*", "JPG, PNG").replace("application/pdf", "PDF").replace(/^\./, "").toUpperCase())
        .join(", ")
    : "";
  return types ? t("common.file.hint", { types, size: sizeText(props.maxSize) }) : t("common.file.hintSize", { size: sizeText(props.maxSize) });
});
</script>

<template>
  <div class="flex flex-col gap-2" @paste="onPaste">
    <button
      :id="control.id.value"
      type="button"
      :disabled="control.disabled.value"
      :aria-describedby="control.describedBy.value"
      :aria-invalid="control.invalid.value || undefined"
      :class="[
        'group relative flex w-full items-center gap-3 rounded-[10px] border border-dashed text-left outline-offset-2 transition-colors duration-150',
        compact ? 'px-3 py-2.5' : 'flex-col justify-center px-6 py-7 text-center',
        over ? 'border-primary bg-accent-soft/60' : 'border-line-strong bg-canvas/50 hover:border-[color-mix(in_srgb,var(--c-text)_32%,transparent)] hover:bg-surface-2/50',
        control.invalid.value && 'border-danger',
        control.disabled.value && 'cursor-not-allowed opacity-55',
      ]"
      @click="input?.click()"
      @dragenter.prevent="onEnter"
      @dragover.prevent
      @dragleave.prevent="onLeave"
      @drop.prevent="onDrop"
    >
      <span
        :class="[
          'grid shrink-0 place-items-center rounded-full transition-transform duration-200',
          compact ? 'size-8 bg-surface-2 text-muted dark:bg-surface-3' : 'size-11 bg-accent-soft text-accent-fg',
          over && 'scale-110',
        ]"
        aria-hidden="true"
      >
        <ImageUp v-if="accept?.startsWith('image')" :size="compact ? 16 : 20" />
        <Paperclip v-else :size="compact ? 16 : 20" />
      </span>
      <span class="min-w-0">
        <span class="block text-base font-semibold text-fg">{{ title ?? (over ? t("common.file.release") : t("common.file.drop")) }}</span>
        <span class="mt-0.5 block text-sm text-muted">
          <span class="font-semibold text-primary group-hover:underline">{{ t("common.file.browse") }}</span>
          <span> · {{ hintText }}</span>
        </span>
      </span>
    </button>
    <input ref="input" type="file" class="hidden" :accept="accept" :multiple="multiple" tabindex="-1" @change="onChange" />

    <ul v-if="errors.length" class="flex flex-col gap-1" role="alert">
      <li v-for="error in errors" :key="error" class="text-xs font-medium text-danger">{{ error }}</li>
    </ul>

    <TransitionGroup v-if="model.length" name="list" tag="ul" class="relative flex flex-col gap-1.5">
      <li
        v-for="(file, index) in model"
        :key="`${file.name}:${file.size}:${file.lastModified}`"
        class="relative flex items-center gap-3 overflow-hidden rounded-[10px] border border-line bg-surface py-2 pl-2 pr-1.5"
      >
        <img v-if="previews.get(file)" :src="previews.get(file)" alt="" class="size-9 shrink-0 rounded-[6px] object-cover" />
        <span v-else class="grid size-9 shrink-0 place-items-center rounded-[6px] bg-surface-2 text-muted dark:bg-surface-3"><FileText :size="16" /></span>
        <span class="min-w-0 flex-1">
          <span class="block truncate text-sm font-medium text-fg">{{ file.name }}</span>
          <span class="block text-xs text-muted">{{ sizeText(file.size) }}</span>
        </span>
        <span v-if="progress[file.name] !== undefined && progress[file.name]! < 100" class="text-xs font-semibold tabular-nums text-muted">
          {{ Math.round(progress[file.name]!) }}%
        </span>
        <button
          type="button"
          class="pressable grid size-7 shrink-0 place-items-center rounded-[6px] text-subtle hover:bg-highlight hover:text-fg"
          :aria-label="t('common.file.remove', { name: file.name })"
          :disabled="control.disabled.value"
          @click="remove(index)"
        >
          <X :size="14" />
        </button>
        <span
          v-if="progress[file.name] !== undefined"
          class="absolute inset-x-0 bottom-0 h-0.5 origin-left bg-primary transition-transform duration-300"
          :style="{ transform: `scaleX(${Math.min(100, progress[file.name]!) / 100})` }"
          aria-hidden="true"
        />
      </li>
    </TransitionGroup>
  </div>
</template>
