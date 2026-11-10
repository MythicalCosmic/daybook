<script setup lang="ts">
/**
 * What changed between two versions of a policy's text: paragraphs added (green), removed (struck
 * through) and changed (the words marked), long unchanged stretches folded away.
 */
import { ChevronsUpDown } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";

import { usePolicyVersion } from "./api";
import { diffCounts, diffText, type DiffBlock } from "./lib";
import "./policy.css";

const props = defineProps<{ policyId: number; from: number; to: number }>();

const { t } = useI18n();
const before = usePolicyVersion(() => props.policyId, () => props.from);
const after = usePolicyVersion(() => props.policyId, () => props.to);

const blocks = computed<DiffBlock[]>(() => (before.data.value && after.data.value ? diffText(before.data.value.body_text, after.data.value.body_text) : []));
const counts = computed(() => diffCounts(blocks.value));
const changed = computed(() => counts.value.added + counts.value.removed + counts.value.changed > 0);

// Unchanged stretches longer than this keep one paragraph on each side and fold the rest.
const FOLD = 3;
const opened = ref(new Set<number>());
watch(
  () => [props.from, props.to],
  () => (opened.value = new Set()),
);

type Row = { kind: "block"; block: DiffBlock; index: number } | { kind: "fold"; start: number; count: number };
const rows = computed<Row[]>(() => {
  const out: Row[] = [];
  const list = blocks.value;
  let index = 0;
  while (index < list.length) {
    if (list[index]!.kind !== "same") {
      out.push({ kind: "block", block: list[index]!, index });
      index += 1;
      continue;
    }
    let end = index;
    while (end < list.length && list[end]!.kind === "same") end += 1;
    const run = end - index;
    if (run > FOLD && !opened.value.has(index)) {
      const keepStart = index === 0 ? 0 : 1;
      const keepEnd = end === list.length ? 0 : 1;
      for (let k = index; k < index + keepStart; k += 1) out.push({ kind: "block", block: list[k]!, index: k });
      out.push({ kind: "fold", start: index, count: run - keepStart - keepEnd });
      for (let k = end - keepEnd; k < end; k += 1) out.push({ kind: "block", block: list[k]!, index: k });
    } else {
      for (let k = index; k < end; k += 1) out.push({ kind: "block", block: list[k]!, index: k });
    }
    index = end;
  }
  return out;
});

function unfold(start: number): void {
  opened.value = new Set([...opened.value, start]);
}
</script>

<template>
  <div class="flex flex-col gap-3" data-policy-diff>
    <div v-if="before.isPending.value || after.isPending.value" class="flex flex-col gap-2" aria-hidden="true">
      <SkeletonBlock v-for="n in 6" :key="n" :width="n % 3 ? '100%' : '65%'" height="18px" />
    </div>
    <ErrorState v-else-if="before.isError.value || after.isError.value" compact :error="before.error.value ?? after.error.value" :retry="() => (before.refetch(), after.refetch())" />
    <template v-else>
      <div class="flex flex-wrap items-center gap-1.5">
        <StatusPill v-if="counts.added" tone="success" size="sm" :label="t('hr.policy.diff.added', { n: counts.added }, counts.added)" />
        <StatusPill v-if="counts.changed" tone="warning" size="sm" :label="t('hr.policy.diff.changed', { n: counts.changed }, counts.changed)" />
        <StatusPill v-if="counts.removed" tone="danger" size="sm" :label="t('hr.policy.diff.removed', { n: counts.removed }, counts.removed)" />
      </div>
      <EmptyState v-if="!changed" size="sm" tone="neutral" :icon="ChevronsUpDown" :title="t('hr.policy.diff.none')" />
      <div v-else class="flex flex-col">
        <template v-for="row in rows" :key="row.kind === 'fold' ? `fold-${row.start}` : `block-${row.index}`">
          <button
            v-if="row.kind === 'fold'"
            type="button"
            class="pressable my-1 inline-flex items-center gap-1.5 self-start rounded-full border border-dashed border-line-strong px-3 py-1 text-xs font-medium text-muted hover:bg-highlight hover:text-fg"
            @click="unfold(row.start)"
          >
            <ChevronsUpDown :size="13" aria-hidden="true" />{{ t("hr.policy.diff.same", { n: row.count }, row.count) }}
          </button>
          <p v-else class="hr-diff-block" :data-kind="row.block.kind">
            <template v-if="row.block.kind === 'changed'">
              <template v-for="(part, partIndex) in row.block.parts" :key="partIndex">
                <ins v-if="part.kind === 'added'">{{ part.text }}</ins>
                <del v-else-if="part.kind === 'removed'">{{ part.text }}</del>
                <span v-else>{{ part.text }}</span>
              </template>
            </template>
            <template v-else>{{ row.block.parts[0]?.text }}</template>
          </p>
        </template>
      </div>
    </template>
  </div>
</template>
