<script setup lang="ts">
/**
 * Renders Markdown safely (AI answers, project descriptions, briefings): markdown-it with raw HTML
 * off, sanitized with DOMPurify (lib/markdown.ts). Record references become chips that open the
 * record in the console: `member:17` → "Person #17", `[Dilnoza](member:17)` → "Dilnoza". `kinds`
 * adds record types; `labels` names bare references you already know ("member:17" → "Dilnoza").
 * The renderer (markdown-it + DOMPurify, ~55 KB) loads on first use, so a page that shows Markdown
 * doesn't carry it in its own chunk; until then the source shows as plain text.
 */
import { computed, onMounted, shallowRef } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import type { MarkdownOptions } from "@/lib/markdown";
import { useCompanyStore } from "@/stores/company";

type Renderer = (source: string, options: MarkdownOptions) => string;

const props = withDefaults(
  defineProps<{
    source: string | null | undefined;
    kinds?: Record<string, (id: string) => string>;
    labels?: Record<string, string>;
    size?: "sm" | "md";
    allowImages?: boolean;
    breaks?: boolean;
  }>(),
  { kinds: undefined, labels: undefined, size: "md", allowImages: false, breaks: true },
);

const { t, te } = useI18n();
const router = useRouter();
const company = useCompanyStore();

const render = shallowRef<Renderer | null>(null);
onMounted(async () => {
  // The bundler caches the import, so every MarkdownView on the page shares one download.
  render.value = (await import("@/lib/markdown")).renderMarkdown;
});

const html = computed(() =>
  render.value?.(props.source ?? "", {
    base: company.currentId ? `/dashboard/c/${company.currentId}` : null,
    kinds: props.kinds,
    allowImages: props.allowImages,
    breaks: props.breaks,
    label: (kind, id) => props.labels?.[`${kind}:${id}`] ?? (te(`common.record.${kind}`) ? t(`common.record.${kind}`, { id }) : `${kind} #${id}`),
  }) ?? null,
);

/** Chips and internal links navigate inside the app instead of reloading the page. */
function onClick(event: MouseEvent): void {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const link = (event.target as HTMLElement).closest("a");
  const href = link?.getAttribute("href");
  if (!link || !href || !href.startsWith("/dashboard/")) return;
  event.preventDefault();
  void router.push(href.slice("/dashboard".length));
}
</script>

<template>
  <!-- v-html is safe here: renderMarkdown disables raw HTML and sanitizes the result with DOMPurify. -->
  <div v-if="html !== null" :class="['md-body', size === 'sm' && 'md-sm']" @click="onClick" v-html="html" />
  <div v-else :class="['md-body whitespace-pre-line', size === 'sm' && 'md-sm']">{{ source }}</div>
</template>

<style scoped>
.md-body {
  color: var(--c-text);
  font-size: var(--text-base);
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.md-sm {
  font-size: var(--text-sm);
  line-height: 1.55;
}
.md-body :deep(> * + *) {
  margin-top: 0.75em;
}
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) {
  font-weight: 650;
  line-height: 1.3;
  letter-spacing: -0.01em;
  margin-top: 1.25em;
}
.md-body :deep(h1) {
  font-size: 1.45em;
}
.md-body :deep(h2) {
  font-size: 1.25em;
}
.md-body :deep(h3) {
  font-size: 1.08em;
}
.md-body :deep(h4) {
  font-size: 1em;
}
.md-body :deep(:first-child) {
  margin-top: 0;
}
.md-body :deep(a:not(.md-chip)) {
  color: var(--c-primary);
  text-decoration: underline;
  text-decoration-color: color-mix(in srgb, var(--c-primary) 40%, transparent);
  text-underline-offset: 2px;
}
.md-body :deep(a:not(.md-chip):hover) {
  text-decoration-color: currentColor;
}
.md-body :deep(ul),
.md-body :deep(ol) {
  padding-left: 1.35em;
}
.md-body :deep(ul) {
  list-style: disc;
}
.md-body :deep(ol) {
  list-style: decimal;
}
.md-body :deep(li + li) {
  margin-top: 0.25em;
}
.md-body :deep(li::marker) {
  color: var(--c-subtle);
}
.md-body :deep(blockquote) {
  border-left: 3px solid var(--c-border-strong);
  padding-left: 0.9em;
  color: var(--c-muted);
}
.md-body :deep(code) {
  border-radius: 5px;
  background: var(--c-surface-2);
  padding: 0.1em 0.35em;
  font-family: var(--font-mono);
  font-size: 0.88em;
}
.md-body :deep(pre) {
  overflow-x: auto;
  border: 1px solid var(--c-border);
  border-radius: 10px;
  background: var(--c-canvas);
  padding: 0.8em 1em;
}
.md-body :deep(pre code) {
  background: none;
  padding: 0;
}
.md-body :deep(hr) {
  border: 0;
  border-top: 1px solid var(--c-border);
}
.md-body :deep(table) {
  display: block;
  overflow-x: auto;
  border-collapse: collapse;
  font-size: 0.95em;
  font-variant-numeric: tabular-nums;
}
.md-body :deep(th),
.md-body :deep(td) {
  border-bottom: 1px solid var(--c-border);
  padding: 6px 12px 6px 0;
  text-align: left;
  white-space: nowrap;
}
.md-body :deep(th) {
  color: var(--c-muted);
  font-size: var(--text-xs);
  font-weight: 600;
}
.md-body :deep(.md-chip) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  margin: 0 1px;
  padding: 0 7px 0 6px;
  border-radius: 999px;
  background: var(--c-accent-soft);
  color: var(--c-accent-fg);
  font-size: 0.86em;
  font-weight: 600;
  line-height: 1.6;
  vertical-align: baseline;
  text-decoration: none;
  white-space: nowrap;
  transition: background-color var(--dur-press) var(--ease-standard);
}
.md-body :deep(a.md-chip:hover) {
  background: color-mix(in srgb, var(--c-accent-soft) 70%, var(--c-primary));
}
.md-body :deep(.md-chip::before) {
  content: "";
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: currentColor;
  opacity: 0.6;
}
</style>
