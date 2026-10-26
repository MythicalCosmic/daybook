<script setup lang="ts">
/**
 * A department in the org chart: its name, its head (or that it has none yet), how many people
 * are directly in it and, when sub-departments add people, how many in all. The whole card opens
 * its panel; the head's name opens their page; with `canEdit` a menu changes the structure.
 */
import { Ellipsis, UserRound, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import DropdownMenu from "@/components/DropdownMenu.vue";
import IconButton from "@/components/IconButton.vue";
import PersonCell from "@/components/PersonCell.vue";
import UiTooltip from "@/components/UiTooltip.vue";

import { departmentCounts } from "../departments";
import type { Department } from "../types";
import { departmentMenu, type DepartmentAction } from "./departmentMenu";

const props = defineProps<{ department: Department; hasChildren: boolean; selected?: boolean; canEdit?: boolean; top?: boolean }>();
const emit = defineEmits<{ open: []; action: [action: DepartmentAction] }>();

const { t } = useI18n();
const counts = computed(() => departmentCounts(props.department, props.hasChildren));

const menu = computed(() => departmentMenu(props.department, t, (action) => emit("action", action)));
</script>

<template>
  <article
    :class="[
      'dept-card group/card relative flex w-full min-w-0 flex-col gap-2.5 rounded-card border bg-surface p-3.5 transition-[border-color,box-shadow] duration-150 sm:max-w-[21rem]',
      selected ? 'border-primary ring-2 ring-primary/25' : 'border-line hover:border-line-strong',
    ]"
    :data-department="department.id"
  >
    <div class="flex min-w-0 items-start gap-2">
      <h3 class="min-w-0 flex-1 pt-0.5">
        <!-- The name stretches over the whole card: anywhere on it opens the panel. -->
        <button
          type="button"
          :class="[
            'block w-full text-left leading-snug text-fg outline-none after:absolute after:inset-0 after:rounded-card focus-visible:after:ring-2 focus-visible:after:ring-[var(--c-ring)]',
            top ? 'text-md font-semibold' : 'text-base font-semibold',
          ]"
          :aria-label="t('people.dept.open', { name: department.name })"
          :aria-expanded="selected"
          data-open-department
          @click="emit('open')"
        >
          <span class="line-clamp-2 break-words">{{ department.name }}</span>
        </button>
      </h3>
      <DropdownMenu v-if="canEdit" :items="menu" align="end">
        <template #trigger>
          <IconButton :icon="Ellipsis" size="sm" variant="ghost" :label="t('people.dept.actions')" class="relative z-[1] -mr-1.5 -mt-1" data-department-menu />
        </template>
      </DropdownMenu>
    </div>

    <!-- Clicks between the head's parts fall through to the card. -->
    <div class="pointer-events-none relative z-[1] min-w-0">
      <div v-if="department.head" class="pointer-events-auto w-fit max-w-full" data-head>
        <PersonCell :person="department.head" :subtitle="t('people.dept.head')" link />
      </div>
      <div v-else class="flex min-w-0 items-center gap-2.5" data-no-head>
        <span class="grid size-7 shrink-0 place-items-center rounded-full border border-dashed border-line-strong text-subtle">
          <UserRound :size="14" aria-hidden="true" />
        </span>
        <span class="min-w-0 leading-tight">
          <span class="block truncate text-sm text-subtle">{{ t("people.dept.noHead") }}</span>
          <button
            v-if="canEdit"
            type="button"
            class="pointer-events-auto mt-0.5 block text-xs font-semibold text-primary hover:underline"
            data-set-head
            @click="emit('action', 'head')"
          >
            {{ t("people.dept.setHead") }}
          </button>
        </span>
      </div>
    </div>

    <p class="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 border-t border-line pt-2.5 text-xs text-muted" data-counts>
      <Users :size="13" class="shrink-0 text-subtle" aria-hidden="true" />
      <span v-if="counts.direct" class="tabular-nums">{{ t("people.dept.people", { n: counts.direct }, counts.direct) }}</span>
      <span v-else class="text-subtle">{{ t("people.dept.nobody") }}</span>
      <template v-if="counts.total !== null">
        <span class="text-subtle" aria-hidden="true">·</span>
        <UiTooltip :content="t('people.dept.totalHint')">
          <span class="pointer-events-auto relative z-[1] font-medium tabular-nums text-fg" data-total>{{ t("people.dept.total", { n: counts.total }) }}</span>
        </UiTooltip>
      </template>
    </p>
  </article>
</template>
