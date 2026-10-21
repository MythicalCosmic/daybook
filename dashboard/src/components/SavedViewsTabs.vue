<script setup lang="ts">
/**
 * Saved views as tabs above a list (plan §6.2: "All open, Late now, Waiting for check, Today,
 * custom"): built-in views first, then the person's own and shared ones, each with an optional
 * count. When the filters differ from the active view (`dirty`), "Save view" offers to save them
 * (and "Save changes" on one's own view). Own views have a menu: rename, share, delete.
 *
 *   const views = useSavedViews("tasks");
 *   <SavedViewsTabs v-model="viewId" :views="[...builtins, ...views.tabs.value]" :dirty="changed"
 *     @save="(input) => views.create.mutate({ name: input.name, is_shared: input.shared, state })"
 *     @update="(view) => views.update.mutate({ id: Number(view.id), state })" … />
 */
import { Ellipsis, Pencil, Plus, Share2, Trash2, Users } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { SavedViewTab } from "@/lib/useSavedViews";

import { useSlidingIndicator } from "./useSlidingIndicator";

import CheckBox from "./CheckBox.vue";
import DropdownMenu, { type MenuEntry } from "./DropdownMenu.vue";
import TextInput from "./TextInput.vue";
import UiBadge from "./UiBadge.vue";
import UiButton from "./UiButton.vue";
import UiPopover from "./UiPopover.vue";
import { useConfirm } from "./useConfirm";

/** A tab: a built-in view (`builtin`) or a saved one (`savedViewTab(view)` from useSavedViews). */
export type ViewTab = SavedViewTab;

const active = defineModel<ViewTab["id"]>({ required: true });

const props = withDefaults(defineProps<{ views: ViewTab[]; dirty?: boolean; canSave?: boolean; max?: number }>(), { dirty: false, canSave: true, max: 6 });

const emit = defineEmits<{
  save: [input: { name: string; shared: boolean }];
  update: [view: ViewTab];
  rename: [view: ViewTab, name: string];
  share: [view: ViewTab, shared: boolean];
  delete: [view: ViewTab];
}>();

const { t } = useI18n();
const confirm = useConfirm();

const visible = computed(() => {
  const head = props.views.slice(0, props.max);
  const current = props.views.find((view) => view.id === active.value);
  // The active view is always a visible tab.
  if (current && !head.includes(current)) head.splice(head.length - 1, 1, current);
  return head;
});
const overflow = computed(() => props.views.filter((view) => !visible.value.includes(view)));
const current = computed(() => props.views.find((view) => view.id === active.value) ?? null);

// Sliding underline: follows the active view, also when a count arrives and widens a tab before it.
const strip = ref<HTMLElement | null>(null);
const { indicator } = useSlidingIndicator(strip, {
  active: () => '[data-active="true"]',
  items: "[data-active]",
  deps: [active, () => visible.value.map((view) => `${view.id}:${view.name}:${view.count ?? ""}`).join("|"), () => props.dirty],
});

// Save as new.
const saving = ref(false);
const name = ref("");
const shared = ref(false);
watch(saving, (open) => {
  if (open) {
    name.value = "";
    shared.value = false;
  }
});
function save(): void {
  if (!name.value.trim()) return;
  emit("save", { name: name.value.trim(), shared: shared.value });
  saving.value = false;
}

// Rename.
const renaming = ref<ViewTab | null>(null);
const newName = ref("");
function startRename(view: ViewTab): void {
  renaming.value = view;
  newName.value = view.name;
}
function rename(): void {
  if (renaming.value && newName.value.trim()) emit("rename", renaming.value, newName.value.trim());
  renaming.value = null;
}

async function remove(view: ViewTab): Promise<void> {
  const answer = await confirm({ title: t("common.views.deleteConfirm", { name: view.name }), tone: "danger", confirmLabel: t("common.delete") });
  if (answer) emit("delete", view);
}

function menuFor(view: ViewTab): MenuEntry[] {
  return [
    { label: t("common.views.rename"), icon: Pencil, onSelect: () => startRename(view) },
    { label: view.shared ? t("common.views.unshare") : t("common.views.share"), icon: Share2, onSelect: () => emit("share", view, !view.shared) },
    { type: "separator" },
    { label: t("common.views.delete"), icon: Trash2, danger: true, onSelect: () => void remove(view) },
  ];
}

const overflowMenu = computed<MenuEntry[]>(() => overflow.value.map((view) => ({ label: view.name, icon: view.shared ? Users : undefined, onSelect: () => (active.value = view.id) })));
</script>

<template>
  <div class="flex min-w-0 items-center gap-2 border-b border-line">
    <div ref="strip" role="tablist" class="no-scrollbar relative -mb-px flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto">
      <div v-for="view in visible" :key="view.id" class="group/tab relative flex shrink-0 items-center" :data-active="view.id === active">
        <template v-if="renaming?.id === view.id">
          <form class="flex h-10 items-center" @submit.prevent="rename">
            <TextInput v-model="newName" size="sm" autofocus class="w-[160px]" @blur="rename" @keydown.esc="renaming = null" />
          </form>
        </template>
        <button
          v-else
          type="button"
          role="tab"
          :aria-selected="view.id === active"
          :class="[
            'flex h-10 items-center gap-1.5 whitespace-nowrap rounded-t-[6px] px-2.5 text-base font-[550] transition-colors',
            view.id === active ? 'text-fg' : 'text-muted hover:text-fg',
            view.mine && !view.builtin && view.id === active && 'pr-1',
          ]"
          @click="active = view.id"
        >
          <Users v-if="view.shared && !view.builtin" :size="13" class="text-subtle" :aria-label="t('common.views.shared')" />
          {{ view.name }}
          <UiBadge v-if="view.count !== undefined" :count="view.count" :tone="view.id === active ? 'primary' : 'neutral'" />
          <span v-if="dirty && view.id === active" class="size-1.5 rounded-full bg-warning" :title="t('common.views.modified')" />
        </button>
        <DropdownMenu v-if="view.mine && !view.builtin && view.id === active && renaming?.id !== view.id" :items="menuFor(view)" width="210px" align="start">
          <template #trigger>
            <button type="button" class="mr-1 grid size-6 place-items-center rounded-[6px] text-subtle hover:bg-highlight hover:text-fg" :aria-label="t('common.views.options')">
              <Ellipsis :size="14" />
            </button>
          </template>
        </DropdownMenu>
      </div>
      <DropdownMenu v-if="overflow.length" :items="overflowMenu" width="220px" align="start">
        <template #trigger>
          <button type="button" class="flex h-10 shrink-0 items-center gap-1 px-2.5 text-base font-[550] text-muted hover:text-fg">
            {{ t("common.views.more") }}
            <UiBadge :count="overflow.length" tone="neutral" />
          </button>
        </template>
      </DropdownMenu>
      <span
        v-if="indicator"
        class="pointer-events-none absolute bottom-0 h-[2px] rounded-full bg-primary transition-[left,width] duration-240 ease-out"
        :style="{ left: `${indicator.left}px`, width: `${indicator.width}px` }"
        aria-hidden="true"
      />
    </div>

    <div v-if="canSave && dirty" class="flex shrink-0 items-center gap-1 pb-1">
      <UiButton v-if="current?.mine && !current.builtin" size="sm" variant="ghost" @click="emit('update', current)">{{ t("common.views.saveChanges") }}</UiButton>
      <UiPopover v-model:open="saving" width="280px" align="end">
        <template #trigger>
          <UiButton size="sm" variant="soft" :icon="Plus">{{ current?.mine && !current.builtin ? t("common.views.saveAsNew") : t("common.views.save") }}</UiButton>
        </template>
        <form class="flex flex-col gap-3" @submit.prevent="save">
          <label class="flex flex-col gap-1.5 text-sm font-semibold text-fg">
            {{ t("common.views.name") }}
            <TextInput v-model="name" autofocus :maxlength="60" />
          </label>
          <CheckBox v-model="shared" size="sm" :label="t('common.views.share')" />
          <div class="flex justify-end gap-2">
            <UiButton size="sm" variant="ghost" @click="saving = false">{{ t("common.cancel") }}</UiButton>
            <UiButton size="sm" variant="primary" type="submit" :disabled="!name.trim()">{{ t("common.save") }}</UiButton>
          </div>
        </form>
      </UiPopover>
    </div>
  </div>
</template>
