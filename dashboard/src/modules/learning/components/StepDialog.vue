<script setup lang="ts">
/**
 * "Add a step" in the course editor: a lesson, a knowledge base page or a quiz of this company
 * that isn't archived (drafts too: the course only reaches people once it is published).
 */
import { BookOpen, FileQuestion, PlayCircle } from "@lucide/vue";
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useCompanyId } from "@/stores/company";

import { learningApi, learningKeys } from "../api";
import { STATUS_TONES } from "../lib";
import type { Pick, StepKind } from "../types";

const props = defineProps<{ taken: { kind: StepKind; id: number }[] }>();
const open = defineModel<boolean>("open", { default: false });
const emit = defineEmits<{ pick: [input: { kind: StepKind; target_id: number; required: boolean }] }>();

const { t } = useI18n();
const cid = useCompanyId();
const kind = ref<StepKind>("lesson");
const q = ref("");
const required = ref(true);
watch(open, (value) => {
  if (value) {
    q.value = "";
    required.value = true;
  }
});

const picks = useQuery({
  queryKey: computed(() => learningKeys.of(cid.value, "targets", { kind: kind.value, q: q.value })),
  queryFn: () => learningApi.targets(cid.value, kind.value, q.value),
  enabled: computed(() => open.value && cid.value > 0),
  staleTime: 10_000,
});
const kinds = computed(() => [
  { value: "lesson" as const, label: t("learning.step.kind.lesson"), icon: PlayCircle },
  { value: "page" as const, label: t("learning.step.kind.page"), icon: BookOpen },
  { value: "quiz" as const, label: t("learning.step.kind.quiz"), icon: FileQuestion },
]);
const isTaken = (row: Pick) => props.taken.some((step) => step.kind === kind.value && step.id === row.id);

function choose(row: Pick): void {
  if (isTaken(row)) return;
  emit("pick", { kind: kind.value, target_id: row.id, required: required.value });
  open.value = false;
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('learning.step.addTitle')" :description="t('learning.step.addHint')" size="md">
    <div class="flex flex-col gap-3">
      <SegmentedControl v-model="kind" :options="kinds" block />
      <TextInput v-model="q" type="search" :debounce="250" :placeholder="t('learning.step.search')" clearable />
      <ToggleSwitch v-model="required" :label="t('learning.step.required')" :description="t('learning.step.requiredHint')" />
      <div class="max-h-[46vh] overflow-y-auto">
        <template v-if="picks.isPending.value">
          <SkeletonBlock v-for="n in 4" :key="n" height="44px" radius="8px" class="mb-2" />
        </template>
        <EmptyState v-else-if="!picks.data.value?.length" size="sm" :title="t(`learning.step.none.${kind}`)" />
        <ul v-else class="flex flex-col">
          <li v-for="row in picks.data.value" :key="row.id">
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-[10px] px-2 py-2.5 text-left hover:bg-surface-2 disabled:opacity-50"
              :disabled="isTaken(row)"
              @click="choose(row)"
            >
              <span class="grid size-8 shrink-0 place-items-center rounded-[8px] bg-surface-2 text-base" aria-hidden="true">{{ row.emoji || "•" }}</span>
              <span class="min-w-0 flex-1 truncate text-sm font-medium text-fg">{{ row.title }}</span>
              <span v-if="isTaken(row)" class="text-xs text-muted">{{ t("learning.step.already") }}</span>
              <StatusPill v-else size="sm" :tone="STATUS_TONES[row.status]" :label="t(`learning.status.${row.status}`)" />
            </button>
          </li>
        </ul>
      </div>
    </div>
  </UiDialog>
</template>
