<script setup lang="ts">
/** Reminder policies as cards: what each does (a small timeline and one line), where it's used. */
import { BellRing, Ellipsis, Moon, Pencil, Plus, Star, Trash2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useHotkey } from "@/core/hotkeys";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { rs, useRouteState } from "@/lib/useRouteState";

import { useDeletePolicy, useMakeDefault, usePolicies } from "../api";
import { summary } from "../draft";
import { clock, parseClock } from "../schedule";
import type { Policy } from "../types";
import PolicyEditor from "./PolicyEditor.vue";
import ReminderTimelinePreview from "./ReminderTimelinePreview.vue";

const { t } = useI18n();
const confirm = useConfirm();
const { isPhone } = useBreakpoints();
const query = usePolicies();
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const makeDefault = useMakeDefault();
const remove = useDeletePolicy();

const editorOpen = ref(false);
const editing = ref<Policy | null>(null);
function create(): void {
  editing.value = null;
  editorOpen.value = true;
}
function edit(policy: Policy): void {
  editing.value = policy;
  editorOpen.value = true;
}
useHotkey("n", create, { description: "reminders.keys.new", group: "page" });
// The palette's "New reminder policy" lands here with `?new=1`.
const newParam = useRouteState("new", rs.boolean(false));
watch(
  newParam,
  (value) => {
    if (!value) return;
    create();
    newParam.value = false;
  },
  { immediate: true },
);

async function setDefault(policy: Policy): Promise<void> {
  try {
    await makeDefault.mutateAsync(policy.id);
    toast.success(t("reminders.toast.default"), { description: policy.name });
  } catch {
    // rolled back
  }
}

async function onDelete(policy: Policy): Promise<void> {
  const answer = await confirm({ title: t("reminders.delete.title"), message: t("reminders.delete.body", { name: policy.name }), tone: "danger", confirmLabel: t("common.delete") });
  if (!answer) return;
  try {
    await remove.mutateAsync(policy.id);
    toast.success(t("reminders.toast.deleted"), { description: policy.name });
  } catch {
    // shown by the HTTP layer
  }
}

function menu(policy: Policy): MenuEntry[] {
  const entries: MenuEntry[] = [{ label: t("common.edit"), icon: Pencil, onSelect: () => edit(policy) }];
  if (!policy.is_default) {
    entries.push({ label: t("reminders.makeDefault"), icon: Star, onSelect: () => setDefault(policy) });
    entries.push({ type: "separator" }, { label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => onDelete(policy) });
  }
  return entries;
}

const quiet = (policy: Policy) => {
  const from = parseClock(policy.quiet_from);
  const until = parseClock(policy.quiet_until);
  return from === null || until === null ? null : `${clock(from)}–${clock(until)}`;
};

defineExpose({ create });
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="flex items-center justify-between gap-3">
      <p class="text-sm text-muted">{{ t("reminders.policies.hint") }}</p>
      <UiButton variant="primary" :icon="Plus" :kbd="isPhone ? undefined : 'N'" @click="create">{{ t("reminders.new") }}</UiButton>
    </div>
    <div v-if="skeleton" class="grid gap-3 lg:grid-cols-2"><SkeletonBlock v-for="n in 4" :key="n" height="190px" radius="12px" /></div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.data.value && !query.data.value.length" class="ui-card">
      <EmptyState :icon="BellRing" :title="t('reminders.policies.emptyTitle')" :description="t('reminders.policies.emptyBody')">
        <UiButton variant="primary" :icon="Plus" @click="create">{{ t("reminders.new") }}</UiButton>
      </EmptyState>
    </div>
    <div v-else class="grid gap-3 lg:grid-cols-2">
      <article
        v-for="policy in query.data.value"
        :key="policy.id"
        :class="['ui-card flex min-w-0 cursor-pointer flex-col gap-3 p-4 transition-colors hover:border-line-strong', policy.is_default && 'border-primary/40']"
        tabindex="0"
        @click="edit(policy)"
        @keydown.enter.self="edit(policy)"
      >
        <header class="flex min-w-0 items-start gap-2">
          <div class="min-w-0 flex-1">
            <p class="flex min-w-0 items-center gap-2">
              <span class="truncate text-base font-semibold text-fg">{{ policy.name }}</span>
              <span v-if="policy.is_default" class="inline-flex shrink-0 items-center gap-1 rounded-full bg-accent-soft px-2 py-px text-xs font-semibold text-accent-fg"><Star :size="11" />{{ t("reminders.default") }}</span>
            </p>
            <p class="mt-0.5 text-sm text-muted">{{ summary(policy, t) }}</p>
          </div>
          <div @click.stop>
            <DropdownMenu :items="menu(policy)">
              <template #trigger><IconButton :icon="Ellipsis" :label="t('common.more')" size="sm" /></template>
            </DropdownMenu>
          </div>
        </header>
        <ReminderTimelinePreview :policy="policy" compact />
        <footer class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
          <span v-if="quiet(policy)" class="inline-flex items-center gap-1"><Moon :size="12" />{{ t("reminders.policies.quiet", { range: quiet(policy) }) }}</span>
          <span>{{ t("reminders.policies.routines", { n: policy.usage.routines }, policy.usage.routines) }}</span>
          <span>{{ t("reminders.policies.openTasks", { n: policy.usage.open_tasks }, policy.usage.open_tasks) }}</span>
          <span v-if="policy.texts.length">{{ t("reminders.policies.texts", { n: policy.texts.length }, policy.texts.length) }}</span>
        </footer>
      </article>
    </div>
    <PolicyEditor v-model:open="editorOpen" :policy="editing" />
  </div>
</template>
