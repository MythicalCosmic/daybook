<script setup lang="ts">
/**
 * A person in the org chart, more closely (the hover card's content, and the phone's sheet): their
 * job, where they sit and who they report to, their statuses, the move waiting for them, and the
 * way to their profile and to "Move…", or why they can't be moved.
 */
import { ArrowUpRight, Lock, Shuffle } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useFormat } from "@/lib/useFormat";

import { useOrgContext } from "./context";
import { badges } from "./tree";
import type { OrgPerson } from "./types";

const props = defineProps<{ person: OrgPerson }>();

const { t } = useI18n();
const fmt = useFormat();
const org = useOrgContext();

const position = computed(() => (props.person.position_id !== null ? (org.positions.value.get(props.person.position_id)?.name ?? null) : null));
const list = computed(() => badges(props.person));
const department = computed(() => org.departmentName(props.person.department_id));
const branch = computed(() => org.branchName(props.person.home_branch_id));
const manager = computed(() => org.personName(props.person.manager_id));
const facts = computed(() =>
  [
    department.value ? { key: "department", label: t("lifecycle.org.card.department"), value: department.value } : null,
    branch.value ? { key: "branch", label: t("lifecycle.org.card.branch"), value: branch.value } : null,
    manager.value ? { key: "manager", label: t("lifecycle.org.card.reportsTo"), value: manager.value } : null,
  ].filter((fact): fact is { key: string; label: string; value: string } => fact !== null),
);
const badgeLabel = (key: string, day: string | null) => (day ? t(`lifecycle.org.badge.${key}`, { date: fmt.day(day, "short") }) : t(`lifecycle.org.badge.${key}Open`));
</script>

<template>
  <div class="flex flex-col" data-org-card>
    <div class="flex items-start gap-3 p-4 pb-3">
      <UserAvatar :name="person.name" :src="person.photo_url" :size="44" />
      <div class="min-w-0 flex-1">
        <p class="truncate text-md font-semibold leading-6 text-fg">{{ person.name }}</p>
        <p class="truncate text-sm text-muted">{{ position ?? t("lifecycle.org.noPosition") }}<template v-if="person.is_owner"> · {{ t("lifecycle.org.owner") }}</template></p>
        <div v-if="list.length" class="mt-1.5 flex flex-wrap gap-1">
          <StatusPill v-for="badge in list" :key="badge.key" size="sm" :tone="badge.tone" :label="badgeLabel(badge.key, badge.day)" />
        </div>
      </div>
    </div>
    <dl v-if="facts.length" class="mx-4 mb-3 flex flex-col gap-1.5 rounded-[10px] bg-surface-2/70 p-2.5 text-sm dark:bg-surface-3/50">
      <div v-for="fact in facts" :key="fact.key" class="flex min-w-0 items-baseline justify-between gap-3">
        <dt class="shrink-0 text-xs text-muted">{{ fact.label }}</dt>
        <dd class="min-w-0 truncate text-right font-medium text-fg">{{ fact.value }}</dd>
      </div>
    </dl>
    <p v-if="!person.may_move && org.can.value.move && person.why_not" class="mx-4 mb-3 flex items-start gap-1.5 text-xs text-muted" data-why-not>
      <Lock :size="13" class="mt-px shrink-0 text-subtle" aria-hidden="true" />{{ t(`lifecycle.org.whyNot.${person.why_not}`) }}
    </p>
    <div class="flex items-center justify-between gap-2 border-t border-line px-3 py-2">
      <RouterLink :to="org.profileUrl(person.id)" class="inline-flex items-center gap-1 rounded-[8px] px-1.5 py-1 text-sm font-semibold text-primary hover:bg-surface-2/60">
        {{ t("common.person.open") }}<ArrowUpRight :size="15" aria-hidden="true" />
      </RouterLink>
      <UiButton v-if="person.may_move" size="sm" variant="secondary" :icon="Shuffle" data-card-move @click="org.startMove(person)">{{ t("lifecycle.org.move") }}</UiButton>
    </div>
  </div>
</template>
