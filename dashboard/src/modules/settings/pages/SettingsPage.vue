<script setup lang="ts">
/**
 * Settings (plan §6.2): the panel list on the left, the chosen panel on the right
 * (`settings/:panel`). Panels come from every module's `settings` in the registry, filtered by
 * permission and module switch, and read as one settings app:
 *
 * - the list is grouped like the sidebar (Company, People, Work, Money, Communication…), with the
 *   person's own Notifications and Sessions last under "Your account";
 * - every row has an icon, a short name and (on phones) one line about it, wherever the panel
 *   comes from: this module's dictionary may name another module's panel (`settings.panel.<id>`,
 *   `….hint`, `….description`), else the panel's own title is used;
 * - every module panel gets the same header as this module's own panels (title and one sentence);
 * - Roles and Positions live in People, but owners look for them here, so the People group links
 *   to them.
 *
 * Other modules' titles live in their own dictionaries; their rows wait as skeletons until those
 * load, so a raw key never flashes. On a phone the list is a page of its own and a panel opens over
 * it with a back link.
 */
import {
  ArrowUpRight,
  Bell,
  BriefcaseBusiness,
  Building2,
  ChevronLeft,
  ChevronRight,
  CreditCard,
  Landmark,
  LayoutGrid,
  MapPin,
  MonitorSmartphone,
  Settings2,
  ShieldCheck,
  Store,
  UserPlus,
  Wallet,
  type LucideIcon,
} from "@lucide/vue";
import { computed, onMounted, ref, watch, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { allowed, isModuleVisible } from "@/core/access";
import { findModule, modules, type SettingsPanel } from "@/core/modules";
import { ensureModuleMessages } from "@/i18n";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useCompanyStore } from "@/stores/company";

import { groupPanels, type NavSection, type PanelEntry } from "../nav";

const { t, te } = useI18n();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const { isPhone } = useBreakpoints();

/**
 * Icons for panels whose registry entry has none (this module's own, kept out of the first bundle,
 * and a few module panels), matching the icons those modules use on their own pages.
 */
const ICONS: Record<string, LucideIcon> = {
  company: Building2,
  features: LayoutGrid,
  branches: MapPin,
  invite: UserPlus,
  notifications: Bell,
  sessions: MonitorSmartphone,
  sales: Store,
  registers: Wallet,
  "payment-methods": CreditCard,
  finance: Landmark,
  roles: ShieldCheck,
  positions: BriefcaseBusiness,
};

// Other modules' panel titles live in their own dictionaries: wait for them before naming rows.
const messagesReady = ref(false);
onMounted(() => {
  const pending = modules.filter((module) => module.settings?.length && module.id !== "settings").map((module) => ensureModuleMessages(module));
  void Promise.allSettled(pending).then(() => (messagesReady.value = true));
});

const entries = computed<PanelEntry[]>(() => {
  const list: PanelEntry[] = [];
  for (const module of modules) {
    if (!module.settings?.length || !isModuleVisible(module, company.current)) continue;
    for (const panel of module.settings as SettingsPanel[]) {
      if (!allowed(company.current, panel)) continue;
      list.push({ ...panel, icon: panel.icon ?? ICONS[panel.id], moduleId: module.id, moduleGroup: module.group, moduleOrder: module.order, own: module.id === "settings" });
    }
  }
  return list;
});

/** Roles and Positions are People pages; they show in Settings as links when the person may open them. */
const people = computed(() => findModule("people"));
const links = computed(() => {
  const module = people.value;
  if (!module || !isModuleVisible(module, company.current)) return [];
  const base = `/c/${company.currentId}/people`;
  return [
    { id: "roles", to: `${base}/roles`, perm: "roles.manage" as const },
    { id: "positions", to: `${base}/positions`, perm: "positions.manage" as const },
  ].filter((link) => allowed(company.current, link));
});

const sections = computed<NavSection[]>(() => groupPanels(entries.value, links.value));
const panels = computed(() => sections.value.flatMap((section) => section.items.filter((item) => item.kind === "panel").map((item) => item.panel!)));

const param = computed(() => {
  const value = route.params.panel;
  return (Array.isArray(value) ? value[0] : value) || "";
});
const active = computed(() => panels.value.find((p) => p.id === param.value) ?? null);
/** Desktop opens the first panel when none is chosen; a phone shows the list instead. */
const shown = computed(() => active.value ?? (isPhone.value ? null : (panels.value[0] ?? null)));

const base = computed(() => `/c/${company.currentId}/settings`);

/** The row's name: this dictionary's `settings.panel.<id>` when it has one, else the panel's title. */
function label(panel: { id: string; title?: string }): string | null {
  const own = `settings.panel.${panel.id}`;
  if (te(own)) return t(own);
  if (panel.title && te(panel.title)) return t(panel.title);
  return messagesReady.value && panel.title ? t(panel.title) : null;
}
const hint = (id: string) => (te(`settings.panel.${id}.hint`) ? t(`settings.panel.${id}.hint`) : "");
const description = (id: string) => (te(`settings.panel.${id}.description`) ? t(`settings.panel.${id}.description`) : "");
const sectionTitle = (section: NavSection) => t(section.id === "account" ? "settings.section.account" : `shell.group.${section.id}`);
const iconOf = (icon: Component | undefined) => icon ?? Settings2;

// An unknown panel in the URL (switched off, or no permission) falls back to the list.
watch([param, panels], () => {
  if (param.value && panels.value.length && !active.value) void router.replace(base.value);
});
</script>

<template>
  <div>
    <PageHeader v-if="!isPhone || !shown" :title="t('settings.title')" :description="t('settings.description')" />
    <div class="grid grid-cols-1 gap-6 lg:grid-cols-[248px_minmax(0,1fr)] lg:gap-10">
      <!-- The panel list (a page of its own on a phone) -->
      <!-- On a desktop the list stays in view and scrolls on its own when it is taller than the window. -->
      <nav
        v-if="!isPhone || !shown"
        :aria-label="t('settings.title')"
        class="flex flex-col gap-5 lg:sticky lg:top-[calc(var(--topbar-h)+20px)] lg:-mx-1.5 lg:max-h-[calc(100dvh-var(--topbar-h)-44px)] lg:self-start lg:overflow-y-auto lg:overscroll-contain lg:px-1.5 lg:pb-2"
        data-settings-nav
      >
        <section v-for="section in sections" :key="section.id" :data-section="section.id">
          <h2 class="mb-1.5 px-2.5 text-xs font-semibold uppercase tracking-[0.06em] text-subtle max-md:px-1">{{ sectionTitle(section) }}</h2>
          <ul :class="isPhone ? 'overflow-hidden rounded-[14px] border border-line bg-surface' : 'flex flex-col gap-0.5'">
            <li v-for="item in section.items" :key="item.key">
              <!-- A row whose module dictionary hasn't arrived yet -->
              <div v-if="item.kind === 'panel' && !label(item.panel!)" :class="['flex items-center gap-3', isPhone ? 'border-b border-line px-4 py-3.5 last:border-b-0' : 'h-10 px-2.5']" aria-hidden="true">
                <SkeletonBlock :width="isPhone ? '36px' : '20px'" :height="isPhone ? '36px' : '20px'" radius="7px" />
                <SkeletonBlock width="60%" />
              </div>
              <RouterLink
                v-else
                :to="item.kind === 'panel' ? `${base}/${item.panel!.id}` : item.to!"
                :data-panel="item.kind === 'panel' ? item.panel!.id : undefined"
                :data-link="item.kind === 'link' ? item.id : undefined"
                :class="[
                  'pressable group flex items-center gap-3 text-left',
                  isPhone ? 'border-b border-line px-4 py-3 last:border-b-0' : 'h-10 rounded-[9px] px-2.5',
                  !isPhone && item.kind === 'panel' && shown?.id === item.panel!.id
                    ? 'bg-surface font-semibold text-fg shadow-[var(--sh-raised)]'
                    : 'text-muted hover:bg-highlight hover:text-fg',
                ]"
                :aria-current="item.kind === 'panel' && shown?.id === item.panel!.id ? 'page' : undefined"
              >
                <span :class="['grid shrink-0 place-items-center rounded-[8px]', isPhone ? 'size-9 bg-accent-soft text-accent-fg' : 'size-6']">
                  <component :is="iconOf(item.kind === 'panel' ? item.panel!.icon : ICONS[item.id])" :size="isPhone ? 18 : 16" aria-hidden="true" />
                </span>
                <span class="min-w-0 flex-1">
                  <span :class="['block truncate', isPhone ? 'text-base font-semibold text-fg' : 'text-base']" :title="isPhone ? undefined : (label(item.kind === 'panel' ? item.panel! : item) ?? '')">{{
                    label(item.kind === "panel" ? item.panel! : item)
                  }}</span>
                  <span v-if="isPhone && hint(item.id)" class="mt-0.5 block truncate text-sm text-muted">{{ hint(item.id) }}</span>
                </span>
                <ArrowUpRight v-if="item.kind === 'link'" :size="15" class="shrink-0 text-subtle transition-colors group-hover:text-muted" aria-hidden="true" />
                <ChevronRight v-else-if="isPhone" :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
              </RouterLink>
            </li>
          </ul>
        </section>
      </nav>

      <!-- The chosen panel -->
      <section v-if="shown" class="min-w-0" :data-panel-body="shown.id">
        <RouterLink v-if="isPhone" :to="base" class="-ml-1 mb-3 inline-flex items-center gap-1 rounded-[6px] px-1 py-0.5 text-sm font-medium text-muted hover:text-fg">
          <ChevronLeft :size="16" />
          {{ t("settings.allSettings") }}
        </RouterLink>
        <!-- This module's panels bring their own header (with their actions); the others get the same one here. -->
        <header v-if="!shown.own" class="mb-5" data-panel-header>
          <h2 v-if="label(shown)" class="text-lg font-semibold tracking-[-0.01em] text-fg">{{ label(shown) }}</h2>
          <SkeletonBlock v-else width="180px" height="22px" />
          <p v-if="description(shown.id)" class="mt-1 max-w-[640px] text-base text-muted">{{ description(shown.id) }}</p>
        </header>
        <component :is="shown.component" :key="`${shown.moduleId}:${shown.id}`" />
      </section>
      <EmptyState v-else-if="!panels.length" :title="t('settings.empty.title')" :description="t('settings.empty.body')" :icon="Settings2" />
    </div>
  </div>
</template>
