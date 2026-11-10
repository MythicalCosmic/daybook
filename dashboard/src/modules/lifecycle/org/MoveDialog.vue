<script setup lang="ts">
/**
 * "Move…": where should this person go? Every department (or branch) of the view as a list, the
 * one they are in marked and not choosable. Choosing one opens the job change dialog filled in;
 * nothing changes here.
 */
import { Check, MapPin, Network, Search, Users } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import TextInput from "@/components/TextInput.vue";
import UiDialog from "@/components/UiDialog.vue";
import UserAvatar from "@/components/UserAvatar.vue";

import { fold, moveTargets, sameTarget, type MoveTarget, type OrgNode } from "./tree";
import type { OrgPerson } from "./types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ person: OrgPerson; root: OrgNode }>();
const emit = defineEmits<{ chosen: [target: MoveTarget] }>();

const { t } = useI18n();
const query = ref("");

/** Each target with its depth in the tree (for the indent). */
const rows = computed(() => {
  const depth = new Map<string, number>();
  const visit = (node: OrgNode, level: number) => {
    depth.set(node.key, level);
    for (const child of node.children) visit(child, level + 1);
  };
  visit(props.root, 0);
  const needle = fold(query.value);
  return moveTargets(props.root)
    .map((node) => ({
      node,
      target: node.target!,
      depth: Math.max(0, (depth.get(node.key) ?? 1) - 1),
      name: node.kind === "unplaced" ? t("lifecycle.org.unplaced") : node.name,
      here: sameTarget(props.person, node.target!),
    }))
    .filter((row) => !needle || fold(row.name).includes(needle));
});

function choose(target: MoveTarget): void {
  emit("chosen", target);
  open.value = false;
}
</script>

<template>
  <UiDialog v-model:open="open" size="sm" :title="t('lifecycle.org.moveTitle', { name: person.name })" :description="t('lifecycle.org.moveDescription')">
    <div class="flex flex-col gap-3">
      <div class="flex items-center gap-2.5 rounded-[12px] bg-surface-2/70 px-3 py-2 dark:bg-surface-3/50">
        <UserAvatar :name="person.name" :src="person.photo_url" :size="30" />
        <p class="min-w-0 truncate text-sm font-medium text-fg">{{ person.name }}</p>
      </div>
      <TextInput v-if="rows.length > 7 || query" v-model="query" type="search" size="sm" :icon="Search" clearable :placeholder="t('lifecycle.org.moveSearch')" />
      <ul class="-mx-1 flex max-h-[min(24rem,55dvh)] flex-col gap-0.5 overflow-y-auto px-1" data-move-targets>
        <li v-for="row in rows" :key="row.node.key">
          <button
            type="button"
            :disabled="row.here"
            :class="[
              'flex w-full min-w-0 items-center gap-2.5 rounded-[10px] py-2 pr-3 text-left outline-none transition-colors',
              row.here ? 'cursor-default bg-surface-2/60 text-muted dark:bg-surface-3/40' : 'text-fg hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-[var(--c-ring)] dark:hover:bg-surface-3/60',
            ]"
            :style="{ paddingLeft: `${12 + row.depth * 18}px` }"
            :data-target="row.node.key"
            @click="choose(row.target)"
          >
            <component :is="row.node.kind === 'branch' ? MapPin : row.node.kind === 'unplaced' ? Users : Network" :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
            <span class="min-w-0 flex-1 truncate text-sm font-medium">{{ row.name }}</span>
            <span v-if="row.here" class="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-muted"><Check :size="13" aria-hidden="true" />{{ t("lifecycle.org.here") }}</span>
            <span v-else class="shrink-0 text-xs tabular-nums text-subtle">{{ t("lifecycle.org.people", { n: row.node.count }, row.node.count) }}</span>
          </button>
        </li>
        <li v-if="!rows.length" class="px-3 py-6 text-center text-sm text-muted">{{ t("lifecycle.org.notFound") }}</li>
      </ul>
    </div>
  </UiDialog>
</template>
