<script setup lang="ts">
/** Move a page (with its sub-pages) to another space, or under another page. */
import { FolderInput } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import type { SelectOption } from "@/components/options";
import SelectBox from "@/components/SelectBox.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { knowledgeApi, usePutPage, useRefresh, useSpaces, useTree } from "../api";
import { flatten } from "../lib";
import type { PageDetail, TreeNodeData } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ page: PageDetail }>();

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const putPage = usePutPage();
const spaces = useSpaces();
const spaceId = ref<number | null>(props.page.space.id);
const parentId = ref<number>(0);
const tree = useTree(computed(() => (open.value ? spaceId.value : null)));
const saving = ref(false);

watch(open, (isOpen) => {
  if (!isOpen) return;
  spaceId.value = props.page.space.id;
  parentId.value = props.page.parent_id ?? 0;
});
watch(spaceId, (next, previous) => {
  if (previous !== undefined && next !== props.page.space.id) parentId.value = 0;
});

/** Pages it may go under: not itself, nothing inside it. */
function withoutSelf(nodes: TreeNodeData[]): TreeNodeData[] {
  return nodes.filter((node) => node.id !== props.page.id).map((node) => ({ ...node, children: withoutSelf(node.children) }));
}

const spaceOptions = computed<SelectOption<number>[]>(() => (spaces.data.value ?? []).map((space) => ({ value: space.id, label: `${space.icon} ${space.name}`.trim() })));
const parentOptions = computed<SelectOption<number>[]>(() => [
  { value: 0, label: t("knowledge.move.top") },
  ...flatten(withoutSelf(tree.data.value ?? []))
    .filter(({ depth }) => depth < 3)
    .map(({ node, depth }) => ({ value: node.id, label: `${"  ".repeat(depth)}${depth ? "↳ " : ""}${node.emoji} ${node.title}`.replace(/\s+/g, " ").trim() })),
]);

async function submit(): Promise<void> {
  if (!spaceId.value) return;
  saving.value = true;
  try {
    const page = await knowledgeApi.move(company.currentId ?? 0, props.page.id, {
      space: spaceId.value,
      parent: parentId.value || null,
      index: 9999,
    });
    putPage(page);
    void refresh();
    toast.success(t("knowledge.move.done"));
    open.value = false;
  } catch {
    // Shown by the HTTP layer (too deep, wrong space…).
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('knowledge.move.title')" :description="t('knowledge.move.hint')" size="sm">
    <form id="kb-move" class="flex flex-col gap-4" @submit.prevent="submit">
      <FormField :label="t('knowledge.move.space')">
        <SelectBox v-model="spaceId" :options="spaceOptions" />
      </FormField>
      <FormField :label="t('knowledge.move.under')">
        <SelectBox v-model="parentId" :options="parentOptions" />
      </FormField>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="kb-move" :icon="FolderInput" :loading="saving">{{ t("knowledge.move.submit") }}</UiButton>
    </template>
  </UiDialog>
</template>
