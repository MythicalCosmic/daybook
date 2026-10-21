<script setup lang="ts">
/**
 * Settings (plan §6.2): the panel list on the left, the chosen panel on the right
 * (`settings/:panel`). Panels come from every module's `settings` in the registry, filtered by
 * permission and module switch: this module's own first, then the modules', in sidebar order.
 * On a phone the list is a page of its own and a panel opens over it with a back link.
 */
import { Bell, Building2, ChevronLeft, ChevronRight, LayoutGrid, MapPin, MonitorSmartphone, Settings2, UserPlus, type LucideIcon } from "@lucide/vue";
import { computed, onMounted, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import { allowed, isModuleVisible } from "@/core/access";
import { modules, type SettingsPanel } from "@/core/modules";
import { ensureModuleMessages } from "@/i18n";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useCompanyStore } from "@/stores/company";

interface PanelEntry extends SettingsPanel {
  moduleId: string;
  own: boolean;
}

const { t, te } = useI18n();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const { isPhone } = useBreakpoints();

/** Icons of this module's own panels (kept out of the registry entry, which is in the first bundle). */
const OWN_ICONS: Record<string, LucideIcon> = {
  company: Building2,
  features: LayoutGrid,
  branches: MapPin,
  invite: UserPlus,
  notifications: Bell,
  sessions: MonitorSmartphone,
};

const panels = computed<PanelEntry[]>(() => {
  const list: PanelEntry[] = [];
  for (const module of modules) {
    if (!module.settings?.length || !isModuleVisible(module, company.current)) continue;
    for (const panel of module.settings) {
      const own = module.id === "settings";
      if (allowed(company.current, panel)) list.push({ ...panel, icon: panel.icon ?? (own ? OWN_ICONS[panel.id] : undefined), moduleId: module.id, own });
    }
  }
  const ownFirst = (p: PanelEntry) => (p.own ? 0 : 1);
  return list.sort((a, b) => ownFirst(a) - ownFirst(b) || (a.own ? (a.order ?? 0) - (b.order ?? 0) : 0));
});
const ownPanels = computed(() => panels.value.filter((p) => p.own));
const modulePanels = computed(() => panels.value.filter((p) => !p.own));

const param = computed(() => {
  const value = route.params.panel;
  return (Array.isArray(value) ? value[0] : value) || "";
});
const active = computed(() => panels.value.find((p) => p.id === param.value) ?? null);
/** Desktop opens the first panel when none is chosen; a phone shows the list instead. */
const shown = computed(() => active.value ?? (isPhone.value ? null : (panels.value[0] ?? null)));

const base = computed(() => `/c/${company.currentId}/settings`);
const hint = (panel: PanelEntry) => {
  const key = `settings.panel.${panel.id}.hint`;
  return panel.own && te(key) ? t(key) : "";
};

// An unknown panel in the URL (switched off, or no permission) falls back to the list.
watch([param, panels], () => {
  if (param.value && panels.value.length && !active.value) void router.replace(base.value);
});

// Other modules' panel titles live in their own dictionaries.
onMounted(() => {
  for (const module of modules) if (module.settings?.length && module.id !== "settings") void ensureModuleMessages(module).catch(() => undefined);
});
</script>

<template>
  <div>
    <PageHeader
      v-if="!isPhone || !shown"
      :title="t('settings.title')"
      :description="t('settings.description')"
    />
    <div class="grid grid-cols-1 gap-6 lg:grid-cols-[240px_minmax(0,1fr)] lg:gap-8">
      <!-- The panel list (a page of its own on a phone) -->
      <nav v-if="!isPhone || !shown" :aria-label="t('settings.title')" class="lg:sticky lg:top-[calc(var(--topbar-h)+20px)] lg:self-start">
        <ul :class="isPhone ? 'overflow-hidden rounded-[14px] border border-line bg-surface' : 'flex flex-col gap-0.5'">
          <li v-for="panel in ownPanels" :key="`${panel.moduleId}:${panel.id}`">
            <RouterLink
              :to="`${base}/${panel.id}`"
              :class="[
                'pressable group flex items-center gap-3 text-left',
                isPhone ? 'border-b border-line px-4 py-3.5 last:border-b-0' : 'h-10 rounded-[9px] px-2.5',
                !isPhone && shown?.id === panel.id ? 'bg-surface font-semibold text-fg shadow-[var(--sh-raised)]' : 'text-muted hover:bg-highlight hover:text-fg',
              ]"
              :aria-current="shown?.id === panel.id ? 'page' : undefined"
            >
              <span :class="['grid shrink-0 place-items-center rounded-[8px]', isPhone ? 'size-9 bg-accent-soft text-accent-fg' : 'size-6']">
                <component :is="panel.icon ?? Settings2" :size="isPhone ? 18 : 16" />
              </span>
              <span class="min-w-0 flex-1">
                <span :class="['block truncate', isPhone ? 'text-base font-semibold text-fg' : 'text-base']">{{ t(panel.title) }}</span>
                <span v-if="isPhone && hint(panel)" class="mt-0.5 block truncate text-sm text-muted">{{ hint(panel) }}</span>
              </span>
              <ChevronRight v-if="isPhone" :size="16" class="shrink-0 text-subtle" />
            </RouterLink>
          </li>
        </ul>
        <template v-if="modulePanels.length">
          <p class="mb-1.5 mt-5 px-2.5 text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("settings.modulesHeading") }}</p>
          <ul :class="isPhone ? 'overflow-hidden rounded-[14px] border border-line bg-surface' : 'flex flex-col gap-0.5'">
            <li v-for="panel in modulePanels" :key="`${panel.moduleId}:${panel.id}`">
              <RouterLink
                :to="`${base}/${panel.id}`"
                :class="[
                  'pressable flex items-center gap-3',
                  isPhone ? 'border-b border-line px-4 py-3.5 last:border-b-0' : 'h-10 rounded-[9px] px-2.5',
                  !isPhone && shown?.id === panel.id ? 'bg-surface font-semibold text-fg shadow-[var(--sh-raised)]' : 'text-muted hover:bg-highlight hover:text-fg',
                ]"
              >
                <component :is="panel.icon ?? Settings2" :size="16" class="shrink-0" />
                <span class="min-w-0 flex-1 truncate text-base">{{ t(panel.title) }}</span>
                <ChevronRight v-if="isPhone" :size="16" class="shrink-0 text-subtle" />
              </RouterLink>
            </li>
          </ul>
        </template>
      </nav>

      <!-- The chosen panel -->
      <section v-if="shown" class="min-w-0">
        <RouterLink v-if="isPhone" :to="base" class="-ml-1 mb-3 inline-flex items-center gap-1 rounded-[6px] px-1 py-0.5 text-sm font-medium text-muted hover:text-fg">
          <ChevronLeft :size="16" />
          {{ t("settings.allSettings") }}
        </RouterLink>
        <component :is="shown.component" :key="`${shown.moduleId}:${shown.id}`" />
      </section>
      <EmptyState v-else-if="!panels.length" :title="t('settings.empty.title')" :description="t('settings.empty.body')" :icon="Settings2" />
    </div>
  </div>
</template>
