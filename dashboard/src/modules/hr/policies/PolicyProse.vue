<script setup lang="ts">
/**
 * A policy's text as people read it: the server's HTML (already cleaned by the knowledge base's
 * allow-list) cleaned once more here, checklists read-only, links opening in a new tab.
 */
import DOMPurify from "dompurify";
import { computed } from "vue";

import "./policy.css";

const props = defineProps<{ html: string }>();

const TAGS = ["p", "h1", "h2", "h3", "h4", "strong", "b", "em", "i", "u", "s", "strike", "code", "pre", "blockquote", "br", "hr", "ul", "ol", "li", "label", "input", "span", "div", "a", "table", "thead", "tbody", "tr", "th", "td", "colgroup", "col"];
const ATTRIBUTES = ["href", "start", "colspan", "rowspan", "data-type", "data-checked", "data-callout", "type", "checked"];

const clean = computed(() => {
  const html = DOMPurify.sanitize(props.html || "", { ALLOWED_TAGS: TAGS, ALLOWED_ATTR: ATTRIBUTES });
  return html.replace(/<input\b/g, "<input disabled").replace(/<a\b/g, '<a target="_blank" rel="noopener noreferrer"').replace(/<table\b/g, '<div class="hr-prose-scroll"><table').replace(/<\/table>/g, "</table></div>");
});
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- cleaned twice: the server's allow-list and DOMPurify -->
  <article class="hr-prose" v-html="clean" />
</template>
