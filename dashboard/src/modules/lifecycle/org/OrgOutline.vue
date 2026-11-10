<script setup lang="ts">
/**
 * The org chart on a phone: the same tree as an indented outline, no canvas. The company and its
 * owners on top; each part a row that folds open to its head, its people by job title, its open
 * places and the parts below it. A person opens Person 360; "Move…" in their menu moves them.
 */
import { Building2 } from "@lucide/vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import UserAvatar from "@/components/UserAvatar.vue";

import { useOrgContext } from "./context";
import OrgOutlineNode from "./OrgOutlineNode.vue";
import type { OrgNode } from "./tree";
import type { OrgRef } from "./types";

defineProps<{ root: OrgNode; owners: OrgRef[] }>();

const { t } = useI18n();
const org = useOrgContext();
</script>

<template>
  <div class="flex flex-col gap-3" data-org-outline>
    <section class="ui-card overflow-hidden">
      <header class="flex items-center gap-2.5 px-4 pb-2 pt-3.5">
        <span class="grid size-8 shrink-0 place-items-center rounded-[9px] bg-accent-soft text-primary"><Building2 :size="16" aria-hidden="true" /></span>
        <div class="min-w-0 flex-1">
          <h2 class="truncate text-md font-semibold text-fg">{{ root.name }}</h2>
          <p class="text-xs tabular-nums text-muted">{{ t("lifecycle.org.people", { n: root.total }, root.total) }}</p>
        </div>
      </header>
      <ul class="flex flex-col px-2 pb-2">
        <li v-for="owner in owners" :key="owner.id">
          <RouterLink :to="org.profileUrl(owner.id)" class="flex min-w-0 items-center gap-2.5 rounded-[10px] px-2 py-2 active:bg-surface-2">
            <UserAvatar :name="owner.name" :src="owner.photo_url" :size="32" />
            <span class="min-w-0 leading-tight">
              <span class="block truncate text-base font-semibold text-fg">{{ owner.name }}</span>
              <span class="block truncate text-xs text-muted">{{ t("lifecycle.org.owner") }}</span>
            </span>
          </RouterLink>
        </li>
      </ul>
    </section>
    <ul class="flex flex-col gap-2.5">
      <OrgOutlineNode v-for="child in root.children" :key="child.key" :node="child" :depth="0" />
    </ul>
  </div>
</template>
