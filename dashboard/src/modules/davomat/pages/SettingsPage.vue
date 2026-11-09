<script setup lang="ts">
/**
 * Davomat's Settings (`settings/:panel?`): the panel list on the left, the chosen panel on the
 * right; on a phone the list is a page of its own and a panel opens over it with a back link.
 * Daybook's settings module isn't in this edition: the panels come from this edition's registry
 * (this module's Organization, Users and roles, Telegram and Your account, and every other
 * module's, such as attendance's rules), filtered by permission and switch, grouped as an
 * organization thinks of them: Organization · People and access · Integrations · Rules · Your
 * account. Face ID's settings are a page of their own; Rules links to it.
 */
import { ArrowUpRight, Building2, ChevronLeft, ChevronRight, Fingerprint, ScanFace, Send, Settings2, ShieldCheck, UserRound } from "@lucide/vue";
import { computed, nextTick, onMounted, ref, watch, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import CompanyLogo from "@/components/CompanyLogo.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { allowed, isModuleVisible } from "@/core/access";
import { editionInfo } from "@/core/edition";
import { findModule, modules, type SettingsPanel } from "@/core/modules";
import { ensureModuleMessages } from "@/i18n";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useCompanyStore } from "@/stores/company";

type SectionId = "organization" | "access" | "integrations" | "rules" | "account";
const SECTION_ORDER: readonly SectionId[] = ["organization", "access", "integrations", "rules", "account"];
/** Where this module's own panels go; every other module's panel is a rule. */
const OWN_SECTION: Record<string, SectionId> = { organization: "organization", users: "access", telegram: "integrations", account: "account" };

interface PanelEntry extends SettingsPanel {
  moduleId: string;
  moduleOrder: number;
  own: boolean;
}
type Item = { kind: "panel"; key: string; id: string; panel: PanelEntry } | { kind: "link"; key: string; id: string; to: string; icon: Component; title: string; hint: string };
interface Section {
  id: SectionId;
  items: Item[];
}

const { t, te } = useI18n();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const { isPhone } = useBreakpoints();

const ICONS: Record<string, Component> = { organization: Building2, users: ShieldCheck, telegram: Send, account: UserRound, attendance: Fingerprint };

// Other modules' panel titles live in their own dictionaries: rows wait for them as skeletons.
const messagesReady = ref(false);
onMounted(() => {
  const pending = modules.filter((module) => module.settings?.length && module.id !== "davomat").map((module) => ensureModuleMessages(module));
  void Promise.allSettled(pending).then(() => (messagesReady.value = true));
});

const entries = computed<PanelEntry[]>(() => {
  const list: PanelEntry[] = [];
  for (const module of modules) {
    if (!module.settings?.length || !isModuleVisible(module, company.current)) continue;
    for (const panel of module.settings) {
      if (!allowed(company.current, panel)) continue;
      list.push({ ...panel, icon: panel.icon ?? ICONS[panel.id], moduleId: module.id, moduleOrder: module.order, own: module.id === "davomat" });
    }
  }
  return list.sort((a, b) => Number(b.own) - Number(a.own) || a.moduleOrder - b.moduleOrder || (a.order ?? 0) - (b.order ?? 0));
});

/** Face ID's settings are a page of their own: a link among the rules for those who may change them. */
const faceLink = computed<Item | null>(() => {
  const faceid = findModule("faceid");
  if (!faceid || !isModuleVisible(faceid, company.current) || !allowed(company.current, { perm: "attendance.manage", feature: "face_id" })) return null;
  return {
    kind: "link",
    key: "link:faceid",
    id: "faceid",
    to: `/c/${company.currentId}/faceid/settings`,
    icon: ScanFace,
    title: t("davomat.settings.faceid.title"),
    hint: t("davomat.settings.faceid.hint"),
  };
});

const sections = computed<Section[]>(() => {
  const map = new Map<SectionId, Item[]>();
  for (const panel of entries.value) {
    const id = panel.own ? (OWN_SECTION[panel.id] ?? "organization") : "rules";
    const items = map.get(id) ?? [];
    items.push({ kind: "panel", key: `${panel.moduleId}:${panel.id}`, id: panel.id, panel });
    map.set(id, items);
  }
  if (faceLink.value) map.set("rules", [...(map.get("rules") ?? []), faceLink.value]);
  return SECTION_ORDER.filter((id) => map.get(id)?.length).map((id) => ({ id, items: map.get(id)! }));
});
const panels = computed(() => sections.value.flatMap((section) => section.items.flatMap((item) => (item.kind === "panel" ? [item.panel] : []))));

const param = computed(() => {
  const value = route.params.panel;
  return (Array.isArray(value) ? value[0] : value) || "";
});
const active = computed(() => panels.value.find((panel) => panel.id === param.value) ?? null);
/** A desktop opens the first panel when none is chosen; a phone shows the list. */
const shown = computed(() => active.value ?? (isPhone.value ? null : (panels.value[0] ?? null)));
const base = computed(() => `/c/${company.currentId}/settings`);

// An unknown panel in the address (switched off, or not for this role) falls back to the list,
// also when the page opens on one.
watch(
  [param, panels],
  () => {
    if (param.value && panels.value.length && !active.value) void router.replace(base.value);
  },
  { immediate: true },
);

/** A row's name: Davomat's own words for a panel when it has them, else the panel's title once loaded. */
function label(panel: PanelEntry): string | null {
  const own = `davomat.settings.panel.${panel.id}`;
  if (te(own)) return t(own);
  if (te(panel.title)) return t(panel.title);
  return messagesReady.value ? t(panel.title) : null;
}
function description(panel: PanelEntry): string {
  const own = panel.own ? `davomat.settings.${panel.id}.description` : `davomat.settings.panel.${panel.id}.description`;
  if (te(own)) return t(own);
  // Another module's panel: its own sentence, next to its title ("attendance.settings.description").
  const theirs = panel.title.replace(/\.title$/, ".description");
  return theirs !== panel.title && te(theirs) ? t(theirs) : "";
}
const sectionTitle = (id: SectionId) => t(`davomat.settings.section.${id}`);
const iconOf = (icon: Component | undefined) => icon ?? Settings2;

const organizationName = computed(() => company.current?.name ?? editionInfo.value.organization?.name ?? "");
const organizationLogo = computed(() => company.current?.logo ?? editionInfo.value.organization?.logo_url ?? null);

/** The list scrolls on its own when taller than the window: a panel opened from a link brings its row into view. */
const navEl = ref<HTMLElement | null>(null);
function revealActive(): void {
  const nav = navEl.value;
  const row = nav?.querySelector<HTMLElement>('[aria-current="page"]');
  if (!nav || !row || nav.scrollHeight <= nav.clientHeight) return;
  const box = nav.getBoundingClientRect();
  const at = row.getBoundingClientRect();
  if (at.top >= box.top && at.bottom <= box.bottom) return;
  nav.scrollTop += at.top - box.top - (nav.clientHeight - at.height) / 2;
}
watch([() => shown.value?.id, messagesReady], () => void nextTick(revealActive), { flush: "post" });
</script>

<template>
  <div data-davomat-settings>
    <PageHeader v-if="!isPhone || !shown" :title="t('davomat.nav.settings')" :description="t('davomat.settings.description')" />
    <div class="grid grid-cols-1 gap-6 lg:grid-cols-[264px_minmax(0,1fr)] lg:gap-10">
      <!-- The list (a page of its own on a phone) -->
      <nav
        v-if="!isPhone || !shown"
        ref="navEl"
        :aria-label="t('davomat.nav.settings')"
        class="flex flex-col gap-5 lg:sticky lg:top-[calc(var(--topbar-h)+20px)] lg:-mx-1.5 lg:max-h-[calc(100dvh-var(--topbar-h)-44px)] lg:self-start lg:overflow-y-auto lg:overscroll-contain lg:px-1.5 lg:pb-2"
        data-settings-nav
      >
        <!-- Whose settings these are -->
        <RouterLink
          v-if="organizationName"
          :to="`${base}/organization`"
          class="pressable ui-card flex items-center gap-3 p-3 hover:border-line-strong"
          data-org-card
        >
          <CompanyLogo :name="organizationName" :src="organizationLogo" :size="40" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-base font-semibold text-fg">{{ organizationName }}</span>
            <span class="block truncate text-xs text-muted">{{ editionInfo.product }}</span>
          </span>
          <ChevronRight :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
        </RouterLink>

        <section v-for="section in sections" :key="section.id" :data-section="section.id">
          <h2 class="mb-1.5 px-2.5 text-xs font-semibold uppercase tracking-[0.06em] text-subtle max-md:px-1">{{ sectionTitle(section.id) }}</h2>
          <ul :class="isPhone ? 'overflow-hidden rounded-[14px] border border-line bg-surface' : 'flex flex-col gap-0.5'">
            <li v-for="item in section.items" :key="item.key">
              <!-- A row whose module dictionary hasn't arrived yet -->
              <div
                v-if="item.kind === 'panel' && !label(item.panel)"
                :class="['flex items-center gap-3', isPhone ? 'border-b border-line px-4 py-3.5 last:border-b-0' : 'h-10 px-2.5']"
                aria-hidden="true"
              >
                <SkeletonBlock :width="isPhone ? '36px' : '20px'" :height="isPhone ? '36px' : '20px'" radius="7px" />
                <SkeletonBlock width="60%" />
              </div>
              <RouterLink
                v-else
                :to="item.kind === 'panel' ? `${base}/${item.panel.id}` : item.to"
                :data-panel="item.kind === 'panel' ? item.panel.id : undefined"
                :data-link="item.kind === 'link' ? item.id : undefined"
                :class="[
                  'pressable group flex items-center gap-3 text-left',
                  isPhone ? 'border-b border-line px-4 py-3 last:border-b-0' : 'h-10 rounded-[9px] px-2.5',
                  !isPhone && item.kind === 'panel' && shown?.id === item.panel.id
                    ? 'bg-surface font-semibold text-fg shadow-[var(--sh-raised)]'
                    : 'text-muted hover:bg-highlight hover:text-fg',
                ]"
                :aria-current="item.kind === 'panel' && shown?.id === item.panel.id ? 'page' : undefined"
              >
                <span :class="['grid shrink-0 place-items-center rounded-[8px]', isPhone ? 'size-9 bg-accent-soft text-accent-fg' : 'size-6']">
                  <component :is="item.kind === 'panel' ? iconOf(item.panel.icon) : item.icon" :size="isPhone ? 18 : 16" aria-hidden="true" />
                </span>
                <span class="min-w-0 flex-1">
                  <span :class="['block truncate', isPhone ? 'text-base font-semibold text-fg' : 'text-base']">{{
                    item.kind === "panel" ? label(item.panel) : item.title
                  }}</span>
                  <span v-if="isPhone" class="mt-0.5 line-clamp-2 text-sm text-muted">{{ item.kind === "panel" ? description(item.panel) : item.hint }}</span>
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
          {{ t("davomat.settings.all") }}
        </RouterLink>
        <header class="mb-5" data-panel-header>
          <h2 v-if="label(shown)" class="text-lg font-semibold tracking-[-0.01em] text-fg">{{ label(shown) }}</h2>
          <SkeletonBlock v-else width="180px" height="22px" />
          <p v-if="description(shown)" class="mt-1 max-w-[640px] text-base text-muted">{{ description(shown) }}</p>
        </header>
        <component :is="shown.component" :key="`${shown.moduleId}:${shown.id}`" />
      </section>
      <EmptyState v-else-if="!panels.length" :title="t('davomat.settings.empty.title')" :description="t('davomat.settings.empty.body')" :icon="Settings2" />
    </div>
  </div>
</template>
