<script setup lang="ts">
/**
 * Topics (docs/PLAN-LEARNING.md §2.5): the subjects knowledge base pages, video lessons and quiz
 * questions are about, and what the skill matrix is worked out by. Kept by managers of the
 * knowledge base or of training: a name and a colour each, in order; archived ones stay on what
 * they tag but are offered for nothing new. "Add the pharmacy topics" adds the usual ones.
 */
import { Archive, ArrowDown, ArrowUp, Pencil, Plus, RotateCcw, Sparkles, Tags } from "@lucide/vue";
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import { qk } from "@/api/keys";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { TOPIC_COLOR_KEYS, topicColor, topicsApi, type Topic } from "../topics";

const { t } = useI18n();
const cid = useCompanyId();
const company = useCompanyStore();
const client = useQueryClient();
const showArchived = ref(false);

const key = computed(() => qk(cid.value, "knowledge", "topics", { archived: showArchived.value }));
const topics = useQuery({
  queryKey: key,
  queryFn: () => topicsApi.list(cid.value, showArchived.value),
  enabled: computed(() => cid.value > 0),
});
const rows = computed(() => (topics.data.value ?? []).filter((row) => showArchived.value || !row.archived));
const refresh = () => client.invalidateQueries({ queryKey: [cid.value, "knowledge"] });

const editing = ref<Topic | null>(null);
const open = ref(false);
const draft = reactive({ name: "", color: "sky", description: "" });
const error = ref<string | null>(null);
const busy = ref(false);

function edit(row: Topic | null): void {
  editing.value = row;
  error.value = null;
  Object.assign(draft, { name: row?.name ?? "", color: row?.color || "sky", description: row?.description ?? "" });
  open.value = true;
}

async function save(): Promise<void> {
  if (!draft.name.trim()) {
    error.value = t("knowledge.topics.needName");
    return;
  }
  busy.value = true;
  try {
    const input = { name: draft.name.trim(), color: draft.color, description: draft.description.trim() };
    if (editing.value) await topicsApi.update(cid.value, editing.value.id, input);
    else await topicsApi.create(cid.value, input);
    open.value = false;
    void refresh();
  } finally {
    busy.value = false;
  }
}

async function archive(row: Topic): Promise<void> {
  await (row.archived ? topicsApi.restore(cid.value, row.id) : topicsApi.archive(cid.value, row.id));
  void refresh();
}

async function move(index: number, by: -1 | 1): Promise<void> {
  const ids = rows.value.filter((row) => !row.archived).map((row) => row.id);
  const target = index + by;
  if (target < 0 || target >= ids.length) return;
  [ids[index], ids[target]] = [ids[target]!, ids[index]!];
  await topicsApi.reorder(cid.value, ids);
  void refresh();
}

const adding = ref(false);
async function pharmacy(): Promise<void> {
  adding.value = true;
  try {
    const made = await topicsApi.pharmacy(cid.value);
    toast.success(made.length ? t("knowledge.topics.added", { n: made.length }, made.length) : t("knowledge.topics.haveAll"));
    void refresh();
  } finally {
    adding.value = false;
  }
}

const usage = (row: Topic) => t("knowledge.topics.usage", { pages: row.page_count, lessons: row.lesson_count, questions: row.question_count });
</script>

<template>
  <div class="mx-auto max-w-3xl">
    <PageHeader :title="t('knowledge.topics.title')" :description="t('knowledge.topics.description')" :back="`/c/${company.currentId}/knowledge`" :back-label="t('knowledge.title')">
      <template #actions>
        <UiButton variant="secondary" :icon="Sparkles" :loading="adding" @click="pharmacy">{{ t("knowledge.topics.pharmacy") }}</UiButton>
        <UiButton variant="primary" :icon="Plus" @click="edit(null)">{{ t("knowledge.topics.new") }}</UiButton>
      </template>
    </PageHeader>
    <ToggleSwitch v-model="showArchived" size="sm" class="mb-3" :label="t('knowledge.topics.showArchived')" />

    <ErrorState v-if="topics.isError.value" :error="topics.error.value" :retry="() => topics.refetch()" />
    <template v-else-if="topics.isPending.value">
      <SkeletonBlock v-for="n in 5" :key="n" height="52px" radius="10px" class="mb-2" />
    </template>
    <div v-else-if="!rows.length" class="ui-card">
      <EmptyState :icon="Tags" :title="t('knowledge.topics.emptyTitle')" :description="t('knowledge.topics.emptyBody')">
        <UiButton variant="primary" :icon="Sparkles" :loading="adding" @click="pharmacy">{{ t("knowledge.topics.pharmacy") }}</UiButton>
      </EmptyState>
    </div>
    <ul v-else class="ui-card flex flex-col divide-y divide-line">
      <li v-for="(row, index) in rows" :key="row.id" class="flex flex-wrap items-center gap-3 px-4 py-3" :class="row.archived ? 'opacity-60' : ''">
        <span class="size-3.5 shrink-0 rounded-full" :style="{ background: topicColor(row.color) }" aria-hidden="true" />
        <span class="min-w-0 flex-1">
          <span class="block truncate font-medium text-fg">{{ row.name }}</span>
          <span class="block truncate text-xs text-muted">{{ row.description || usage(row) }}</span>
        </span>
        <div class="flex items-center gap-1">
          <template v-if="!row.archived">
            <IconButton :icon="ArrowUp" size="sm" :label="t('knowledge.topics.up')" :disabled="index === 0" @click="move(index, -1)" />
            <IconButton :icon="ArrowDown" size="sm" :label="t('knowledge.topics.down')" :disabled="index === rows.length - 1" @click="move(index, 1)" />
            <IconButton :icon="Pencil" size="sm" :label="t('common.edit')" @click="edit(row)" />
          </template>
          <IconButton :icon="row.archived ? RotateCcw : Archive" size="sm" :label="row.archived ? t('knowledge.topics.restore') : t('knowledge.topics.archive')" @click="archive(row)" />
        </div>
      </li>
    </ul>

    <UiDialog v-model:open="open" :title="editing ? t('knowledge.topics.editTitle') : t('knowledge.topics.new')" size="sm">
      <form class="flex flex-col gap-4" @submit.prevent="save">
        <FormField :label="t('knowledge.topics.name')" :error="error" required>
          <TextInput v-model="draft.name" :maxlength="80" autofocus :placeholder="t('knowledge.topics.namePlaceholder')" />
        </FormField>
        <FormField :label="t('knowledge.topics.color')">
          <div class="flex flex-wrap gap-2" role="radiogroup" :aria-label="t('knowledge.topics.color')">
            <button
              v-for="color in TOPIC_COLOR_KEYS"
              :key="color"
              type="button"
              role="radio"
              :aria-checked="draft.color === color"
              :aria-label="color"
              class="size-7 rounded-full border-2 transition"
              :class="draft.color === color ? 'border-fg' : 'border-transparent'"
              :style="{ background: topicColor(color) }"
              @click="draft.color = color"
            />
          </div>
        </FormField>
        <FormField :label="t('knowledge.topics.descriptionLabel')" optional>
          <TextInput v-model="draft.description" :maxlength="300" />
        </FormField>
      </form>
      <template #footer>
        <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="busy" @click="save">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
