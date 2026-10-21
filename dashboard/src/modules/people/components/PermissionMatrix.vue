<script setup lang="ts">
/**
 * The roles matrix (plan §6.2, C's own component): permissions as rows grouped by area under
 * sticky headings, roles as columns with sticky names. The Owner column is locked (owners hold
 * everything); a role the editor may not change is read-only (rule 1), and permissions the editor
 * doesn't hold are greyed out (rule 2). Changes are staged in `draft` until the page saves them.
 *
 *   <PermissionMatrix :roles="roles" :permissions="registry" v-model:draft="draft" :grantable="(code) => can(code)" />
 */
import { Crown, Lock } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { PermissionInfo } from "@/api/types";
import CheckBox from "@/components/CheckBox.vue";
import UiTooltip from "@/components/UiTooltip.vue";

import type { Role } from "../types";

/** Role id → its permission codes as edited (only roles that changed). */
const draft = defineModel<Record<number, string[]>>("draft", { default: () => ({}) });

const props = defineProps<{
  roles: Role[];
  permissions: PermissionInfo[];
  /** Whether the editor may put this permission in a bundle (or take it out). */
  grantable: (code: string) => boolean;
  /** Narrow to one area ("finance"); empty shows all. */
  area?: string;
  query?: string;
}>();

defineSlots<{ header?: (props: { role: Role }) => unknown }>();

const { t, te } = useI18n();

export interface PermissionGroup {
  area: string;
  label: string;
  items: PermissionInfo[];
}

const groups = computed<PermissionGroup[]>(() => {
  const needle = (props.query ?? "").trim().toLowerCase();
  const out: PermissionGroup[] = [];
  for (const perm of props.permissions) {
    if (props.area && perm.group !== props.area) continue;
    if (needle && !`${perm.label} ${perm.code}`.toLowerCase().includes(needle)) continue;
    let group = out.find((g) => g.area === perm.group);
    if (!group) {
      group = { area: perm.group, label: areaLabel(perm.group), items: [] };
      out.push(group);
    }
    group.items.push(perm);
  }
  return out;
});

function areaLabel(area: string): string {
  const key = `people.area.${area}`;
  return te(key) ? t(key) : area;
}

function codes(role: Role): string[] {
  return draft.value[role.id] ?? role.permissions;
}

function has(role: Role, code: string): boolean {
  return role.is_owner || codes(role).includes(code);
}

function changed(role: Role, code: string): boolean {
  const staged = draft.value[role.id];
  return !!staged && staged.includes(code) !== role.permissions.includes(code);
}

function editable(role: Role, code: string): boolean {
  return !role.is_owner && role.can_edit && props.grantable(code);
}

function toggle(role: Role, code: string, value: boolean): void {
  const current = new Set(codes(role));
  if (value) current.add(code);
  else current.delete(code);
  const next = props.permissions.map((p) => p.code).filter((c) => current.has(c));
  const same = next.length === role.permissions.length && next.every((c) => role.permissions.includes(c));
  const copy = { ...draft.value };
  if (same) delete copy[role.id];
  else copy[role.id] = next;
  draft.value = copy;
}

function reason(role: Role, code: string): string | undefined {
  if (role.is_owner) return t("people.roles.ownerLocked");
  if (!role.can_edit) return t("people.roles.cantEdit");
  if (!props.grantable(code)) return t("people.roles.notYours");
  return undefined;
}

function countIn(role: Role, group: PermissionGroup): number {
  return group.items.filter((item) => has(role, item.code)).length;
}
</script>

<template>
  <div class="matrix ui-card overflow-auto" :style="{ '--cols': roles.length }">
    <table class="w-full border-separate border-spacing-0 text-sm">
      <thead>
        <tr>
          <th scope="col" class="corner sticky left-0 top-0 z-30 border-b border-r border-line bg-surface px-4 py-3 text-left align-bottom text-xs font-semibold uppercase tracking-[0.05em] text-subtle">
            {{ t("people.roles.permission") }}
          </th>
          <th
            v-for="role in roles"
            :key="role.id"
            scope="col"
            class="sticky top-0 z-20 min-w-[104px] border-b sm:min-w-[132px] border-line bg-surface px-3 py-3 text-center align-top font-semibold"
          >
            <slot name="header" :role="role">
              <span class="inline-flex items-center gap-1 text-fg"><Crown v-if="role.is_owner" :size="13" class="text-primary" />{{ role.name }}</span>
            </slot>
          </th>
        </tr>
      </thead>
      <tbody v-for="group in groups" :key="group.area">
        <tr>
          <th scope="rowgroup" class="group-head sticky left-0 z-10 border-b border-r border-line bg-surface-2 px-4 py-2 text-left text-xs font-semibold text-muted dark:bg-surface-2">
            {{ group.label }}
          </th>
          <td v-for="role in roles" :key="role.id" class="border-b border-line bg-surface-2 px-3 py-2 text-center text-xs tabular-nums text-subtle dark:bg-surface-2">
            {{ role.is_owner ? group.items.length : countIn(role, group) }}/{{ group.items.length }}
          </td>
        </tr>
        <tr v-for="perm in group.items" :key="perm.code" class="row">
          <th scope="row" class="sticky left-0 z-10 max-w-[360px] border-b border-r border-line bg-surface px-4 py-2.5 text-left font-normal">
            <span class="block text-base text-fg">{{ perm.label }}</span>
            <code class="mt-0.5 block text-[11px] text-subtle">{{ perm.code }}</code>
          </th>
          <td v-for="role in roles" :key="role.id" :class="['border-b border-line px-3 py-2.5 text-center', role.is_owner && 'bg-surface-2/60', changed(role, perm.code) && 'is-changed']">
            <UiTooltip :content="reason(role, perm.code)" :disabled="!reason(role, perm.code)">
              <span class="inline-flex items-center justify-center">
                <Lock v-if="role.is_owner" :size="14" class="text-primary" :aria-label="t('people.roles.ownerLocked')" />
                <CheckBox
                  v-else
                  :model-value="has(role, perm.code)"
                  :disabled="!editable(role, perm.code)"
                  :aria-label="`${role.name}: ${perm.label}`"
                  @update:model-value="(value: boolean) => toggle(role, perm.code, value)"
                />
              </span>
            </UiTooltip>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!groups.length" class="px-4 py-10 text-center text-sm text-muted">{{ t("people.roles.noMatch") }}</p>
  </div>
</template>

<style scoped>
.matrix {
  max-height: min(calc(100dvh - 260px), 900px);
}
/* Opaque, so the sticky first column never shows what scrolls under it. */
.row:hover th,
.row:hover td:not(.is-changed) {
  background-color: color-mix(in srgb, var(--c-text) 4%, var(--c-surface));
}
.is-changed {
  background-color: color-mix(in srgb, var(--c-warning) 14%, var(--c-surface));
}
.corner {
  min-width: 280px;
}
/* Phones show one role at a time: the permission column takes what the role column leaves. */
@media (max-width: 639px) {
  .corner {
    min-width: 0;
  }
}
</style>
