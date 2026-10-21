<script setup lang="ts">
/**
 * The console frame (plan §6.5): sidebar (or phone tab bar), top bar, the routed page in a panel,
 * and the shell's overlays (palette, inbox, shortcuts, new company, AI panel slot). It runs the one
 * pulse poller, the global shortcuts and the document title.
 */
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import { useTitle } from "@vueuse/core";
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterView, useRoute, useRouter } from "vue-router";

import { keys } from "@/api/keys";
import { shellApi } from "@/api/shell";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import { menuPanel, preloadWhenIdle } from "@/components/lazyPart";
import { toast } from "@/components/useToast";
import { canAccessRoute, visibleModules } from "@/core/access";
import { hasExtension } from "@/core/extensions";
import { registerHotkey } from "@/core/hotkeys";
import { findModule, modules } from "@/core/modules";
import { buildNav } from "@/core/nav";
import { PULSE_INBOX_UNREAD, PULSE_QUEUE, PULSE_SAVED_VIEWS, keyMatches, pulse, usePulseCount, usePulsePolling } from "@/core/pulse";
import { ensureAllModuleMessages } from "@/i18n";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { pageTitleFor } from "@/lib/usePageTitle";
import { applyQueryPatch } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";
import { usePaletteStore } from "@/stores/palette";
import { useSessionStore } from "@/stores/session";
import { useUiStore } from "@/stores/ui";

import { companyMenu } from "./companySwitcher";
import ForbiddenPage from "./ForbiddenPage.vue";
import MobileTabBar from "./MobileTabBar.vue";
import SideNav from "./SideNav.vue";
import { bufferKeysUntilPaletteMounts, loadPalette, prefetchPaletteOnModifier } from "./paletteLoader";
import { resolveStartParam, telegram } from "./TelegramBridge";
import TopBar from "./TopBar.vue";

const CommandPalette = defineAsyncComponent(loadPalette);
const InboxDrawer = defineAsyncComponent(() => import("./InboxDrawer.vue"));
const ShortcutsDialog = defineAsyncComponent(() => import("./ShortcutsDialog.vue"));
const MoreSheet = defineAsyncComponent(() => import("./MoreSheet.vue"));
const UiDialog = defineAsyncComponent(() => import("@/components/UiDialog.vue"));

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const client = useQueryClient();
const session = useSessionStore();
const company = useCompanyStore();
const ui = useUiStore();
const palette = usePaletteStore();
const { isPhone, isTablet, isDesktop } = useBreakpoints();

const companyless = computed(() => route.matched.some((record) => record.meta.companyless));
const fullLayout = computed(() => route.matched.some((record) => record.meta.layout === "full"));
const showSidebar = computed(() => !isPhone.value && !companyless.value);
const rail = computed(() => isTablet.value || ui.sidebarCollapsed);

// Every visible module's titles are needed by the sidebar and the palette.
const messagesReady = ref(false);
const visible = computed(() => visibleModules(modules, company.current));
watch(
  visible,
  async (list) => {
    await ensureAllModuleMessages(list);
    messagesReady.value = true;
  },
  { immediate: true },
);

const nav = computed(() => buildNav(modules, company.current, pulse.value));
const forbidden = computed(() => !companyless.value && !!company.current && !canAccessRoute(route, company.current));

// Live data. When the inbox or the queue moves, the drawer's lists and the unread count refetch
// (never the pulse query itself, which shares the "shell" prefix).
const pulseQuery = usePulsePolling(
  computed(() => (companyless.value ? null : company.currentId)),
  (changed) => {
    const id = company.currentId;
    if (id === null) return;
    if (changed.some((key) => keyMatches(PULSE_INBOX_UNREAD, key))) {
      void client.invalidateQueries({ queryKey: [id, "shell", "inbox"] });
      void client.invalidateQueries({ queryKey: keys.unread(id) });
    }
    if (changed.some((key) => keyMatches(PULSE_QUEUE, key))) void client.invalidateQueries({ queryKey: [id, "shell", "queue"] });
    if (changed.includes(PULSE_SAVED_VIEWS)) void client.invalidateQueries({ queryKey: [id, "shell", "saved-views"] });
  },
);
const queueCount = usePulseCount(PULSE_QUEUE);
const unreadCount = usePulseCount(PULSE_INBOX_UNREAD);
const inboxCount = computed(() => queueCount.value + unreadCount.value);

// How many unread notifications are critical (`inbox/unread-count/`): the favicon badge, "(n)" in
// the title and the arrival toast.
const unread = useQuery({
  queryKey: computed(() => keys.unread(company.currentId ?? 0)),
  queryFn: ({ signal }) => shellApi.unreadCount(company.currentId ?? 0, signal),
  enabled: computed(() => !companyless.value && company.currentId !== null),
  staleTime: 60_000,
});
const criticalCount = computed(() => unread.data.value?.critical ?? 0);

const aiAvailable = computed(
  () => !!company.current && company.can("ai.use") && company.enabled("ai") && hasExtension("shell.panel", company.current),
);

function openInbox(tab?: "needs" | "notifications"): void {
  const next = tab ?? (queueCount.value > 0 || unreadCount.value === 0 ? "needs" : "notifications");
  void router.push({ path: route.path, query: applyQueryPatch(route.query, { inbox: next }), hash: route.hash });
}

async function signOut(): Promise<void> {
  await session.logout();
  client.clear();
  // Inside Telegram there is no login page: initData was the session, so the way back is the bot.
  await router.replace(telegram().inside ? { name: "session-ended" } : "/login");
}

// Critical arrivals: a soft toast, a badge on the favicon and "(n)" in the title. The first count
// of each company only sets the baseline, so opening the console never greets you with a toast.
const criticalSeen = new Map<number, number>();
watch(
  () => [company.currentId, unread.data.value] as const,
  ([id, data]) => {
    if (id === null || !data) return;
    const previous = criticalSeen.get(id);
    criticalSeen.set(id, data.critical);
    if (previous !== undefined && data.critical > previous) {
      toast.warning(t("shell.inbox.urgent"), {
        description: t("shell.inbox.unreadCount", { n: data.count }),
        action: { label: t("common.open"), onClick: () => openInbox("notifications") },
      });
    }
  },
);

const FAVICON = "/dashboard/favicon.svg";
const BADGED =
  "data:image/svg+xml," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 50"><circle cx="21" cy="21" r="21" fill="#c67139"/><path d="M12.25 21.9 18.4 28 29.6 15.8" fill="none" stroke="#f5ead8" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="39" cy="11" r="11" fill="#d93a26" stroke="#fff" stroke-width="3"/></svg>',
  );
watch(
  criticalCount,
  (count) => {
    const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (link) link.href = count > 0 ? BADGED : FAVICON;
  },
  { immediate: true },
);

const pageTitle = computed(() => {
  const named = pageTitleFor(route);
  if (named) return named;
  const key = [...route.matched].reverse().find((record) => record.meta.title)?.meta.title;
  if (key) return t(key);
  const module = findModule(route.matched.map((record) => record.meta.module).find(Boolean));
  return module ? t(module.title) : "";
});
useTitle(
  computed(() => {
    const parts = [pageTitle.value, companyless.value ? "" : company.current?.name, t("shell.brand")].filter(Boolean);
    const prefix = criticalCount.value > 0 ? `(${criticalCount.value}) ` : "";
    return prefix + parts.join(" · ");
  }),
);

// Overlays mount on first use, so their code loads only when needed.
const paletteMounted = ref(false);
const inboxMounted = ref(false);
const shortcutsMounted = ref(false);
const moreMounted = ref(false);
const newCompanyMounted = ref(false);
watch(() => palette.open, (open) => open && (paletteMounted.value = true), { immediate: true });
watch(() => route.query.inbox, (value) => value !== undefined && (inboxMounted.value = true), { immediate: true });
watch(() => ui.shortcutsOpen, (open) => open && (shortcutsMounted.value = true), { immediate: true });
watch(() => ui.moreOpen, (open) => open && (moreMounted.value = true), { immediate: true });
watch(() => ui.newCompanyOpen, (open) => open && (newCompanyMounted.value = true), { immediate: true });
watch(() => route.fullPath, () => (ui.moreOpen = false));

// Global shortcuts.
const removers: Array<() => void> = [];
removers.push(
  registerHotkey("mod+k", () => palette.toggle(), { allowInInputs: true, allowInDialogs: true }),
  registerHotkey("/", () => palette.show()),
  registerHotkey("mod+j", () => aiAvailable.value && ui.askAi(), { allowInInputs: true, allowInDialogs: true, enabled: () => aiAvailable.value }),
  registerHotkey("?", () => (ui.shortcutsOpen = true)),
  registerHotkey("[", () => ui.toggleSidebar(), { enabled: () => isDesktop.value && !companyless.value }),
  prefetchPaletteOnModifier(),
  bufferKeysUntilPaletteMounts(
    () => palette.open,
    (key) => (palette.initialQuery += key),
  ),
);
let jumpRemovers: Array<() => void> = [];
watch(
  nav,
  (groups) => {
    jumpRemovers.forEach((remove) => remove());
    jumpRemovers = groups
      .flatMap((group) => group.modules)
      .filter((module) => module.hotkey)
      .map((module) => registerHotkey(`g ${module.hotkey}`, () => void router.push(module.path)));
  },
  { immediate: true },
);
onBeforeUnmount(() => [...removers, ...jumpRemovers].forEach((remove) => remove()));

// The desktop panel scrolls on its own: top on a new page, back where you were on Back/Forward.
const mainEl = ref<HTMLElement | null>(null);
const scrollMemory = new Map<string, number>();
let fromHistory = false;
const onPopState = () => (fromHistory = true);
const stopBefore = router.beforeEach((_to, from) => {
  if (mainEl.value) scrollMemory.set(from.fullPath, mainEl.value.scrollTop);
});
watch(
  () => route.path,
  async () => {
    await nextTick();
    const saved = fromHistory ? scrollMemory.get(route.fullPath) : undefined;
    fromHistory = false;
    if (mainEl.value) mainEl.value.scrollTop = saved ?? 0;
  },
);

onMounted(() => {
  // The menus (reka-ui and its positioning) are not in the first load: fetched now that the page
  // has painted, so the first menu opens at once (components/lazyPart.ts).
  removers.push(preloadWhenIdle([menuPanel, companyMenu]));
  window.addEventListener("popstate", onPopState);
  // Opened from the owner bot with a `startapp` parameter: go there once.
  const tg = telegram();
  if (tg.startParam && company.currentId !== null) {
    const target = resolveStartParam(tg.startParam, company.currentId, modules);
    tg.startParam = null;
    if (target) void router.replace(target);
  }
});
onBeforeUnmount(() => {
  window.removeEventListener("popstate", onPopState);
  stopBefore();
});

const closeNewCompany = () => (ui.newCompanyOpen = false);
</script>

<template>
  <div class="min-h-dvh bg-[var(--c-nav)] md:flex">
    <a
      href="#content"
      class="fixed left-3 top-3 z-[100] -translate-y-20 rounded-button bg-fg px-3 py-2 text-sm font-semibold text-canvas transition-transform focus:translate-y-0"
      >{{ t("shell.skip") }}</a
    >

    <SideNav
      v-if="showSidebar"
      :groups="nav"
      :rail="rail"
      :ready="messagesReady"
      :can-collapse="isDesktop"
      @toggle="ui.toggleSidebar()"
      @retry="pulseQuery.refetch()"
    />

    <div :class="['flex min-w-0 flex-1 flex-col', !isPhone && 'h-dvh py-2 pr-2', !isPhone && !showSidebar && 'pl-2']">
      <div
        :class="[
          'flex min-h-0 flex-1 flex-col',
          isPhone ? 'bg-canvas' : 'overflow-hidden rounded-[14px] border border-line bg-surface shadow-xs',
        ]"
      >
        <TopBar
          :phone="isPhone"
          :companyless="companyless"
          :ai-available="aiAvailable"
          :inbox-count="inboxCount"
          :inbox-critical="criticalCount > 0"
          @open-inbox="openInbox()"
          @sign-out="signOut"
          @retry="pulseQuery.refetch()"
        />
        <main
          id="content"
          ref="mainEl"
          tabindex="-1"
          :class="[
            'relative min-h-0 flex-1 outline-none',
            !isPhone && 'overflow-y-auto overscroll-contain',
            isPhone && !companyless && 'pb-[calc(var(--tabbar-h)+var(--safe-bottom))]',
          ]"
        >
          <div :class="fullLayout ? 'h-full' : 'mx-auto w-full max-w-[1440px] px-4 pb-10 pt-5 md:px-8 md:pt-7'">
            <RouterView v-slot="{ Component, route: current }">
              <Transition name="route">
                <ForbiddenPage v-if="forbidden" key="forbidden" />
                <component :is="Component" v-else :key="current.path" />
              </Transition>
            </RouterView>
          </div>
        </main>
      </div>
    </div>

    <MobileTabBar v-if="isPhone && !companyless" :groups="nav" :more-open="ui.moreOpen" @more="ui.moreOpen = !ui.moreOpen" />
    <MoreSheet v-if="moreMounted" v-model:open="ui.moreOpen" :groups="nav" @sign-out="signOut" />

    <CommandPalette v-if="paletteMounted" :groups="nav" :ai-available="aiAvailable" @open-inbox="openInbox()" @sign-out="signOut" />
    <InboxDrawer v-if="inboxMounted && !companyless" />
    <ShortcutsDialog v-if="shortcutsMounted" v-model:open="ui.shortcutsOpen" :groups="nav" :ai-available="aiAvailable" />

    <UiDialog v-if="newCompanyMounted" v-model:open="ui.newCompanyOpen" :title="t('shell.company.new')" :description="t('shell.company.newHint')">
      <ExtensionSlot name="shell.company.create" :context="{ close: closeNewCompany }" />
    </UiDialog>

    <ExtensionSlot v-if="!companyless" name="shell.panel" as="none" :context="{ route: route.fullPath }" />
  </div>
</template>
