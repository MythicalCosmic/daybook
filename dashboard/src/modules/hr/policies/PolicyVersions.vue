<script setup lang="ts">
/**
 * A policy's versions, newest first: the draft (if any), the version in force, and the ones before,
 * each with when and by whom it was published, whether it asked everyone again or was a small edit,
 * what changed, and its file. "Read" opens that version's text; "What changed" compares it with the
 * one before (or any other).
 */
import { FileDiff, FileText, Paperclip, PenLine } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useFormat } from "@/lib/useFormat";

import { usePolicyVersion } from "./api";
import PolicyDiff from "./PolicyDiff.vue";
import PolicyProse from "./PolicyProse.vue";
import type { PolicyDetail, PolicyVersion } from "./types";

const props = defineProps<{ policy: PolicyDetail; editTo?: string | null }>();

const { t } = useI18n();
const fmt = useFormat();

const versions = computed(() => props.policy.versions);
const published = computed(() => versions.value.filter((row) => !row.is_draft));

function label(row: PolicyVersion): { text: string; tone: "success" | "neutral" | "warning" | "info" } {
  if (row.is_draft) return { text: t("hr.policy.versions.draftNow"), tone: "warning" };
  if (props.policy.version?.id === row.id) return { text: t("hr.policy.status.active"), tone: "success" };
  return { text: t("hr.policy.versions.earlier"), tone: "neutral" };
}

function how(row: PolicyVersion): string | null {
  if (row.is_draft) return null;
  if (row.number === 1 || row === published.value.at(-1)) return t("hr.policy.versions.first");
  return row.asks_again ? t("hr.policy.versions.asksAgain") : t("hr.policy.versions.smallEdit");
}

// Reading one version, or comparing two ------------------------------------------------------------
const mode = ref<"read" | "compare" | null>(null);
const picked = ref<number | null>(null);
const base = ref<number | null>(null);
const open = computed({
  get: () => mode.value !== null,
  set: (value: boolean) => {
    if (!value) mode.value = null;
  },
});
const reading = usePolicyVersion(() => props.policy.id, () => (mode.value === "read" ? picked.value : null));

function read(row: PolicyVersion): void {
  picked.value = row.number;
  mode.value = "read";
}
function compare(row: PolicyVersion): void {
  picked.value = row.number;
  base.value = versions.value.find((other) => other.number < row.number && !other.is_draft)?.number ?? null;
  mode.value = "compare";
}
const baseOptions = computed(() =>
  versions.value.filter((row) => row.number !== picked.value && !row.is_draft).map((row) => ({ value: row.number, label: t("hr.policy.version", { n: row.number }) })),
);
const title = computed(() => (picked.value ? t("hr.policy.version", { n: picked.value }) : ""));
</script>

<template>
  <div class="flex flex-col gap-3" data-policy-versions>
    <EmptyState v-if="!versions.length" size="sm" tone="neutral" :icon="FileText" :title="t('hr.policy.versions.none')" />
    <ol v-else class="ui-card divide-y divide-[var(--c-border)] overflow-hidden">
      <li v-for="row in versions" :key="row.id" class="flex flex-col gap-2 px-4 py-3.5 sm:flex-row sm:items-start sm:gap-4" :data-version="row.number">
        <span class="grid size-9 shrink-0 place-items-center rounded-full bg-surface-2 text-sm font-semibold tabular-nums text-fg dark:bg-surface-3" aria-hidden="true">{{ row.number }}</span>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <p class="text-base font-semibold text-fg">{{ t("hr.policy.version", { n: row.number }) }}</p>
            <StatusPill :tone="label(row).tone" size="sm" :label="label(row).text" />
            <StatusPill v-if="how(row)" tone="neutral" variant="outline" size="sm" :dot="false" :label="how(row)!" />
          </div>
          <p class="mt-0.5 text-sm text-muted">
            <template v-if="row.published_at">{{ fmt.instant(row.published_at, "datetime") }}<template v-if="row.published_by"> · {{ row.published_by }}</template></template>
            <template v-else>{{ t("hr.policy.updated", { date: fmt.instant(row.updated_at, "short") }) }}</template>
          </p>
          <p v-if="row.change_note" class="mt-1.5 text-sm text-fg">{{ row.change_note }}</p>
          <p v-if="row.has_file" class="mt-1 inline-flex items-center gap-1 text-xs text-muted"><Paperclip :size="12" aria-hidden="true" />{{ t(`hr.policy.fileType.${row.file_type ?? "pdf"}`) }}</p>
        </div>
        <div class="flex shrink-0 flex-wrap items-center gap-1.5 sm:justify-end">
          <UiButton v-if="row.is_draft && editTo" size="sm" :icon="PenLine" :to="editTo">{{ t("hr.policy.continueDraft") }}</UiButton>
          <UiButton v-else size="sm" variant="ghost" :icon="FileText" @click="read(row)">{{ t("hr.policy.versions.read") }}</UiButton>
          <UiButton v-if="!row.is_draft && published.length > 1 && row.number !== published.at(-1)?.number" size="sm" variant="ghost" :icon="FileDiff" @click="compare(row)">{{
            t("hr.policy.versions.compare")
          }}</UiButton>
        </div>
      </li>
    </ol>

    <UiDrawer v-model:open="open" :title="mode === 'compare' ? t('hr.policy.versions.compareTitle', { n: picked ?? 0 }) : title" size="lg">
      <div class="p-5">
      <template v-if="mode === 'read'">
        <div v-if="reading.isPending.value" class="flex flex-col gap-2" aria-hidden="true"><SkeletonBlock v-for="n in 8" :key="n" :width="n % 3 ? '100%' : '70%'" /></div>
        <ErrorState v-else-if="reading.isError.value" compact :error="reading.error.value" :retry="() => reading.refetch()" />
        <template v-else-if="reading.data.value">
          <p v-if="reading.data.value.change_note" class="mb-4 rounded-[10px] bg-surface-2 px-3.5 py-2.5 text-sm text-fg dark:bg-surface-3">
            <span class="font-semibold">{{ t("hr.policy.field.changeNote") }}:</span> {{ reading.data.value.change_note }}
          </p>
          <PolicyProse v-if="reading.data.value.body" :html="reading.data.value.body" />
          <EmptyState v-else size="sm" tone="neutral" :icon="Paperclip" :title="t('hr.policy.text.empty')" />
          <a v-if="reading.data.value.file_url" :href="reading.data.value.file_url" target="_blank" rel="noopener" class="mt-5 inline-flex items-center gap-2 rounded-[10px] border border-line px-3.5 py-2.5 text-sm font-medium text-fg hover:bg-highlight">
            <Paperclip :size="15" class="text-subtle" aria-hidden="true" />{{ t("hr.policy.text.openFile") }}
          </a>
        </template>
      </template>
      <template v-else-if="mode === 'compare' && picked">
        <FormField :label="t('hr.policy.diff.with')" class="mb-4 max-w-[260px]">
          <SelectBox v-model="base" :options="baseOptions" />
        </FormField>
        <PolicyDiff v-if="base" :policy-id="policy.id" :from="Math.min(base, picked)" :to="Math.max(base, picked)" />
      </template>
      </div>
    </UiDrawer>
  </div>
</template>
