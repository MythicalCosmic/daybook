<script setup lang="ts">
/**
 * The top bar (plan §6.1): breadcrumb, "Search or jump… ⌘K", Ask AI (only when the AI is
 * available), the inbox bell, theme, language and the account menu. On phones: the company
 * switcher, search, bell and account.
 */
import { Bell, Keyboard, Languages, LogOut, Monitor, Moon, MonitorSmartphone, Rows3, Search, Sparkles, Sun } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { changeLanguage } from "@/app/providers";
import { switchTheme, toggleTheme } from "@/app/theme";
import Breadcrumbs, { type Crumb } from "@/components/Breadcrumbs.vue";
import ConnectionPill from "@/components/ConnectionPill.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import IconButton from "@/components/IconButton.vue";
import KbdKey from "@/components/KbdKey.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { LANGUAGES } from "@/api/types";
import { findModule } from "@/core/modules";
import { moduleNavItems } from "@/core/nav";
import { currentLanguage } from "@/i18n";
import { pageTitleFor } from "@/lib/usePageTitle";
import { usePaletteStore } from "@/stores/palette";
import { useSessionStore } from "@/stores/session";
import { useUiStore, type Density, type ThemeMode } from "@/stores/ui";

import CompanySwitcher from "./CompanySwitcher.vue";

const props = defineProps<{
  phone: boolean;
  companyless: boolean;
  aiAvailable: boolean;
  inboxCount: number;
  inboxCritical: boolean;
}>();
const emit = defineEmits<{ openInbox: []; signOut: []; retry: [] }>();

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const ui = useUiStore();
const palette = usePaletteStore();

const crumbs = computed<Crumb[]>(() => {
  const module = findModule(route.matched.map((r) => r.meta.module).find(Boolean));
  if (!module) {
    const title = [...route.matched].reverse().find((r) => r.meta.title)?.meta.title;
    return title ? [{ label: t(title) }] : [];
  }
  const companyId = route.params.companyId;
  const first = moduleNavItems(module)[0];
  const base = `/c/${Array.isArray(companyId) ? companyId[0] : companyId}`;
  const list: Crumb[] = [{ label: t(`shell.group.${module.group}`) }];
  const moduleTitle = t(module.title);
  list.push({ label: moduleTitle, to: first ? `${base}/${first.to}`.replace(/\/$/, "") : base });
  const pageTitle = [...route.matched].reverse().find((r) => r.meta.title)?.meta.title;
  // A page showing one record names it (usePageTitle): "Projects › Yunusobod storage room".
  const named = pageTitleFor(route);
  if (named) list.push({ label: named });
  else if (pageTitle && t(pageTitle) !== moduleTitle) list.push({ label: t(pageTitle) });
  return module.group === "overview" ? list.slice(1) : list;
});

const user = computed(() => session.me?.user ?? null);
const hasSessionsPage = computed(() => {
  const id = route.params.companyId;
  if (!id) return false;
  return router.resolve(`/c/${Array.isArray(id) ? id[0] : id}/settings/sessions`).name !== "company-not-found";
});

const languageNames = computed(() => Object.fromEntries(LANGUAGES.map((l) => [l, t(`shell.language.${l}`)])));

const accountMenu = computed<MenuEntry[]>(() => {
  const entries: MenuEntry[] = [];
  if (hasSessionsPage.value) {
    const id = route.params.companyId;
    entries.push({
      label: t("shell.user.sessions"),
      icon: MonitorSmartphone,
      onSelect: () => void router.push(`/c/${Array.isArray(id) ? id[0] : id}/settings/sessions`),
    });
  }
  entries.push(
    { label: t("shell.user.shortcuts"), icon: Keyboard, shortcut: "?", onSelect: () => (ui.shortcutsOpen = true) },
    {
      type: "sub",
      label: t("shell.user.appearance"),
      icon: ui.theme === "dark" ? Moon : Sun,
      hint: t(`shell.theme.${ui.themeMode}`),
      items: [
        {
          type: "radio",
          value: ui.themeMode,
          options: [
            { value: "light", label: t("shell.theme.light"), icon: Sun },
            { value: "dark", label: t("shell.theme.dark"), icon: Moon },
            { value: "system", label: t("shell.theme.system"), icon: Monitor },
          ],
          onChange: (value) => switchTheme(value as ThemeMode),
        },
      ],
    },
    {
      type: "sub",
      label: t("shell.density.label"),
      icon: Rows3,
      hint: t(`shell.density.${ui.density}`),
      items: [
        {
          type: "radio",
          value: ui.density,
          options: [
            { value: "comfortable", label: t("shell.density.comfortable") },
            { value: "compact", label: t("shell.density.compact") },
          ],
          onChange: (value) => ui.setDensity(value as Density),
        },
      ],
    },
  );
  if (props.phone) {
    entries.push({
      type: "sub",
      label: t("shell.topbar.language"),
      icon: Languages,
      hint: languageNames.value[currentLanguage()],
      items: [{ type: "radio", value: locale.value, options: LANGUAGES.map((l) => ({ value: l, label: languageNames.value[l]! })), onChange: changeLanguage }],
    });
  }
  entries.push({ type: "separator" }, { label: t("shell.user.signOut"), icon: LogOut, danger: true, onSelect: () => emit("signOut") });
  return entries;
});

const languageMenu = computed<MenuEntry[]>(() => [
  { type: "radio", value: locale.value, options: LANGUAGES.map((l) => ({ value: l, label: languageNames.value[l]! })), onChange: changeLanguage },
]);
</script>

<template>
  <header
    class="flex h-[var(--topbar-h)] shrink-0 items-center gap-2 border-b border-line bg-surface/85 px-3 backdrop-blur-md md:px-4"
    :class="phone && 'sticky top-0 z-30 pt-[var(--safe-top)] h-[calc(var(--topbar-h)+var(--safe-top))]'"
  >
    <CompanySwitcher v-if="phone || companyless" variant="compact" />

    <Breadcrumbs v-if="!phone && !companyless && crumbs.length" :items="crumbs" />

    <span class="min-w-0 flex-1" />

    <button
      v-if="!phone"
      type="button"
      class="pressable group hidden h-8 w-[280px] items-center gap-2 rounded-button border border-line bg-canvas/70 pl-2.5 pr-1.5 text-left text-base text-muted shadow-xs hover:border-line-strong hover:bg-surface hover:text-fg lg:flex"
      @click="palette.show()"
    >
      <Search :size="15" class="shrink-0" aria-hidden="true" />
      <span class="min-w-0 flex-1 truncate">{{ t("shell.topbar.search") }}</span>
      <KbdKey keys="mod+k" />
    </button>
    <IconButton v-if="!phone" class="lg:hidden" :icon="Search" :label="t('shell.topbar.searchShort')" shortcut="mod+k" @click="palette.show()" />
    <IconButton v-else :icon="Search" :label="t('shell.topbar.searchShort')" @click="palette.show()" />

    <UiTooltip v-if="aiAvailable && !phone" :content="t('shell.topbar.askAi')" shortcut="mod+j" side="bottom">
      <button
        type="button"
        class="pressable flex h-8 items-center gap-1.5 rounded-button px-2.5 text-sm font-semibold text-accent-fg hover:bg-accent-soft"
        @click="ui.askAi()"
      >
        <Sparkles :size="15" aria-hidden="true" />
        <span class="hidden xl:inline">{{ t("shell.topbar.askAi") }}</span>
      </button>
    </UiTooltip>

    <ExtensionSlot v-if="!companyless" name="shell.topbar.end" class="flex items-center gap-1" />

    <ConnectionPill v-if="phone" compact @retry="emit('retry')" />

    <span v-if="!phone" class="mx-1 h-5 w-px bg-line" aria-hidden="true" />

    <IconButton
      v-if="!companyless"
      :icon="Bell"
      :label="t('shell.topbar.inbox')"
      :badge="inboxCount"
      :badge-tone="inboxCritical ? 'danger' : 'primary'"
      @click="emit('openInbox')"
    />

    <template v-if="!phone">
      <IconButton
        :icon="ui.theme === 'dark' ? Sun : Moon"
        :label="ui.theme === 'dark' ? t('shell.theme.toLight') : t('shell.theme.toDark')"
        @click="(event: MouseEvent) => toggleTheme(event)"
      />
      <DropdownMenu :items="languageMenu" width="180px">
        <template #trigger>
          <button
            type="button"
            class="pressable flex h-8 items-center gap-1.5 rounded-button px-2 text-sm font-semibold uppercase text-muted hover:bg-highlight hover:text-fg data-[state=open]:bg-highlight"
            :aria-label="t('shell.topbar.language')"
          >
            <Languages :size="16" aria-hidden="true" />
            {{ locale }}
          </button>
        </template>
      </DropdownMenu>
    </template>

    <DropdownMenu v-if="user" :items="accountMenu" width="260px">
      <template #trigger>
        <button
          type="button"
          class="pressable ml-0.5 grid size-8 place-items-center rounded-full outline-offset-1 hover:ring-4 hover:ring-[var(--c-highlight)] data-[state=open]:ring-4 data-[state=open]:ring-[var(--c-highlight)]"
          :aria-label="t('shell.topbar.account')"
        >
          <UserAvatar :name="user.full_name" :src="user.photo_url" :size="28" />
        </button>
      </template>
      <template #header>
        <div class="flex items-center gap-3 px-2 pb-2.5 pt-2">
          <UserAvatar :name="user.full_name" :src="user.photo_url" :size="36" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-base font-semibold text-fg">{{ user.full_name }}</p>
            <p v-if="user.username || user.telegram_id" class="truncate text-xs text-muted">{{ user.username ? `@${user.username}` : `#${user.telegram_id}` }}</p>
          </div>
        </div>
        <div class="-mx-1 mb-1 h-px bg-line" />
      </template>
    </DropdownMenu>
  </header>
</template>
