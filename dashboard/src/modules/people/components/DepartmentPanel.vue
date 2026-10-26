<script setup lang="ts">
/**
 * A department's panel: its head (and whom the head reports to), the people directly in it with a
 * way to take someone out, "Add people" (current members; whoever is in another department moves
 * here), its sub-departments, and everyone in it and below on the Team list.
 */
import { ArrowRight, ChevronRight, Network, UserPlus, UserRound, X } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import IconButton from "@/components/IconButton.vue";
import MultiSelect from "@/components/MultiSelect.vue";
import type { SelectOption } from "@/components/options";
import PersonCell from "@/components/PersonCell.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { useDepartmentMutations, useDepartmentPeople, usePeople } from "../api";
import { flattenDepartments, headAbove } from "../departments";
import type { Department, Person } from "../types";
import type { DepartmentAction } from "./departmentMenu";

const props = withDefaults(defineProps<{ department: Department; departments: Department[]; canEdit?: boolean; canPlace?: boolean }>(), {
  canEdit: false,
  canPlace: false,
});
const emit = defineEmits<{ open: [department: Department]; action: [action: DepartmentAction, department: Department] }>();

const { t } = useI18n();
const company = useCompanyStore();
const { addMembers, removeMember } = useDepartmentMutations();

const id = computed(() => props.department.id);
const people = useDepartmentPeople(id);
/** Directly in it: the list also holds the departments below. */
const direct = computed(() => (people.data.value?.results ?? []).filter((row) => row.department?.id === id.value));
const above = computed(() => headAbove(props.departments, id.value));
const children = computed(() => flattenDepartments(props.departments).find((node) => node.department.id === id.value)?.children ?? []);

// ─── Add people ──────────────────────────────────────────────────────────────
const adding = ref(false);
const chosen = ref<number[]>([]);
const everyone = usePeople({ status: "current", ordering: "name", page_size: 500 }, adding);
const options = computed<SelectOption<number>[]>(() =>
  (everyone.data.value?.results ?? [])
    .filter((row) => row.department?.id !== id.value)
    .map((row: Person) => ({
      value: row.id,
      label: row.name,
      description: [row.position?.name, row.department ? t("people.dept.nowIn", { name: row.department.name }) : null].filter(Boolean).join(" · ") || undefined,
      avatar: { name: row.name, src: row.photo_url },
    })),
);
watch(id, () => {
  adding.value = false;
  chosen.value = [];
});

async function add(): Promise<void> {
  if (!chosen.value.length) return;
  try {
    await addMembers.mutateAsync({ id: id.value, memberIds: chosen.value });
    toast.success(t("people.dept.added", { name: props.department.name, n: chosen.value.length }));
    chosen.value = [];
    adding.value = false;
  } catch {
    // The HTTP layer showed why.
  }
}

async function takeOut(person: Person): Promise<void> {
  const departmentId = id.value;
  const name = props.department.name;
  try {
    await removeMember.mutateAsync({ departmentId, memberId: person.id });
    toast.success(t("people.dept.removed", { person: person.name, name }), {
      action: { label: t("common.undo"), onClick: () => addMembers.mutate({ id: departmentId, memberIds: [person.id] }) },
    });
  } catch {
    // Back in the list; the HTTP layer showed why.
  }
}

const teamLink = computed(() => `/c/${company.currentId}/people?department=${id.value}`);
</script>

<template>
  <div class="flex flex-col gap-6 p-5" :data-department-panel="department.id">
    <!-- The head -->
    <section class="flex flex-col gap-2.5" data-panel-head>
      <h3 class="text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("people.dept.head") }}</h3>
      <div v-if="department.head" class="flex items-center justify-between gap-3">
        <PersonCell :person="department.head" link size="lg" />
        <UiButton v-if="canEdit" size="sm" variant="ghost" @click="emit('action', 'head', department)">{{ t("people.dept.changeHead") }}</UiButton>
      </div>
      <div v-else class="flex items-center justify-between gap-3">
        <span class="flex min-w-0 items-center gap-2.5">
          <span class="grid size-9 shrink-0 place-items-center rounded-full border border-dashed border-line-strong text-subtle"><UserRound :size="16" aria-hidden="true" /></span>
          <span class="truncate text-base text-muted">{{ t("people.dept.noHead") }}</span>
        </span>
        <UiButton v-if="canEdit" size="sm" variant="secondary" data-panel-set-head @click="emit('action', 'head', department)">{{ t("people.dept.setHead") }}</UiButton>
      </div>
      <p class="text-sm text-muted">{{ t("people.dept.headHint") }}</p>
      <p v-if="department.head && above" class="flex min-w-0 flex-wrap items-center gap-x-1.5 text-sm text-muted" data-head-above>
        <span>{{ t("people.reportsTo") }}:</span>
        <RouterLink :to="`/c/${company.currentId}/people/${above.head.id}`" class="font-medium text-fg hover:text-primary hover:underline">{{ above.head.name }}</RouterLink>
        <span class="text-subtle">· {{ above.department.name }}</span>
      </p>
    </section>

    <!-- The people directly in it -->
    <section class="flex flex-col gap-3">
      <div class="flex items-center justify-between gap-3">
        <h3 class="text-xs font-semibold uppercase tracking-[0.06em] text-subtle">
          {{ t("people.dept.panelPeople") }}<span v-if="people.data.value" class="ml-1.5 tabular-nums text-muted">{{ direct.length }}</span>
        </h3>
        <UiButton v-if="canPlace && !adding" size="sm" variant="secondary" :icon="UserPlus" data-add-people @click="adding = true">{{ t("people.dept.addPeople") }}</UiButton>
      </div>

      <div v-if="adding" class="flex flex-col gap-2.5 rounded-[12px] border border-line bg-surface-2/50 p-3" data-add-picker>
        <MultiSelect
          v-model="chosen"
          :options="options"
          :placeholder="t('common.picker.people')"
          :search-placeholder="t('common.picker.searchPeople')"
          :empty-text="everyone.isPending.value ? undefined : t('people.dept.nobodyToAdd')"
        />
        <p class="text-xs text-muted">{{ t("people.dept.addHint") }}</p>
        <div class="flex justify-end gap-2">
          <UiButton size="sm" variant="ghost" @click="(adding = false), (chosen = [])">{{ t("common.cancel") }}</UiButton>
          <UiButton size="sm" variant="primary" :disabled="!chosen.length" :loading="addMembers.isPending.value" data-add-confirm @click="add">
            {{ t("people.dept.addCount", { n: chosen.length }) }}
          </UiButton>
        </div>
      </div>

      <div v-if="people.isPending.value" class="flex flex-col gap-3">
        <div v-for="n in 3" :key="n" class="flex items-center gap-3"><SkeletonBlock circle height="28px" /><SkeletonBlock width="60%" /></div>
      </div>
      <ul v-else-if="direct.length" class="-mx-2 flex flex-col" data-panel-people>
        <li v-for="person in direct" :key="person.id" class="group/person flex items-center gap-2 rounded-[10px] px-2 py-1.5 hover:bg-highlight" :data-person="person.id">
          <PersonCell class="min-w-0 flex-1" :person="person" :subtitle="person.position?.name ?? t('people.noPosition')" link />
          <UiBadge v-if="department.head?.id === person.id" tone="primary" size="sm">{{ t("people.dept.head") }}</UiBadge>
          <IconButton
            v-if="canPlace"
            :icon="X"
            size="sm"
            :label="t('people.dept.remove')"
            tooltip-side="left"
            class="shrink-0 opacity-60 transition-opacity group-hover/person:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100"
            data-take-out
            @click="takeOut(person)"
          />
        </li>
      </ul>
      <p v-else class="text-sm text-muted" data-no-people>{{ t("people.dept.noPeople") }}</p>
    </section>

    <!-- Sub-departments -->
    <section v-if="children.length" class="flex flex-col gap-2">
      <h3 class="text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("people.dept.subs") }}</h3>
      <ul class="-mx-2 flex flex-col">
        <li v-for="child in children" :key="child.department.id">
          <button
            type="button"
            class="flex w-full items-center gap-2.5 rounded-[10px] px-2 py-2 text-left hover:bg-highlight"
            :data-sub="child.department.id"
            @click="emit('open', child.department)"
          >
            <span class="grid size-7 shrink-0 place-items-center rounded-[8px] bg-surface-2 text-muted"><Network :size="14" aria-hidden="true" /></span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-base font-medium text-fg">{{ child.department.name }}</span>
              <span class="block truncate text-xs text-muted">{{ child.department.head?.name ?? t("people.dept.noHead") }}</span>
            </span>
            <span class="shrink-0 text-xs tabular-nums text-muted">{{ t("people.dept.people", { n: child.department.total_count }, child.department.total_count) }}</span>
            <ChevronRight :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
          </button>
        </li>
      </ul>
    </section>

    <RouterLink
      v-if="department.total_count"
      :to="teamLink"
      class="inline-flex w-fit items-center gap-1.5 text-sm font-medium text-primary hover:underline"
      data-team-link
    >
      {{ t("people.dept.everyone", { n: department.total_count }) }}<ArrowRight :size="14" aria-hidden="true" />
    </RouterLink>
  </div>
</template>
