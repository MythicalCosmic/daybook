<script setup lang="ts">
/**
 * Settings › Users and roles (docs/DAVOMAT.md §1.3, `users/`): the people who sign in to this app,
 * each with a role (Owner, Administrator, Manager, Viewer), the locations a manager or a viewer
 * sees, the last sign-in and whether their Telegram gets the bot's messages. Add one with a first
 * password, change one, set a new password, link their Telegram, deactivate and bring back. What
 * each role may do is spelled out below the list.
 */
import { Crown, Ellipsis, Eye, KeyRound, Pencil, Power, Search, Send, ShieldCheck, UserCog, UserPlus, UserX } from "@lucide/vue";
import { computed, ref, watch, type Component } from "vue";
import { useI18n } from "vue-i18n";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SegmentedControl, { type SegmentOption } from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { normalize } from "@/components/options";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useCompanyStore } from "@/stores/company";

import { activateUser, deactivateUser, useRefresh, useRoles, userTelegramLink, userTelegramUnlink, useUsers } from "../api";
import PasswordDialog from "../components/settings/PasswordDialog.vue";
import { roleTone, type KnownKind } from "../components/settings/roles";
import TelegramLinkDialog from "../components/settings/TelegramLinkDialog.vue";
import UserDialog from "../components/settings/UserDialog.vue";
import type { RoleKind, User } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();

const users = useUsers();
const roles = useRoles();
const skeleton = useDelayedPending(computed(() => users.isPending.value));

type Filter = "all" | RoleKind | "inactive";
const filter = ref<Filter>("all");
const query = ref("");

const fullName = (user: User) => [user.first_name, user.last_name].filter(Boolean).join(" ") || user.username;
const isSelf = (user: User) => user.is_self ?? user.id === company.current?.membership_id;
/** A user's role kind; "other" for someone whose role isn't a web role any more. */
const kindOf = (user: User): KnownKind => user.role?.kind ?? "other";
const roleName = (user: User) => user.role?.name ?? t("davomat.users.noRole");

const ORDER: Record<KnownKind, number> = { owner: 0, admin: 1, manager: 2, viewer: 3, other: 4 };
const all = computed(() =>
  [...(users.data.value ?? [])].sort(
    (a, b) => Number(b.is_active) - Number(a.is_active) || ORDER[kindOf(a)] - ORDER[kindOf(b)] || fullName(a).localeCompare(fullName(b)),
  ),
);

const counts = computed(() => {
  const out: Record<Filter, number> = { all: 0, owner: 0, admin: 0, manager: 0, viewer: 0, inactive: 0 };
  for (const user of all.value) {
    if (!user.is_active) out.inactive++;
    else {
      out.all++;
      const kind = kindOf(user);
      if (kind !== "other") out[kind] += 1;
    }
  }
  return out;
});

const filters = computed<SegmentOption<Filter>[]>(() => {
  const list: SegmentOption<Filter>[] = [{ value: "all", label: t("davomat.users.filter.all"), count: counts.value.all }];
  for (const kind of ["admin", "manager", "viewer"] as const) if (counts.value[kind]) list.push({ value: kind, label: t(`davomat.users.filter.${kind}`), count: counts.value[kind] });
  if (counts.value.inactive) list.push({ value: "inactive", label: t("davomat.users.filter.inactive"), count: counts.value.inactive });
  return list;
});

// A filter whose last person left it (reactivated, deleted) goes back to everyone.
watch(filters, (list) => {
  if (!list.some((option) => option.value === filter.value)) filter.value = "all";
});

const shown = computed(() => {
  const needle = normalize(query.value.trim());
  return all.value.filter((user) => {
    if (filter.value === "inactive" ? user.is_active : !user.is_active) return false;
    if (filter.value !== "all" && filter.value !== "inactive" && kindOf(user) !== filter.value) return false;
    if (!needle) return true;
    return normalize(`${fullName(user)} ${user.username}`).includes(needle);
  });
});

const branchNames = computed(() => new Map((company.current?.branches ?? []).map((b) => [b.id, b.name])));
function locations(user: User): string {
  const kind = kindOf(user);
  if (kind === "owner" || kind === "admin") return t("davomat.users.allBranches");
  if (user.branch_ids.length === 0) return t("davomat.users.noBranches");
  const names = user.branch_ids.map((id) => branchNames.value.get(id)).filter((name): name is string => !!name);
  if (names.length <= 2) return names.join(", ");
  return `${names.slice(0, 2).join(", ")} ${t("davomat.users.moreBranches", { n: names.length - 2 })}`;
}

// ─── Dialogs ──────────────────────────────────────────────────────────────────

const editing = ref<User | null>(null);
const userOpen = ref(false);
const passwordFor = ref<User | null>(null);
const passwordOpen = ref(false);
const telegramFor = ref<User | null>(null);
const telegramOpen = ref(false);

function openCreate(): void {
  editing.value = null;
  userOpen.value = true;
}
function openEdit(user: User): void {
  editing.value = user;
  userOpen.value = true;
}
function onSaved(user: User, created: boolean): void {
  refresh();
  if (!created) toast.success(t("davomat.users.saved", { name: fullName(user) }));
}

/** Switches someone off or back on; the server's refusal (the last owner who can sign in) is its toast. */
async function setActive(user: User, active: boolean): Promise<void> {
  const cid = company.currentId ?? 0;
  try {
    if (!active) {
      const answer = await confirm({
        title: t("davomat.users.deactivate.title", { name: fullName(user) }),
        message: t("davomat.users.deactivate.body"),
        confirmLabel: t("davomat.users.deactivate.confirm"),
        tone: "danger",
        icon: UserX,
      });
      if (!answer) return;
      await deactivateUser(cid, user.id);
      toast.success(t("davomat.users.deactivate.done", { name: fullName(user) }));
    } else {
      await activateUser(cid, user.id);
      toast.success(t("davomat.users.reactivated", { name: fullName(user) }));
    }
  } catch {
    // Shown already: the HTTP layer toasts a refused write.
  } finally {
    refresh();
  }
}

function menu(user: User): MenuEntry[] {
  // Only an owner switches off another owner (the server keeps one who can sign in).
  const protectedOwner = kindOf(user) === "owner" && !company.current?.is_owner;
  const entries: MenuEntry[] = [
    { label: t("common.edit"), icon: Pencil, onSelect: () => openEdit(user) },
    {
      label: t("davomat.users.actions.password"),
      icon: KeyRound,
      onSelect: () => {
        passwordFor.value = user;
        passwordOpen.value = true;
      },
    },
    {
      label: user.telegram_linked ? t("davomat.users.actions.telegramLinked") : t("davomat.users.actions.telegram"),
      icon: Send,
      onSelect: () => {
        telegramFor.value = user;
        telegramOpen.value = true;
      },
    },
  ];
  // Nobody switches themselves off.
  if (!protectedOwner && !isSelf(user)) {
    entries.push({ type: "separator" });
    entries.push(
      user.is_active
        ? { label: t("davomat.users.actions.deactivate"), icon: UserX, danger: true, onSelect: () => void setActive(user, false) }
        : { label: t("davomat.users.actions.reactivate"), icon: Power, onSelect: () => void setActive(user, true) },
    );
  }
  return entries;
}

const telegramCreate = () => userTelegramLink(company.currentId ?? 0, telegramFor.value!.id);
async function telegramUnlink(): Promise<void> {
  const user = telegramFor.value;
  if (!user) return;
  await userTelegramUnlink(company.currentId ?? 0, user.id);
  toast.success(t("davomat.users.telegramUnlinked", { name: fullName(user) }));
  telegramOpen.value = false;
  refresh();
}

// ─── What each role may do ────────────────────────────────────────────────────

const ROLE_ICONS: Record<KnownKind, Component> = { owner: Crown, admin: ShieldCheck, manager: UserCog, viewer: Eye, other: KeyRound };
const roleGuide = computed(() =>
  (["owner", "admin", "manager", "viewer"] as const).map((kind) => ({
    kind,
    icon: ROLE_ICONS[kind],
    name: roles.data.value?.find((role) => (role.kind ?? (role.is_owner ? "owner" : "")) === kind)?.name ?? t(`davomat.users.role.${kind}.name`),
    can: [1, 2, 3].map((n) => t(`davomat.users.role.${kind}.can${n}`)),
  })),
);
const toneBg: Record<ReturnType<typeof roleTone>, string> = {
  primary: "bg-accent-soft text-accent-fg",
  info: "bg-info-soft text-info",
  success: "bg-success-soft text-success",
  neutral: "bg-surface-2 text-muted",
};
</script>

<template>
  <div class="flex flex-col gap-6" data-users>
    <!-- Toolbar -->
    <div class="flex flex-wrap items-center gap-2">
      <TextInput v-model="query" :icon="Search" :placeholder="t('davomat.users.search')" clearable class="min-w-[200px] flex-1 sm:max-w-[300px]" data-search />
      <span class="hidden flex-1 sm:block" />
      <UiButton variant="primary" :icon="UserPlus" data-add @click="openCreate">{{ t("davomat.users.add") }}</UiButton>
    </div>
    <SegmentedControl v-if="filters.length > 1" v-model="filter" :options="filters" size="sm" :aria-label="t('davomat.users.filter.label')" />

    <ErrorState v-if="users.isError.value" :error="users.error.value" :retry="() => users.refetch()" :retrying="users.isFetching.value" />

    <div v-else-if="skeleton || !users.data.value" class="ui-card divide-y divide-line" aria-busy="true">
      <div v-for="n in 4" :key="n" class="flex items-center gap-3 px-4 py-3.5">
        <SkeletonBlock circle width="38px" height="38px" />
        <div class="flex flex-1 flex-col gap-1.5">
          <SkeletonBlock width="40%" />
          <SkeletonBlock width="24%" height="12px" />
        </div>
        <SkeletonBlock width="88px" height="22px" radius="999px" />
      </div>
    </div>

    <div v-else class="ui-card overflow-hidden">
      <!-- Column names on wide screens -->
      <div class="hidden items-center gap-3 border-b border-line bg-surface-2/50 px-4 py-2 text-xs font-medium text-muted lg:flex" aria-hidden="true">
        <span class="w-[38px] shrink-0" />
        <span class="min-w-0 flex-1">{{ t("davomat.users.col.name") }}</span>
        <span class="w-[132px]">{{ t("davomat.users.col.role") }}</span>
        <span class="w-[180px]">{{ t("davomat.users.col.branches") }}</span>
        <span class="w-[120px] text-right">{{ t("davomat.users.col.lastLogin") }}</span>
        <span class="w-[64px]" />
      </div>
      <TransitionGroup tag="ul" name="list" class="divide-y divide-line" role="list">
        <li
          v-for="user in shown"
          :key="user.id"
          :class="['group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-highlight', !user.is_active && 'opacity-60']"
          :data-user="user.username"
        >
          <UserAvatar :name="fullName(user)" :size="38" />
          <div class="min-w-0 flex-1">
            <div class="flex min-w-0 items-center gap-2">
              <button type="button" class="min-w-0 truncate text-left text-base font-semibold text-fg hover:underline" @click="openEdit(user)">{{ fullName(user) }}</button>
              <UiBadge v-if="isSelf(user)" tone="primary">{{ t("davomat.users.you") }}</UiBadge>
              <UiBadge v-if="!user.is_active" tone="neutral">{{ t("davomat.users.inactive") }}</UiBadge>
            </div>
            <div class="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
              <span class="truncate font-mono text-[0.92em]">{{ user.username }}</span>
              <!-- On narrow screens the role and the locations follow the username. -->
              <StatusPill class="lg:hidden" size="sm" :tone="roleTone(kindOf(user))" :label="roleName(user)" :dot="false" />
              <span class="truncate lg:hidden">{{ locations(user) }}</span>
            </div>
          </div>
          <span class="hidden w-[132px] lg:block">
            <StatusPill :tone="roleTone(kindOf(user))" :label="roleName(user)" :dot="false" />
          </span>
          <span class="hidden w-[180px] truncate text-sm text-muted lg:block" :title="locations(user)">{{ locations(user) }}</span>
          <span class="hidden w-[120px] text-right text-sm text-muted md:block">
            <RelativeTime v-if="user.last_login" :value="user.last_login" />
            <span v-else class="text-subtle">{{ t("davomat.users.never") }}</span>
          </span>
          <UiTooltip :content="user.telegram_linked ? t('davomat.users.telegramYes') : t('davomat.users.telegramNo')">
            <span :class="['grid size-7 shrink-0 place-items-center rounded-full', user.telegram_linked ? 'bg-info-soft text-info' : 'text-subtle']" :data-telegram="user.telegram_linked">
              <Send :size="14" />
              <span class="sr-only">{{ user.telegram_linked ? t("davomat.users.telegramYes") : t("davomat.users.telegramNo") }}</span>
            </span>
          </UiTooltip>
          <DropdownMenu :items="menu(user)" width="240px">
            <template #trigger>
              <IconButton :icon="Ellipsis" :label="t('davomat.users.actions.label', { name: fullName(user) })" variant="ghost" size="sm" />
            </template>
          </DropdownMenu>
        </li>
      </TransitionGroup>
      <p v-if="!shown.length" class="px-4 py-10 text-center text-sm text-muted">{{ t("davomat.users.noMatch") }}</p>
    </div>

    <!-- Nobody else signs in yet: who to add -->
    <button
      v-if="users.data.value && all.length <= 1"
      type="button"
      class="pressable group flex items-center gap-4 rounded-card border border-dashed border-line-strong p-5 text-left hover:border-primary hover:bg-accent-soft/40"
      data-invite
      @click="openCreate"
    >
      <span class="grid size-11 shrink-0 place-items-center rounded-full bg-accent-soft text-accent-fg transition-transform duration-200 group-hover:scale-105"><UserPlus :size="20" /></span>
      <span class="min-w-0 flex-1">
        <span class="block text-base font-semibold text-fg">{{ t("davomat.users.empty.title") }}</span>
        <span class="mt-0.5 block text-sm text-muted">{{ t("davomat.users.empty.body") }}</span>
      </span>
    </button>

    <!-- What each role may do -->
    <section aria-labelledby="davomat-roles-title">
      <h3 id="davomat-roles-title" class="text-md font-semibold text-fg">{{ t("davomat.users.guide.title") }}</h3>
      <p class="mt-0.5 text-sm text-muted">{{ t("davomat.users.guide.hint") }}</p>
      <div class="mt-3 grid gap-3 sm:grid-cols-2 2xl:grid-cols-4">
        <article v-for="role in roleGuide" :key="role.kind" class="ui-card flex flex-col gap-3 p-4" :data-role-guide="role.kind">
          <header class="flex items-center gap-2.5">
            <span :class="['grid size-8 place-items-center rounded-[9px]', toneBg[roleTone(role.kind)]]"><component :is="role.icon" :size="16" /></span>
            <span class="text-base font-semibold text-fg">{{ role.name }}</span>
          </header>
          <ul class="flex flex-col gap-1.5 text-sm text-muted">
            <li v-for="line in role.can" :key="line" class="flex gap-2">
              <span class="mt-[7px] size-1 shrink-0 rounded-full bg-[var(--c-border-strong)]" aria-hidden="true" />
              <span>{{ line }}</span>
            </li>
          </ul>
        </article>
      </div>
    </section>

    <UserDialog v-model:open="userOpen" :user="editing" :roles="roles.data.value ?? []" @saved="onSaved" />
    <PasswordDialog v-model:open="passwordOpen" :user="passwordFor" @saved="toast.success(t('davomat.users.password.saved'))" />
    <TelegramLinkDialog
      v-if="telegramFor"
      :key="telegramFor.id"
      v-model:open="telegramOpen"
      :title="t('davomat.users.telegramTitle', { name: fullName(telegramFor) })"
      :description="telegramFor.telegram_linked ? undefined : t('davomat.users.telegramHint')"
      :linked="telegramFor.telegram_linked"
      :create="telegramCreate"
      :unlink="telegramUnlink"
    />
  </div>
</template>
