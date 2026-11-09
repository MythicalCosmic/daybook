<script setup lang="ts">
/**
 * A short list of names people are grouped by (departments, positions): add one in the field on
 * top, rename one in place (click its pencil, Enter saves, Esc cancels), delete one after a
 * confirmation. Each row's count opens the employees in it.
 */
import { Check, Pencil, Plus, Trash2, X } from "@lucide/vue";
import { nextTick, ref, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import { isApiError } from "@/api/http";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";

export interface NameItem {
  id: number;
  name: string;
  count: number;
  subtitle?: string;
  /** Where the count leads (the employees in it). */
  to?: string;
}

const props = defineProps<{
  items: NameItem[] | undefined;
  loading: boolean;
  error: unknown;
  retry: () => unknown;
  canEdit: boolean;
  icon: Component;
  placeholder: string;
  emptyTitle: string;
  emptyBody: string;
  countLabel: (count: number) => string;
  deleteTitle: (name: string) => string;
  deleteBody: string;
  onCreate: (name: string) => Promise<unknown>;
  onRename: (id: number, name: string) => Promise<unknown>;
  onRemove: (id: number) => Promise<unknown>;
}>();

const { t } = useI18n();
const confirm = useConfirm();
const skeleton = useDelayedPending(() => props.loading);

const draft = ref("");
const adding = ref(false);
const addError = ref<string | null>(null);
const editing = ref<number | null>(null);
const editName = ref("");
const saving = ref(false);
const editError = ref<string | null>(null);

function messageOf(error: unknown): string {
  if (isApiError(error)) return error.detail ?? Object.values(error.fieldErrors)[0]?.[0] ?? t("common.error.generic");
  return t("common.error.generic");
}

async function add(): Promise<void> {
  const name = draft.value.trim();
  if (!name || adding.value) return;
  adding.value = true;
  addError.value = null;
  try {
    await props.onCreate(name);
    draft.value = "";
  } catch (error) {
    addError.value = messageOf(error);
  } finally {
    adding.value = false;
  }
}

async function startEdit(item: NameItem): Promise<void> {
  editing.value = item.id;
  editName.value = item.name;
  editError.value = null;
  await nextTick();
  document.querySelector<HTMLInputElement>(`[data-rename="${item.id}"] input`)?.select();
}

async function saveEdit(item: NameItem): Promise<void> {
  const name = editName.value.trim();
  if (!name || name === item.name) {
    editing.value = null;
    return;
  }
  saving.value = true;
  editError.value = null;
  try {
    await props.onRename(item.id, name);
    editing.value = null;
  } catch (error) {
    editError.value = messageOf(error);
  } finally {
    saving.value = false;
  }
}

async function remove(item: NameItem): Promise<void> {
  const answer = await confirm({ title: props.deleteTitle(item.name), message: props.deleteBody, confirmLabel: t("common.delete"), tone: "danger", icon: Trash2 });
  if (!answer) return;
  try {
    await props.onRemove(item.id);
    toast.success(t("davomat.team.list.deleted", { name: item.name }));
  } catch {
    // The HTTP layer has shown why (people still in it, for one).
  }
}
</script>

<template>
  <section class="ui-card overflow-hidden" data-name-list>
    <form v-if="canEdit" class="flex flex-col gap-1.5 border-b border-line bg-surface-2/40 px-4 py-3" @submit.prevent="add">
      <div class="flex gap-2">
        <TextInput v-model="draft" class="min-w-0 flex-1" :placeholder="placeholder" :maxlength="100" :invalid="!!addError" data-new-name @update:model-value="addError = null" />
        <UiButton type="submit" variant="primary" :icon="Plus" :loading="adding" :disabled="!draft.trim()" data-add-name>{{ t("davomat.team.list.add") }}</UiButton>
      </div>
      <p v-if="addError" class="text-sm text-danger" role="alert">{{ addError }}</p>
    </form>

    <div v-if="skeleton" class="flex flex-col gap-3 p-4" aria-hidden="true">
      <div v-for="n in 5" :key="n" class="flex items-center gap-3"><SkeletonBlock width="32px" height="32px" radius="9px" /><SkeletonBlock :width="`${30 + ((n * 13) % 30)}%`" /></div>
    </div>
    <ErrorState v-else-if="error" bare :error="error" :retry="retry" />
    <EmptyState v-else-if="items && !items.length" :icon="icon" :title="emptyTitle" :description="emptyBody" />
    <TransitionGroup v-else-if="items" tag="ul" name="list" class="relative flex flex-col divide-y divide-line">
      <li v-for="item in items" :key="item.id" class="group flex items-center gap-3 px-4 py-2.5" :data-name-row="item.id">
        <span class="grid size-8 shrink-0 place-items-center rounded-[9px] bg-accent-soft text-accent-fg"><component :is="icon" :size="16" aria-hidden="true" /></span>
        <form v-if="editing === item.id" class="flex min-w-0 flex-1 flex-col gap-1" :data-rename="item.id" @submit.prevent="saveEdit(item)">
          <div class="flex items-center gap-1.5">
            <TextInput v-model="editName" size="sm" class="min-w-0 flex-1" :maxlength="100" :invalid="!!editError" @keydown.esc.prevent="editing = null" />
            <IconButton :icon="Check" :label="t('common.save')" size="sm" variant="primary" type="submit" :loading="saving" />
            <IconButton :icon="X" :label="t('common.cancel')" size="sm" @click="editing = null" />
          </div>
          <p v-if="editError" class="text-sm text-danger" role="alert">{{ editError }}</p>
        </form>
        <template v-else>
          <div class="min-w-0 flex-1">
            <p class="truncate text-base font-medium text-fg">{{ item.name }}</p>
            <p v-if="item.subtitle" class="truncate text-xs text-muted">{{ item.subtitle }}</p>
          </div>
          <RouterLink v-if="item.to" :to="item.to" class="shrink-0 rounded-full bg-surface-2 px-2.5 py-1 text-xs font-medium tabular-nums text-muted transition-colors hover:bg-surface-3 hover:text-fg">
            {{ countLabel(item.count) }}
          </RouterLink>
          <span v-else class="shrink-0 text-xs tabular-nums text-muted">{{ countLabel(item.count) }}</span>
          <div v-if="canEdit" class="flex shrink-0 items-center gap-0.5 transition-opacity duration-150 pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 pointer-fine:group-focus-within:opacity-100">
            <IconButton :icon="Pencil" :label="t('davomat.team.list.rename', { name: item.name })" size="sm" @click="startEdit(item)" />
            <IconButton :icon="Trash2" :label="t('davomat.team.list.delete', { name: item.name })" size="sm" @click="remove(item)" />
          </div>
        </template>
      </li>
    </TransitionGroup>
  </section>
</template>
